"""音频预处理模块测试."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from src.preprocessor import Preprocessor
from src.types import Segment


def _module(config: dict | None = None) -> Preprocessor:
    cfg = {
        "preprocessing": {
            "denoise": {"backend": "spectral"},
            "vad": {"backend": "energy"},
            "segmentation": {
                "target_sample_rate": 16000,
                "min_segment_duration_sec": 0.1,
                "max_segment_duration_sec": 5.0,
            },
        },
        "vad": {"min_speech_duration_ms": 100, "max_silence_duration_ms": 200},
    }
    if config:
        cfg.update(config)
    return Preprocessor(cfg)


def test_segment_has_new_metadata_fields() -> None:
    seg = Segment(start=0.0, end=1.0)
    assert seg.vad_confidence == 1.0
    assert seg.speaker_label is None
    assert seg.speaker_confidence is None
    assert seg.needs_review is False


def test_preprocessor_returns_segments(tmp_path: Path) -> None:
    module = _module()
    sr = 16000
    duration = 2.0
    y = np.random.randn(int(sr * duration)) * 0.01
    # 插入一段高能量语音
    y[int(0.5 * sr) : int(1.5 * sr)] += np.sin(2 * np.pi * 400 * np.arange(sr) / sr) * 0.5
    path = tmp_path / "test.wav"
    import soundfile as sf

    sf.write(path, y, sr)
    segments = module.process(path)
    assert isinstance(segments, list)
    for seg in segments:
        assert seg.end > seg.start
        assert seg.vad_confidence >= 0.0


def test_preprocessor_energy_vad_with_silence(tmp_path: Path) -> None:
    module = _module()
    sr = 16000
    y = np.zeros(int(sr * 1.5), dtype=np.float32)  # 全静音
    path = tmp_path / "silent.wav"
    import soundfile as sf

    sf.write(path, y, sr)
    segments = module.process(path)
    assert segments == []


def test_preprocessor_fallback_on_unknown_backend(tmp_path: Path) -> None:
    """未知降噪/VAD 后端应回退到默认实现而不崩溃."""
    module = _module(
        {
            "preprocessing": {
                "denoise": {"backend": "unknown"},
                "vad": {"backend": "unknown"},
            }
        }
    )
    sr = 16000
    y = np.sin(2 * np.pi * 400 * np.arange(int(sr * 1.0)) / sr) * 0.5
    path = tmp_path / "fallback.wav"
    import soundfile as sf

    sf.write(path, y, sr)
    segments = module.process(path)
    assert isinstance(segments, list)


def test_preprocessor_silero_backend_used_if_available(tmp_path: Path) -> None:
    """silero 后端在依赖可用时被调用，否则回退."""
    module = _module({"preprocessing": {"vad": {"backend": "silero", "threshold": 0.5}}})
    sr = 16000
    y = np.sin(2 * np.pi * 400 * np.arange(int(sr * 1.0)) / sr) * 0.5
    path = tmp_path / "silero.wav"
    import soundfile as sf

    sf.write(path, y, sr)
    # 仅验证不崩溃；silero 未安装时自动回退
    segments = module.process(path)
    assert isinstance(segments, list)


def test_preprocessor_noisereduce_backend_used_if_available(tmp_path: Path) -> None:
    """noisereduce 后端在依赖可用时被调用，否则回退."""
    module = _module({"preprocessing": {"denoise": {"backend": "noisereduce"}}})
    sr = 16000
    y = np.sin(2 * np.pi * 400 * np.arange(int(sr * 1.0)) / sr) * 0.5
    path = tmp_path / "nr.wav"
    import soundfile as sf

    sf.write(path, y, sr)
    segments = module.process(path)
    assert isinstance(segments, list)
