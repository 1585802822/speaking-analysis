"""分析流水线协调器.

MVP 只保留两个核心能力: 音频分离 + 发音分析。
本流水线负责发音分析: 预处理 -> 说话人分离 -> ASR 转写 -> ISE 发音评测。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .diarization import DiarizationModule
from .enrollment import EnrollmentManager
from .preprocessor import Preprocessor
from .pronunciation_analyzer import PronunciationAnalyzer
from .reporter import Reporter
from .transcriber import Transcriber
from .types import ProcessingResult


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

    def process(self, audio_path: str) -> ProcessingResult:
        """处理单个音频文件."""
        path = Path(audio_path)
        segments = self.preprocessor.process(path)
        voiceprint = self.enrollment.load_voiceprint()
        user_segments = self.diarization.identify_user(segments, voiceprint, str(path))
        utterances = self.transcriber.transcribe_user_segments(path, user_segments)
        analyses = [
            self.pronunciation_analyzer.analyze(utterances, path),
        ]
        result = ProcessingResult(
            audio_path=str(path),
            duration_sec=self.preprocessor.get_duration(path),
            user_speech_sec=sum(s.end - s.start for s in user_segments),
            utterances=utterances,
            analyses=analyses,
            low_confidence_segments=[s for s in user_segments if s.needs_review],
        )
        self.reporter.save(result, path.stem)
        return result
