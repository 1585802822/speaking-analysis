"""声纹提取测试."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from src.embeddings import extract_embedding
from src.enrollment import EnrollmentManager


def test_extract_embedding_from_wav() -> None:
    """从 wav 声纹文件提取嵌入，应返回非零归一化向量."""
    voiceprint_wav = Path("data/voiceprint/声纹.wav")
    if not voiceprint_wav.exists():
        pytest.skip("data/voiceprint/声纹.wav 不存在")

    emb = extract_embedding(voiceprint_wav)
    assert isinstance(emb, np.ndarray)
    assert emb.dtype == np.float32
    assert emb.ndim == 1
    assert emb.shape[0] > 0
    assert np.linalg.norm(emb) > 0.99  # 归一化后长度约 1


def test_extract_embedding_missing_file() -> None:
    """缺失文件时应抛出 FileNotFoundError."""
    with pytest.raises(FileNotFoundError):
        extract_embedding(Path("data/voiceprint/nonexistent.wav"))


def test_enrollment_manager_enroll(tmp_path: Path) -> None:
    """EnrollmentManager 能提取并保存声纹."""
    voiceprint_wav = Path("data/voiceprint/声纹.wav")
    if not voiceprint_wav.exists():
        pytest.skip("data/voiceprint/声纹.wav 不存在")

    config = {
        "voiceprint_dir": str(tmp_path),
        "speaker": {"embedding_model": "speechbrain/spkrec-ecapa-voxceleb"},
    }
    manager = EnrollmentManager(config)
    manager.enroll(str(voiceprint_wav))

    assert (tmp_path / "embedding.pkl").exists()
    assert (tmp_path / "meta.json").exists()

    voiceprint = manager.load_voiceprint()
    assert voiceprint is not None
    assert "embedding" in voiceprint
    emb = voiceprint["embedding"]
    assert isinstance(emb, np.ndarray)
    assert emb.ndim == 1
    assert np.linalg.norm(emb) > 0.99

    meta_text = (tmp_path / "meta.json").read_text(encoding="utf-8")
    assert '"enrolled": true' in meta_text


def test_enrollment_manager_enroll_m4a(tmp_path: Path) -> None:
    """EnrollmentManager 支持 m4a 格式声纹文件."""
    voiceprint_m4a = Path("data/voiceprint/声纹.m4a")
    if not voiceprint_m4a.exists():
        pytest.skip("data/voiceprint/声纹.m4a 不存在")

    config = {
        "voiceprint_dir": str(tmp_path),
        "speaker": {"embedding_model": "speechbrain/spkrec-ecapa-voxceleb"},
    }
    manager = EnrollmentManager(config)
    manager.enroll(str(voiceprint_m4a))

    assert (tmp_path / "embedding.pkl").exists()
    voiceprint = manager.load_voiceprint()
    assert voiceprint is not None
    assert np.linalg.norm(voiceprint["embedding"]) > 0.99
