"""segment_filter 模块测试."""

from __future__ import annotations

import numpy as np

from src.segment_filter import filter_target_speaker, mark_low_confidence
from src.types import Segment


def test_filter_target_speaker_keeps_high_similarity() -> None:
    seg = Segment(start=0.0, end=1.0)
    audio = np.zeros(16000, dtype=np.float32)
    enroll = np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32)

    def fake_extract(*_args, **_kwargs):
        return np.array([0.95, 0.05, 0.0, 0.0], dtype=np.float32)

    import src.segment_filter as sf

    original_extract = sf._extract_segment_embedding
    sf._extract_segment_embedding = fake_extract  # type: ignore[assignment]
    try:
        results = filter_target_speaker([seg], audio, 16000, enroll, {}, similarity_threshold=0.7)
    finally:
        sf._extract_segment_embedding = original_extract

    assert len(results) == 1
    assert seg.is_user is True
    assert seg.speaker_label == "user"
    assert seg.speaker_confidence > 0.7


def test_filter_target_speaker_filters_low_similarity() -> None:
    seg = Segment(start=0.0, end=1.0)
    audio = np.zeros(16000, dtype=np.float32)
    enroll = np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32)

    def fake_extract(*_args, **_kwargs):
        return np.array([0.0, 1.0, 0.0, 0.0], dtype=np.float32)

    import src.segment_filter as sf

    original_extract = sf._extract_segment_embedding
    sf._extract_segment_embedding = fake_extract  # type: ignore[assignment]
    try:
        results = filter_target_speaker([seg], audio, 16000, enroll, {}, similarity_threshold=0.7)
    finally:
        sf._extract_segment_embedding = original_extract

    assert len(results) == 0
    assert seg.is_user is False
    assert seg.speaker_label == "other"


def test_mark_low_confidence() -> None:
    high = Segment(start=0.0, end=1.0, speaker_confidence=0.9)
    low = Segment(start=1.0, end=2.0, speaker_confidence=0.3)
    mark_low_confidence([high, low], 0.5)
    assert high.needs_review is False
    assert low.needs_review is True
