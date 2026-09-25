"""音频分离导出.

根据说话人分离结果, 把原始音频切分为"用户语音"和"其他音频"两个文件.
"""

from __future__ import annotations

from pathlib import Path

import librosa
import numpy as np
import soundfile as sf

from .types import Segment


def separate_audio(
    audio_path: str | Path,
    segments: list[Segment],
    output_dir: str | Path,
    sample_rate: int = 16000,
) -> dict[str, Path]:
    """按 is_user 把音频分离为用户/其他两段并导出 WAV.

    Parameters
    ----------
    audio_path: 原始音频路径
    segments: 说话人分离后的片段, 要求每个 Segment 的 is_user 已标记
    output_dir: 输出目录
    sample_rate: 输出采样率

    Returns
    -------
    {"user": user_wav_path, "other": other_wav_path}
    """
    audio_path = Path(audio_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    y, sr = librosa.load(str(audio_path), sr=sample_rate, mono=True)
    total_samples = len(y)

    user_mask = np.zeros(total_samples, dtype=bool)
    for seg in segments:
        if getattr(seg, "is_user", False):
            start_sample = max(0, min(int(seg.start * sample_rate), total_samples))
            end_sample = max(0, min(int(seg.end * sample_rate), total_samples))
            if end_sample > start_sample:
                user_mask[start_sample:end_sample] = True

    user_audio = np.zeros_like(y)
    other_audio = np.zeros_like(y)
    user_audio[user_mask] = y[user_mask]
    other_audio[~user_mask] = y[~user_mask]

    user_path = output_dir / "user.wav"
    other_path = output_dir / "other.wav"
    sf.write(str(user_path), user_audio, sample_rate)
    sf.write(str(other_path), other_audio, sample_rate)

    return {"user": user_path, "other": other_path}


def merge_user_segments(
    audio_path: str | Path,
    segments: list[Segment],
    output_path: str | Path,
    sample_rate: int = 16000,
    gap_sec: float = 0.0,
) -> Path:
    """把所有用户片段拼接成一个连续音频文件.

    常用于把不连续的用户语音合并后送给 ISE 评测.
    """
    audio_path = Path(audio_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    y, sr = librosa.load(str(audio_path), sr=sample_rate, mono=True)
    user_segments = [s for s in segments if getattr(s, "is_user", False)]
    if not user_segments:
        sf.write(str(output_path), np.zeros(0, dtype=y.dtype), sample_rate)
        return output_path

    sorted_segs = sorted(user_segments, key=lambda s: s.start)
    gap_samples = int(gap_sec * sample_rate)
    chunks: list[np.ndarray] = []
    for seg in sorted_segs:
        start = max(0, int(seg.start * sample_rate))
        end = max(0, int(seg.end * sample_rate))
        end = min(end, len(y))
        if end <= start:
            continue
        chunks.append(y[start:end])
        if gap_samples > 0:
            chunks.append(np.zeros(gap_samples, dtype=y.dtype))

    if chunks and gap_samples > 0:
        chunks.pop()  # 去掉最后一个尾隙

    merged = np.concatenate(chunks) if chunks else np.zeros(0, dtype=y.dtype)
    sf.write(str(output_path), merged, sample_rate)
    return output_path
