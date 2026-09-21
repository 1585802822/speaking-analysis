"""声纹嵌入提取测试."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np

from src.embeddings import extract_embedding


def test_api_embedding_success(tmp_path: Path):
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"fake wav bytes")

    config = {
        "api": {
            "enabled": True,
            "base_url": "https://gateway.example.com",
            "api_key_env": "TEST_KEY",
            "timeout": 10,
            "endpoints": {"embed": "/embed"},
        }
    }

    fake_resp = MagicMock()
    fake_resp.raise_for_status = MagicMock()
    fake_resp.json.return_value = {"embedding": [1.0, 0.0, 0.0]}

    with patch("src.embeddings.ModelAPIClient._ensure_wav", return_value=audio):
        with patch("requests.post", return_value=fake_resp):
            emb = extract_embedding(str(audio), config)

    assert isinstance(emb, np.ndarray)
    assert emb.dtype == np.float32
    assert np.isclose(np.linalg.norm(emb), 1.0)


def test_api_embedding_failure_falls_back_to_local(tmp_path: Path):
    audio = tmp_path / "audio.wav"
    # 写一段合法静音 WAV，让 MFCC 回退有数据
    import soundfile as sf

    y = np.zeros(16000, dtype=np.float32)
    sf.write(str(audio), y, 16000)

    config = {
        "api": {
            "enabled": True,
            "base_url": "https://gateway.example.com",
            "api_key_env": "TEST_KEY",
            "timeout": 10,
            "endpoints": {"embed": "/embed"},
        }
    }

    fake_resp = MagicMock()
    fake_resp.raise_for_status.side_effect = RuntimeError("API down")

    with patch("requests.post", return_value=fake_resp):
        emb = extract_embedding(str(audio), config)

    # MFCC 回退会返回非零向量（静音也有统计特征）
    assert isinstance(emb, np.ndarray)
    assert emb.shape == (192,)
