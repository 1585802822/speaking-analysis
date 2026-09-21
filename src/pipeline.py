"""分析流水线协调器."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .audio_analyzer import AudioAnalyzer
from .diarization import DiarizationModule
from .emotion_analyzer import EmotionAnalyzer
from .enrollment import EnrollmentManager
from .preprocessor import Preprocessor
from .pronunciation_analyzer import PronunciationAnalyzer
from .reporter import Reporter
from .text_analyzer import TextAnalyzer
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
        self.text_analyzer = TextAnalyzer(config)
        self.audio_analyzer = AudioAnalyzer(config)
        self.emotion_analyzer = EmotionAnalyzer(config)
        self.pronunciation_analyzer = PronunciationAnalyzer(config)
        self.reporter = Reporter(config)

    def process(self, audio_path: str) -> ProcessingResult:
        """处理单个音频文件."""
        path = Path(audio_path)
        segments = self.preprocessor.process(path)
        voiceprint = self.enrollment.load_voiceprint()
        user_segments = self.diarization.identify_user(
            segments, voiceprint, str(path)
        )
        utterances = self.transcriber.transcribe_user_segments(path, user_segments)
        analyses = [
            self.text_analyzer.analyze(utterances),
            self.audio_analyzer.analyze(path, utterances, user_segments),
            self.emotion_analyzer.analyze(path, user_segments),
            self.pronunciation_analyzer.analyze(utterances),
        ]
        result = ProcessingResult(
            audio_path=str(path),
            duration_sec=self.preprocessor.get_duration(path),
            user_speech_sec=sum(s.end - s.start for s in user_segments),
            utterances=utterances,
            analyses=analyses,
            low_confidence_segments=[
                s for s in user_segments if s.needs_review
            ],
        )
        self.reporter.save(result, path.stem)
        return result
