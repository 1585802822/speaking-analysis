"""统一录音 ID 生成.

基于音频文件的解析绝对路径生成稳定的录音 ID，
保证不同目录下的同名文件（如两个 ``test.WAV``）不会互相覆盖数据库记录和片段目录。
"""

from __future__ import annotations

import hashlib
from pathlib import Path


def recording_id_from_path(audio_path: str | Path) -> str:
    """根据音频文件解析路径生成稳定录音 ID，避免同名文件冲突."""
    return hashlib.md5(str(Path(audio_path).resolve()).encode()).hexdigest()[:12]
