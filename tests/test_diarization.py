"""说话人筛选测试."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from src.diarization import DiarizationModule
from src.types import Segment


def _module(tmp_path: Path) -> DiarizationModule:
    config = {
        "voiceprint_dir": str(tmp_path / "voiceprint"),
        "speaker": {
            "similarity_threshold": 0.75,
            "low_confidence_threshold": 0.55,
            "embedding_dim": 4,
        },
        "segmentation": {"target_sample_rate": 16000},
        "asr": {"device": "cpu"},
    }
    return DiarizationModule(config)


def test_cosine_similarity() -> None:
    module = _module(Path("/tmp"))
    a = np.array([1.0, 0.0, 0.0], dtype=np.float32)
    b = np.array([0.0, 1.0, 0.0], dtype=np.float32)
    assert pytest.approx(0.0) == module._cosine_similarity(a, b)

    c = np.array([1.0, 1.0, 0.0], dtype=np.float32) / np.sqrt(2)
    assert pytest.approx(1.0) == module._cosine_similarity(a, a)
    assert pytest.approx(0.7071, rel=1e-3) == module._cosine_similarity(a, c)


def test_cosine_similarity_zero_vector() -> None:
    module = _module(Path("/tmp"))
    a = np.array([1.0, 0.0], dtype=np.float32)
    b = np.array([0.0, 0.0], dtype=np.float32)
    assert module._cosine_similarity(a, b) == 0.0


def test_identify_user_requires_voiceprint(tmp_path: Path) -> None:
    module = _module(tmp_path)
    with pytest.raises(RuntimeError, match="未找到注册声纹"):
        module.identify_user([], None)


def test_identify_user_stub_returns_empty(tmp_path: Path) -> None:
    """占位模式下嵌入为零向量，相似度为 0，不应判定为用户."""
    module = _module(tmp_path)
    voiceprint = {"embedding": np.zeros(4, dtype=np.float32)}
    segments = [
        Segment(start=0.0, end=1.0),
        Segment(start=2.0, end=3.0),
    ]
    user_segments = module.identify_user(
        segments, voiceprint, str(tmp_path / "nonexistent.wav")
    )
    assert user_segments == []
    for seg in segments:
        assert seg.confidence == 0.0
        assert seg.is_user is False


def test_identify_user_with_mocked_embedding(tmp_path: Path) -> None:
    """模拟高相似度片段被判定为用户，低相似度片段被过滤."""
    module = _module(tmp_path)
    voiceprint = {"embedding": np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32)}

    high_seg = Segment(start=0.0, end=1.0)
    low_seg = Segment(start=1.5, end=2.5)

    def fake_extract(seg: Segment, audio_path: str | None) -> np.ndarray:
        if seg is high_seg:
            return np.array([0.9, 0.1, 0.0, 0.0], dtype=np.float32)
        return np.array([0.0, 1.0, 0.0, 0.0], dtype=np.float32)

    module._extract_segment_embedding = fake_extract  # type: ignore[method-assign]

    user_segments = module.identify_user(
        [high_seg, low_seg], voiceprint, str(tmp_path / "audio.wav")
    )
    assert len(user_segments) == 1
    assert user_segments[0] is high_seg
    assert high_seg.is_user is True
    assert low_seg.is_user is False
    assert high_seg.confidence > module.similarity_threshold
    assert low_seg.confidence < module.similarity_threshold
    assert high_seg.speaker_label == "user"
    assert low_seg.speaker_label == "other"
    assert high_seg.speaker_confidence == high_seg.confidence


def test_identify_user_marks_low_confidence(tmp_path: Path) -> None:
    """低置信度片段应被标记为 needs_review."""
    module = _module(tmp_path)
    voiceprint = {"embedding": np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32)}

    seg = Segment(start=0.0, end=1.0)

    def fake_extract(_seg: Segment, _audio_path: str | None) -> np.ndarray:
        return np.array([0.0, 1.0, 0.0, 0.0], dtype=np.float32)

    module._extract_segment_embedding = fake_extract  # type: ignore[method-assign]

    module.identify_user([seg], voiceprint, str(tmp_path / "audio.wav"))
    assert seg.needs_review is True
    assert seg.confidence < module.low_confidence_threshold
