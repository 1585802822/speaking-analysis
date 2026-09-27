"""audio_adapter 音频适配层单元测试."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from src.audio_adapter import (
    crop_for_api,
    prepare_for_api,
    to_pcm_bytes,
    validate_input,
)


def _make_wav(path: Path, sr: int = 16000, duration: float = 1.0, channels: int = 1) -> None:
    """生成一段正弦波测试音频."""
    t = np.linspace(0, duration, int(sr * duration), endpoint=False)
    y = 0.3 * np.sin(2 * np.pi * 440 * t).astype(np.float32)
    if channels > 1:
        y = np.stack([y, y * 0.8], axis=1)
    sf.write(str(path), y, sr)


def test_prepare_for_api_resamples(tmp_path: Path) -> None:
    """96kHz 立体声输入转成 16kHz 单声道 WAV."""
    src = tmp_path / "input.wav"
    _make_wav(src, sr=96000, channels=2)

    out = prepare_for_api(src, output_path=tmp_path / "out.wav")
    info = sf.info(str(out))
    assert info.samplerate == 16000
    assert info.channels == 1
    assert info.subtype == "PCM_16"


def test_prepare_for_api_tmp_output(tmp_path: Path) -> None:
    """未指定输出路径时写到临时文件."""
    src = tmp_path / "input.wav"
    _make_wav(src)

    out = prepare_for_api(src)
    assert out.exists()
    assert out.suffix == ".wav"
    out.unlink()


def test_crop_for_api_crops_interval(tmp_path: Path) -> None:
    """裁剪区间时长正确."""
    src = tmp_path / "input.wav"
    _make_wav(src, duration=1.0)

    out = crop_for_api(src, 0.2, 0.5, output_path=tmp_path / "seg.wav")
    assert out is not None
    y, sr = sf.read(str(out))
    # 允许少量重采样/边界误差
    assert abs(len(y) / sr - 0.3) < 0.05


def test_crop_for_api_invalid_interval(tmp_path: Path) -> None:
    """无效区间返回 None."""
    src = tmp_path / "input.wav"
    _make_wav(src)
    assert crop_for_api(src, 0.5, 0.2) is None


def test_to_pcm_bytes(tmp_path: Path) -> None:
    """PCM 字节流为 16kHz 单声道 int16."""
    src = tmp_path / "input.wav"
    _make_wav(src, duration=1.0)

    data = to_pcm_bytes(src)
    assert len(data) == 16000 * 1 * 2
    samples = np.frombuffer(data, dtype=np.int16)
    assert samples.dtype == np.int16


def test_validate_input_ok(tmp_path: Path) -> None:
    """正常文件校验通过并返回时长."""
    src = tmp_path / "input.wav"
    _make_wav(src, duration=1.0)

    info = validate_input(src, max_duration_sec=10, max_file_size_mb=10)
    assert abs(info["duration_sec"] - 1.0) < 0.1


def test_validate_input_missing(tmp_path: Path) -> None:
    """不存在的文件报错."""
    with pytest.raises(ValueError, match="不存在"):
        validate_input(tmp_path / "nope.wav")


def test_validate_input_too_long(tmp_path: Path) -> None:
    """超长音频报错."""
    src = tmp_path / "input.wav"
    _make_wav(src, duration=2.0)

    with pytest.raises(ValueError, match="过长"):
        validate_input(src, max_duration_sec=1.0)


def test_validate_input_too_large(tmp_path: Path) -> None:
    """超大文件报错."""
    src = tmp_path / "input.wav"
    _make_wav(src, duration=1.0)

    with pytest.raises(ValueError, match="过大"):
        validate_input(src, max_file_size_mb=0.0001)
