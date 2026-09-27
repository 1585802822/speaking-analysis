"""API 音频适配层.

统一把任意输入音频（mp3/wav/m4a/flac、任意采样率/声道/位深）
转换为讯飞各 API 要求的格式：

- 文件上传类（Ifasr_llm / 录音文件转写）：16kHz 单声道 WAV（PCM_16）
- 流式类（ISE 语音评测 / 流式听写）：16kHz 单声道 int16 PCM 字节流

解码优先使用 librosa；失败时用 ffmpeg 兜底（mp3/m4a 等格式）。
"""

from __future__ import annotations

import io
import logging
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import librosa
import numpy as np
import soundfile as sf

logger = logging.getLogger(__name__)

# 讯飞 Ifasr_llm / 录音文件转写的服务端限制（供校验用）
IFLYTEK_MAX_FILE_SIZE_MB = 500
IFLYTEK_MAX_DURATION_SEC = 5 * 3600


def load_mono(
    audio_path: str | Path,
    target_sr: int = 16000,
    offset_sec: float = 0.0,
    duration_sec: float | None = None,
) -> np.ndarray:
    """加载音频为单声道波形（已重采样到 target_sr），librosa 失败时 ffmpeg 兜底."""
    try:
        y, _sr = librosa.load(
            str(audio_path),
            sr=target_sr,
            mono=True,
            offset=offset_sec,
            duration=duration_sec,
        )
        return y
    except Exception as exc:
        logger.warning("librosa 加载失败 %s，尝试 ffmpeg 兜底: %s", audio_path, exc)
        return _load_with_ffmpeg(audio_path, target_sr, offset_sec, duration_sec)


def _load_with_ffmpeg(
    audio_path: str | Path,
    target_sr: int,
    offset_sec: float,
    duration_sec: float | None,
) -> np.ndarray:
    """ffmpeg 兜底解码：输出 16bit 单声道 WAV 到 stdout 再读回."""
    cmd = ["ffmpeg", "-y", "-ss", f"{offset_sec:.3f}"]
    if duration_sec is not None:
        cmd += ["-t", f"{duration_sec:.3f}"]
    cmd += [
        "-i",
        str(audio_path),
        "-ac",
        "1",
        "-ar",
        str(target_sr),
        "-f",
        "wav",
        "pipe:1",
    ]
    proc = subprocess.run(cmd, capture_output=True)
    if proc.returncode != 0:
        stderr = proc.stderr.decode(errors="ignore")[-300:]
        raise RuntimeError(f"ffmpeg 解码失败: {stderr}")
    y, _sr = sf.read(io.BytesIO(proc.stdout), dtype="float32", always_2d=False)
    return y


def prepare_for_api(
    audio_path: str | Path,
    output_path: str | Path | None = None,
    target_sr: int = 16000,
) -> Path:
    """把任意音频转成 16kHz 单声道 WAV（PCM_16），返回输出文件路径.

    未指定 output_path 时写到系统临时目录，由调用方负责清理。
    """
    y = load_mono(audio_path, target_sr)
    if output_path is None:
        fd, tmp_name = tempfile.mkstemp(suffix=".wav", prefix="sa_api_")
        os.close(fd)
        output_path = Path(tmp_name)
    else:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(output_path), y, target_sr, subtype="PCM_16")
    return output_path


def crop_for_api(
    audio_path: str | Path,
    start_sec: float,
    end_sec: float,
    output_path: str | Path | None = None,
    target_sr: int = 16000,
) -> Path | None:
    """裁剪音频区间并转成 API 要求的 16kHz 单声道 WAV.

    区间无效（时长 <= 0）或加载失败时返回 None。
    用于 ASR 逐句上传和 ISE 单句评测。
    """
    duration = end_sec - start_sec
    if duration <= 0:
        return None
    try:
        y = load_mono(audio_path, target_sr, offset_sec=start_sec, duration_sec=duration)
    except Exception as exc:
        logger.warning("裁剪音频失败 %s [%s-%s]: %s", audio_path, start_sec, end_sec, exc)
        return None
    if len(y) == 0:
        return None
    if output_path is None:
        fd, tmp_name = tempfile.mkstemp(suffix=".wav", prefix="sa_segment_")
        os.close(fd)
        output_path = Path(tmp_name)
    else:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(output_path), y, target_sr, subtype="PCM_16")
    return output_path


def to_pcm_bytes(audio_path: str | Path, target_sr: int = 16000) -> bytes:
    """输出 16kHz 单声道 int16 PCM 字节流，供 ISE / 流式听写使用."""
    y = load_mono(audio_path, target_sr)
    return np.clip(y, -1.0, 1.0).astype(np.int16).tobytes()


def validate_input(
    audio_path: str | Path,
    max_duration_sec: float | None = None,
    max_file_size_mb: float | None = None,
) -> dict[str, Any]:
    """校验输入音频，返回基本信息；不满足限制时抛 ValueError.

    文件过大 / 时长超限时给出清晰的错误信息，供 UI 直接展示。
    """
    path = Path(audio_path)
    if not path.exists():
        raise ValueError(f"音频文件不存在: {path}")
    if max_file_size_mb is not None:
        size_mb = path.stat().st_size / (1024 * 1024)
        if size_mb > max_file_size_mb:
            raise ValueError(
                f"文件过大: {size_mb:.1f}MB（上限 {max_file_size_mb}MB），请先压缩或裁剪音频"
            )
    try:
        duration_sec = float(librosa.get_duration(path=str(path)))
    except Exception as exc:
        raise ValueError(f"无法读取音频时长（文件可能损坏或格式不支持）: {exc}") from exc
    if max_duration_sec is not None and duration_sec > max_duration_sec:
        hours = duration_sec / 3600
        limit_hours = max_duration_sec / 3600
        raise ValueError(f"音频过长: {hours:.1f} 小时（上限 {limit_hours:.1f} 小时）")
    return {"duration_sec": duration_sec}
