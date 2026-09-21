"""音频工具函数."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import librosa
import numpy as np
import soundfile as sf


def load_segment(
    audio_path: str, start_sec: float, end_sec: float, sample_rate: int
) -> np.ndarray:
    """加载音频的指定片段，返回单声道波形."""
    duration = max(0.0, end_sec - start_sec)
    y, sr = librosa.load(
        audio_path,
        sr=sample_rate,
        mono=True,
        offset=start_sec,
        duration=duration,
    )
    return y


def crop_audio_to_temp(
    audio_path: str, start_sec: float, end_sec: float, sample_rate: int
) -> str:
    """将音频片段导出为临时 WAV 文件，返回路径."""
    y = load_segment(audio_path, start_sec, end_sec, sample_rate)
    fd, path = tempfile.mkstemp(suffix=".wav", prefix="sa_segment_")
    try:
        sf.write(path, y, sample_rate)
    except Exception:
        Path(path).unlink(missing_ok=True)
        raise
    finally:
        os.close(fd)
    return path
