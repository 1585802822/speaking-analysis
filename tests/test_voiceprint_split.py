"""声纹二次切分测试."""

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
        "segmentation": {"target_sample_rate": 16000, "parallel_workers": 1},
        "asr": {"device": "cpu"},
    }
    return DiarizationModule(config)


# 伪造音频数组: 16kHz, 全零, 足够覆盖测试时间段
_FAKE_AUDIO = (np.zeros(16000 * 10, dtype=np.float32), 16000)


def test_split_by_voiceprint_requires_voiceprint(tmp_path: Path) -> None:
    module = _module(tmp_path)
    with pytest.raises(RuntimeError, match="未找到注册声纹"):
        module.split_by_voiceprint([], tmp_path / "audio.wav", audio_array=_FAKE_AUDIO)


def test_split_by_voiceprint_zero_reference(tmp_path: Path) -> None:
    module = _module(tmp_path)
    voiceprint = {"embedding": np.zeros(4, dtype=np.float32)}
    segments = [Segment(start=0.0, end=3.0)]
    result = module.split_by_voiceprint(
        segments, tmp_path / "audio.wav", voiceprint=voiceprint, audio_array=_FAKE_AUDIO
    )
    assert result == []
    assert segments[0].is_user is False
    assert segments[0].speaker_label == "unknown"


def test_merge_same_speaker_windows(tmp_path: Path) -> None:
    module = _module(tmp_path)
    windows = [
        Segment(start=0.0, end=1.0, speaker_label="user", speaker_confidence=0.9),
        Segment(start=1.0, end=2.0, speaker_label="user", speaker_confidence=0.8),
        Segment(start=2.0, end=3.0, speaker_label="other", speaker_confidence=0.3),
        Segment(start=3.0, end=4.0, speaker_label="user", speaker_confidence=0.95),
    ]
    merged = module._merge_same_speaker_windows(windows)
    assert len(merged) == 3
    assert merged[0].start == 0.0
    assert merged[0].end == 2.0
    assert merged[0].speaker_label == "user"
    assert merged[1].speaker_label == "other"
    assert merged[2].start == 3.0
    assert merged[2].end == 4.0


def test_split_by_voiceprint_with_mocked_embedding(tmp_path: Path) -> None:
    """模拟高/低相似度窗口，验证标签与合并."""
    module = _module(tmp_path)
    voiceprint = {"embedding": np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32)}

    seg = Segment(start=0.0, end=6.0)

    def fake_extract(seg: Segment, audio_path: str | Path | None, audio_array=None) -> np.ndarray:
        # 前 3 秒高相似度 (cos~0.9)，后 3 秒中等相似度 (cos~0.6 → "other")
        if seg.end <= 3.0:
            return np.array([0.9, 0.1, 0.0, 0.0], dtype=np.float32)
        return np.array([0.6, 0.8, 0.0, 0.0], dtype=np.float32)

    module._extract_segment_embedding = fake_extract  # type: ignore[method-assign]

    result = module.split_by_voiceprint(
        [seg],
        tmp_path / "audio.wav",
        voiceprint=voiceprint,
        window_sec=3.0,
        hop_sec=3.0,
        audio_array=_FAKE_AUDIO,
    )
    assert len(result) == 2
    assert result[0].speaker_label == "user"
    assert result[1].speaker_label == "other"
    assert result[0].end == pytest.approx(3.0)
    assert result[1].start == pytest.approx(3.0)


def test_split_by_voiceprint_marks_low_confidence(tmp_path: Path) -> None:
    module = _module(tmp_path)
    voiceprint = {"embedding": np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32)}

    seg = Segment(start=0.0, end=3.0)

    def fake_extract(_seg: Segment, _audio_path: str | Path | None, audio_array=None) -> np.ndarray:
        return np.array([0.0, 1.0, 0.0, 0.0], dtype=np.float32)

    module._extract_segment_embedding = fake_extract  # type: ignore[method-assign]

    result = module.split_by_voiceprint(
        [seg],
        tmp_path / "audio.wav",
        voiceprint=voiceprint,
        window_sec=3.0,
        hop_sec=1.5,
        audio_array=_FAKE_AUDIO,
    )
    assert len(result) == 1
    assert result[0].speaker_label == "unknown"
    assert result[0].needs_review is True
    assert result[0].speaker_confidence < module.low_confidence_threshold


def test_merge_trims_overlap_between_speakers(tmp_path: Path) -> None:
    """hop < window 时相邻 run 重叠，合并后应以重叠中点为界、互不重叠."""
    module = _module(tmp_path)
    windows = [
        Segment(start=0.0, end=3.0, speaker_label="user", speaker_confidence=0.9),
        Segment(start=1.5, end=4.5, speaker_label="other", speaker_confidence=0.3),
        Segment(start=3.0, end=6.0, speaker_label="other", speaker_confidence=0.35),
    ]
    merged = module._merge_same_speaker_windows(windows)
    assert len(merged) == 2
    assert merged[0].speaker_label == "user"
    assert merged[1].speaker_label == "other"
    # user run 原为 [0,3], other run 原为 [1.5,6], 边界取中点 2.25
    assert merged[0].start == pytest.approx(0.0)
    assert merged[0].end == pytest.approx(2.25)
    assert merged[1].start == pytest.approx(2.25)
    assert merged[1].end == pytest.approx(6.0)


def test_merge_same_label_union_still_contiguous(tmp_path: Path) -> None:
    """同标签重叠窗口合并为并集，输出保持时间有序且不重叠."""
    module = _module(tmp_path)
    windows = [
        Segment(start=0.0, end=3.0, speaker_label="user", speaker_confidence=0.9),
        Segment(start=1.5, end=4.5, speaker_label="user", speaker_confidence=0.8),
        Segment(start=3.0, end=6.0, speaker_label="user", speaker_confidence=0.85),
        Segment(start=6.5, end=9.5, speaker_label="other", speaker_confidence=0.3),
    ]
    merged = module._merge_same_speaker_windows(windows)
    assert len(merged) == 2
    assert merged[0].start == pytest.approx(0.0)
    assert merged[0].end == pytest.approx(6.0)
    assert merged[1].start == pytest.approx(6.5)
    assert merged[1].end == pytest.approx(9.5)
    assert merged[0].speaker_confidence == pytest.approx((0.9 + 0.8 + 0.85) / 3)


def test_merge_output_never_overlaps(tmp_path: Path) -> None:
    """混合标签 + 待复核窗口的通用性质：输出有序、连续片段互不重叠."""
    module = _module(tmp_path)
    windows = [
        Segment(start=0.0, end=3.0, speaker_label="user", speaker_confidence=0.9),
        Segment(start=1.5, end=4.5, speaker_label="user", speaker_confidence=0.88),
        Segment(start=3.0, end=6.0, speaker_label="unknown", speaker_confidence=0.1, needs_review=True),
        Segment(start=4.5, end=7.5, speaker_label="other", speaker_confidence=0.3),
        Segment(start=6.0, end=9.0, speaker_label="other", speaker_confidence=0.4),
    ]
    merged = module._merge_same_speaker_windows(windows)
    for prev, cur in zip(merged, merged[1:]):
        assert cur.start >= prev.end - 1e-9, "相邻片段存在重叠"
    starts = [m.start for m in merged]
    assert starts == sorted(starts)
    ends = [m.end for m in merged]
    assert ends == sorted(ends)


def test_merge_coalesces_consecutive_unknown_windows(tmp_path: Path) -> None:
    """连续同标签的待复核(unknown)窗口应合并为一个 run，避免碎片化."""
    module = _module(tmp_path)
    windows = [
        Segment(start=0.0, end=3.0, speaker_label="other", speaker_confidence=0.3),
        Segment(start=1.5, end=4.5, speaker_label="unknown", speaker_confidence=0.1, needs_review=True),
        Segment(start=3.0, end=6.0, speaker_label="unknown", speaker_confidence=0.2, needs_review=True),
        Segment(start=4.5, end=7.5, speaker_label="unknown", speaker_confidence=0.15, needs_review=True),
        Segment(start=6.0, end=9.0, speaker_label="user", speaker_confidence=0.9),
    ]
    merged = module._merge_same_speaker_windows(windows)
    assert len(merged) == 3
    assert [m.speaker_label for m in merged] == ["other", "unknown", "user"]
    assert merged[1].needs_review is True
    # unknown run 原始并集 [1.5, 7.5]，与相邻 run 在重叠中点 2.25 / 6.75 切开
    assert merged[1].start == pytest.approx(2.25)
    assert merged[1].end == pytest.approx(6.75)
    for prev, cur in zip(merged, merged[1:]):
        assert cur.start >= prev.end - 1e-9


def test_merge_hard_clamp_when_middle_run_consumed(tmp_path: Path) -> None:
    """中间短 run 被裁剪耗尽丢弃后, 后一段不得越过前一段结尾（硬边界保障）."""
    module = _module(tmp_path)
    windows = [
        Segment(start=0.0, end=4.5, speaker_label="user", speaker_confidence=0.9),
        Segment(start=2.0, end=2.5, speaker_label="other", speaker_confidence=0.3),
        Segment(start=3.0, end=10.0, speaker_label="user", speaker_confidence=0.85),
    ]
    merged = module._merge_same_speaker_windows(windows)
    # 短 other run 在中点裁剪后耗尽被丢弃, 两个 user run 不得重叠
    labels = [m.speaker_label for m in merged]
    assert labels == ["user", "user"]
    for prev, cur in zip(merged, merged[1:]):
        assert cur.start >= prev.end - 1e-9


def test_smooth_window_labels_removes_isolated_flip(tmp_path: Path) -> None:
    """孤立的单窗口标签翻转应被邻居标签取代."""
    module = _module(tmp_path)
    windows = [
        Segment(start=0.0, end=3.0, speaker_label="user"),
        Segment(start=1.5, end=4.5, speaker_label="other"),
        Segment(start=3.0, end=6.0, speaker_label="user"),
        Segment(start=4.5, end=7.5, speaker_label="user"),
    ]
    module._smooth_window_labels(windows)
    assert [w.speaker_label for w in windows] == ["user", "user", "user", "user"]
    assert windows[1].is_user is True


def test_split_uses_full_length_tail_windows(tmp_path: Path) -> None:
    """尾窗应回退补足整窗长度，避免过短窗口嵌入失真."""
    module = _module(tmp_path)
    voiceprint = {"embedding": np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32)}

    seen: list[tuple[float, float]] = []

    def fake_extract(seg: Segment, _audio_path: str | Path | None, audio_array=None) -> np.ndarray:
        seen.append((seg.start, seg.end))
        return np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32)

    module._extract_segment_embedding = fake_extract  # type: ignore[method-assign]

    result = module.split_by_voiceprint(
        [Segment(start=0.0, end=4.0)],
        tmp_path / "audio.wav",
        voiceprint=voiceprint,
        window_sec=3.0,
        hop_sec=1.5,
        audio_array=_FAKE_AUDIO,
    )
    # 常规窗 [0,3] + 回退尾窗 [1,4], 两个窗口都满 3s
    assert seen == [(0.0, 3.0), (1.0, 4.0)]
    assert len(result) == 1
    assert result[0].start == pytest.approx(0.0)
    assert result[0].end == pytest.approx(4.0)


def test_split_segments_processed_in_time_order(tmp_path: Path) -> None:
    """输入片段乱序时应先排序再切窗, 保证窗口时间有序."""
    module = _module(tmp_path)
    voiceprint = {"embedding": np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32)}

    seen: list[float] = []

    def fake_extract(seg: Segment, _audio_path: str | Path | None, audio_array=None) -> np.ndarray:
        seen.append(seg.start)
        return np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32)

    module._extract_segment_embedding = fake_extract  # type: ignore[method-assign]

    result = module.split_by_voiceprint(
        [Segment(start=6.0, end=9.0), Segment(start=0.0, end=3.0), Segment(start=3.0, end=6.0)],
        tmp_path / "audio.wav",
        voiceprint=voiceprint,
        window_sec=3.0,
        hop_sec=1.5,
        audio_array=_FAKE_AUDIO,
    )
    assert seen == sorted(seen)
    starts = [seg.start for seg in result]
    assert starts == sorted(starts)
