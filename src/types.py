"""共享类型定义."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Segment:
    """音频片段."""

    start: float
    end: float
    speaker: str | None = None
    is_user: bool | None = None
    confidence: float | None = None  # 保留兼容，语义同 speaker_confidence
    vad_confidence: float = 1.0
    speaker_label: str | None = None
    speaker_confidence: float | None = None
    needs_review: bool = False


@dataclass
class Word:
    """ASR 词/字结果."""

    text: str
    start: float
    end: float
    confidence: float | None = None


@dataclass
class Utterance:
    """ASR 句子结果."""

    text: str
    start: float
    end: float
    words: list[Word] = field(default_factory=list)


@dataclass
class AnalysisResult:
    """单个分析维度的发现."""

    dimension: str
    findings: list[dict[str, Any]] = field(default_factory=list)
    summary: str = ""


@dataclass
class ProcessingResult:
    """一次录音的完整处理结果."""

    audio_path: str
    duration_sec: float
    user_speech_sec: float
    utterances: list[Utterance] = field(default_factory=list)
    analyses: list[AnalysisResult] = field(default_factory=list)
    low_confidence_segments: list[Segment] = field(default_factory=list)
