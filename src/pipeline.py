"""分析流水线协调器.

本流水线负责完整处理流程:
    预处理(句子级切分) -> 声纹分离 -> ASR 路由转写 -> 数据入库 -> 发音分析 -> 生成报告.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .db import Database
from .diarization import DiarizationModule
from .enrollment import EnrollmentManager
from .preprocessor import Preprocessor
from .pronunciation_analyzer import PronunciationAnalyzer
from .recording_id import recording_id_from_path
from .reporter import Reporter
from .sentence_segmenter import SentenceSegmenter
from .speaker_separator import SpeakerSeparator
from .transcriber import Transcriber
from .types import ProcessingResult, SegmentTranscription, Utterance


class Pipeline:
    """处理单个录音的完整流水线."""

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        self.preprocessor = Preprocessor(config)
        self.diarization = DiarizationModule(config)
        self.enrollment = EnrollmentManager(config)
        self.transcriber = Transcriber(config)
        self.pronunciation_analyzer = PronunciationAnalyzer(config)
        self.reporter = Reporter(config)
        self.segmenter = SentenceSegmenter(config)
        self.separator = SpeakerSeparator(config)
        self.db = Database(config.get("db_path", "./data/db/speaking_analysis.db"))

    def process(self, audio_path: str) -> ProcessingResult:
        """处理单个音频文件."""
        path = Path(audio_path)
        recording_id = recording_id_from_path(path)
        duration_sec = self.preprocessor.get_duration(path)

        # Stage 1: 句子级预处理与持久化
        segments, audio_paths, _meta_path = self.segmenter.segment(path, recording_id)
        self.db.save_recording(
            recording_id,
            str(path),
            duration_sec,
            sample_rate=self.segmenter.sample_rate,
            status="segmented",
        )
        self.db.save_segments(recording_id, segments, audio_paths)
        # 重跑时清理不再存在的旧片段（数据库行 + WAV 文件）
        self.db.cleanup_orphan_segments(
            recording_id,
            [s.segment_index for s in segments if s.segment_index is not None],
        )

        # Stage 2: 声纹初次分离
        voiceprint = self.enrollment.load_voiceprint()
        if voiceprint is None:
            # 没有注册声纹时，所有片段标记为 other，避免阻塞流程
            for seg in segments:
                seg.speaker_label = "other"
                seg.is_user = False
                seg.speaker_confidence = 0.0
                seg.confidence = 0.0
                seg.needs_review = False
            self.separator._save_diarization_json(recording_id, segments)
            self.db.save_diarization(recording_id, segments)
        else:
            segments = self.separator.separate(segments, recording_id, voiceprint)
        self.db.update_recording_status(recording_id, "diarized")

        # Stage 3: 差异化 ASR 路由
        transcriptions = self.transcriber.transcribe_segments(path, segments, recording_id)
        self.db.save_asr_results(recording_id, transcriptions)
        self.db.update_recording_status(recording_id, "transcribed")

        # Stage 4: 准备下游分析用的用户 utterances
        user_utterances = self._build_user_utterances(transcriptions)

        # Stage 5: 发音分析（仅对用户语音）
        analyses = []
        if user_utterances:
            analyses.append(
                self.pronunciation_analyzer.analyze(user_utterances, path),
            )

        user_segments = [s for s in segments if s.speaker_label == "user"]
        result = ProcessingResult(
            audio_path=str(path),
            duration_sec=duration_sec,
            user_speech_sec=sum(s.end - s.start for s in user_segments),
            utterances=user_utterances,
            analyses=analyses,
            low_confidence_segments=[s for s in segments if s.needs_review],
            segment_transcriptions=transcriptions,
            recording_id=recording_id,
        )
        self.reporter.save(result, path.stem)
        return result

    @staticmethod
    def _build_user_utterances(
        transcriptions: list[SegmentTranscription],
    ) -> list[Utterance]:
        """从所有转写结果中提取 user 片段的 utterances."""
        utterances: list[Utterance] = []
        for tx in transcriptions:
            if tx.speaker_label != "user" or tx.status != "success":
                continue
            utterances.append(
                Utterance(
                    text=tx.text,
                    start=tx.start,
                    end=tx.end,
                    words=tx.words,
                )
            )
        return utterances
