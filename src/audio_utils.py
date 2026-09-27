"""音频工具函数.

统一复用 ``audio_adapter`` 的加载/裁剪/转码能力，
保证项目内所有音频导出都符合 API 要求的格式（16kHz 单声道 WAV）。
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from .audio_adapter import crop_for_api, load_mono


def load_segment(audio_path: str, start_sec: float, end_sec: float, sample_rate: int) -> np.ndarray:
    """加载音频的指定片段，返回单声道波形."""
    duration = max(0.0, end_sec - start_sec)
    return load_mono(audio_path, sample_rate, offset_sec=start_sec, duration_sec=duration)


def crop_audio_to_temp(audio_path: str, start_sec: float, end_sec: float, sample_rate: int) -> str:
    """将音频片段导出为临时 WAV 文件，返回路径."""
    out = crop_for_api(audio_path, start_sec, end_sec, target_sr=sample_rate)
    if out is None:
        raise ValueError(f"裁剪音频失败 {audio_path} [{start_sec}-{end_sec}]")
    return str(out)


def export_segment(
    audio_path: str,
    start_sec: float,
    end_sec: float,
    output_path: str,
    sample_rate: int = 16000,
) -> Path:
    """将音频片段持久化导出为 WAV 文件.

    与 ``crop_audio_to_temp`` 不同，本函数将片段写入指定路径，
    用于把句子级片段长期保存到 ``data/segments/{recording_id}/``。
    """
    out = crop_for_api(
        audio_path,
        start_sec,
        end_sec,
        output_path=output_path,
        target_sr=sample_rate,
    )
    if out is None:
        raise ValueError(f"导出音频片段失败 {audio_path} [{start_sec}-{end_sec}]")
    return out
