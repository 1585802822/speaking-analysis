"""声纹注册与管理测试."""

from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest

from src.enrollment import EnrollmentManager

EMBEDDING_DIM = 192


def _manager(tmp_path: Path) -> EnrollmentManager:
    config = {
        "voiceprint_dir": str(tmp_path / "voiceprint"),
        "speaker": {
            "positive_lr": 0.25,
            "negative_lr": 0.15,
        },
        "asr": {"device": "cpu"},
    }
    return EnrollmentManager(config)


def _dummy_embedding() -> np.ndarray:
    emb = np.random.default_rng(42).random(EMBEDDING_DIM).astype(np.float32)
    return emb / (np.linalg.norm(emb) + 1e-8)


def test_enroll_and_load(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    audio = tmp_path / "enroll.wav"
    audio.write_text("dummy")  # 提取后端会尝试读取，测试用 mock 绕过真实模型

    with patch.object(manager, "_extract_embedding", return_value=_dummy_embedding()):
        manager.enroll(str(audio))

    voiceprint = manager.load_voiceprint()
    assert voiceprint is not None
    assert voiceprint["embedding"].shape == (EMBEDDING_DIM,)
    assert voiceprint["samples"] == [str(audio)]

    meta = manager.meta_path.read_text(encoding="utf-8")
    assert "enrolled" in meta


def test_load_voiceprint_missing(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    assert manager.load_voiceprint() is None


def test_update_voiceprint_positive(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    audio = tmp_path / "enroll.wav"
    audio.write_text("dummy")

    initial = np.zeros(EMBEDDING_DIM, dtype=np.float32)
    initial[0] = 1.0
    with patch.object(manager, "_extract_embedding", return_value=initial.copy()):
        manager.enroll(str(audio))

    # 注入可控嵌入：正面样本偏向 y 轴
    positive = np.zeros(EMBEDDING_DIM, dtype=np.float32)
    positive[1] = 1.0

    manager._extract_embedding = lambda path: (  # type: ignore[method-assign]
        positive if "pos" in str(path) else initial
    )
    manager.update_voiceprint(positive_samples=[str(tmp_path / "pos1.wav")])

    voiceprint = manager.load_voiceprint()
    assert voiceprint is not None
    center = voiceprint["embedding"]
    # 中心应向 y 方向偏移且保持单位长度
    assert center[1] > 0.0
    assert np.isclose(np.linalg.norm(center), 1.0)
    assert str(tmp_path / "pos1.wav") in voiceprint["positive_samples"]


def test_update_voiceprint_negative(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    audio = tmp_path / "enroll.wav"
    audio.write_text("dummy")

    initial = np.zeros(EMBEDDING_DIM, dtype=np.float32)
    initial[0] = 1.0
    with patch.object(manager, "_extract_embedding", return_value=initial.copy()):
        manager.enroll(str(audio))

    manager._extract_embedding = lambda path: np.zeros(EMBEDDING_DIM, dtype=np.float32)  # type: ignore[method-assign]
    manager.update_voiceprint(
        positive_samples=[],
        negative_samples=[str(tmp_path / "neg1.wav")],
    )

    voiceprint = manager.load_voiceprint()
    assert voiceprint is not None
    center = voiceprint["embedding"]
    # 负面样本与中心相同，推动方向任意；主要验证更新后仍归一化且样本已记录
    assert np.isclose(np.linalg.norm(center), 1.0)
    assert str(tmp_path / "neg1.wav") in voiceprint["negative_samples"]


def test_update_without_voiceprint_raises(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    with pytest.raises(RuntimeError, match="未找到注册声纹"):
        manager.update_voiceprint(positive_samples=[str(tmp_path / "x.wav")])
