"""Model API Gateway 客户端测试."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from src.model_api_client import ModelAPIClient
from src.types import Utterance, Word


def _config(enabled: bool = True, with_endpoints: bool = True) -> dict:
    endpoints = {"asr": "/asr", "embed": "/embed"} if with_endpoints else {}
    return {
        "api": {
            "enabled": enabled,
            "base_url": "https://gateway.example.com",
            "api_key_env": "TEST_API_KEY",
            "timeout": 10,
            "endpoints": endpoints,
        }
    }


def test_disabled_client_returns_none_availability():
    client = ModelAPIClient(_config(enabled=False))
    assert not client.asr_available
    assert not client.embed_available


def test_missing_base_url_disables_client():
    cfg = _config()
    cfg["api"]["base_url"] = ""
    client = ModelAPIClient(cfg)
    assert not client.asr_available
    assert not client.embed_available


def test_missing_endpoint_disables_single_capability():
    client = ModelAPIClient(_config(with_endpoints=False))
    assert not client.asr_available
    assert not client.embed_available


def test_load_key_from_env(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("TEST_API_KEY", "secret-key")
    client = ModelAPIClient(_config())
    assert client.api_key == "secret-key"


def test_transcribe_parses_response(tmp_path: Path):
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"fake wav bytes")
    client = ModelAPIClient(_config())

    fake_resp = MagicMock()
    fake_resp.raise_for_status = MagicMock()
    fake_resp.json.return_value = {
        "segments": [
            {
                "text": "hello world",
                "start": 0.0,
                "end": 1.0,
                "words": [
                    {"text": "hello", "start": 0.0, "end": 0.5, "confidence": 0.9},
                    {"text": "world", "start": 0.5, "end": 1.0, "confidence": 0.8},
                ],
            }
        ]
    }

    with patch("src.model_api_client.ModelAPIClient._ensure_wav", return_value=audio):
        with patch("requests.post", return_value=fake_resp):
            result = client.transcribe(str(audio))

    assert len(result) == 1
    assert isinstance(result[0], Utterance)
    assert result[0].text == "hello world"
    assert len(result[0].words) == 2
    assert result[0].words[0].text == "hello"


def test_embed_parses_response(tmp_path: Path):
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"fake wav bytes")
    client = ModelAPIClient(_config())

    fake_resp = MagicMock()
    fake_resp.raise_for_status = MagicMock()
    fake_resp.json.return_value = {"embedding": [0.1, 0.2, 0.3]}

    with patch("src.model_api_client.ModelAPIClient._ensure_wav", return_value=audio):
        with patch("requests.post", return_value=fake_resp):
            result = client.embed(str(audio))

    assert isinstance(result, np.ndarray)
    assert result.dtype == np.float32
    assert np.allclose(result, np.array([0.1, 0.2, 0.3], dtype=np.float32))


def test_api_error_raises_exception(tmp_path: Path):
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"fake wav bytes")
    client = ModelAPIClient(_config())

    fake_resp = MagicMock()
    fake_resp.raise_for_status.side_effect = RuntimeError("API down")

    with patch("src.model_api_client.ModelAPIClient._ensure_wav", return_value=audio):
        with patch("requests.post", return_value=fake_resp):
            with pytest.raises(RuntimeError, match="API down"):
                client.transcribe(str(audio))


def _iflytek_config(app_id: str = "test_app", api_secret: str = "test_secret") -> dict:
    return {
        "api": {
            "enabled": True,
            "provider": "iflytek",
            "timeout": 10,
            "iflytek": {
                "app_id": app_id,
                "api_secret": api_secret,
                "language": "cn",
            },
            "base_url": "",
            "endpoints": {},
        }
    }


def test_iflytek_credentials_read_from_env(monkeypatch):
    """配置值为空时, 讯飞密钥应从环境变量读取."""
    monkeypatch.setenv("IFLYTEK_APP_ID", "env_app")
    monkeypatch.setenv("IFLYTEK_API_SECRET", "env_secret")
    config = _iflytek_config(app_id="", api_secret="")
    config["api"]["iflytek"]["app_id_env"] = "IFLYTEK_APP_ID"
    config["api"]["iflytek"]["api_secret_env"] = "IFLYTEK_API_SECRET"

    client = ModelAPIClient(config)
    assert client.asr_available
    assert client.iflytek_client.app_id == "env_app"
    assert client.iflytek_client.api_secret == "env_secret"


def test_iflytek_missing_credentials_not_available():
    client = ModelAPIClient(_iflytek_config(app_id="", api_secret=""))
    assert not client.asr_available
    assert not client.embed_available


def test_iflytek_transcribe_upload_and_poll(tmp_path: Path):
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"fake wav bytes")
    client = ModelAPIClient(_iflytek_config())

    assert client.asr_available
    assert not client.embed_available

    order_result = {
        "lattice": [
            {
                "json_1best": json.dumps(
                    {
                        "st": {
                            "bg": "0",
                            "ed": "1500",
                            "rt": [
                                {
                                    "ws": [
                                        {
                                            "wb": 0,
                                            "we": 5,
                                            "cw": [{"w": "你", "wp": "n"}],
                                        },
                                        {
                                            "wb": 5,
                                            "we": 10,
                                            "cw": [{"w": "好", "wp": "n"}],
                                        },
                                        {
                                            "wb": 10,
                                            "we": 15,
                                            "cw": [{"w": "，", "wp": "p"}],
                                        },
                                        {
                                            "wb": 15,
                                            "we": 25,
                                            "cw": [{"w": "世", "wp": "n"}],
                                        },
                                        {
                                            "wb": 25,
                                            "we": 35,
                                            "cw": [{"w": "界", "wp": "n"}],
                                        },
                                    ]
                                }
                            ],
                        }
                    }
                )
            }
        ]
    }

    upload_resp = MagicMock()
    upload_resp.raise_for_status = MagicMock()
    upload_resp.json.return_value = {
        "ok": 0,
        "data": json.dumps({"orderId": "ORDER123"}),
    }
    result_resp = MagicMock()
    result_resp.raise_for_status = MagicMock()
    result_resp.json.return_value = {
        "ok": 0,
        "data": json.dumps({"orderResult": json.dumps(order_result), "status": 4}),
    }

    def fake_post(url: str, **kwargs):
        if "upload" in url:
            return upload_resp
        return result_resp

    with patch("requests.post", side_effect=fake_post):
        result = client.transcribe(str(audio))

    assert len(result) == 1
    utterance = result[0]
    assert isinstance(utterance, Utterance)
    assert utterance.text == "你好，世界"
    assert utterance.start == 0.0
    assert utterance.end == 1.5

    # 标点被跳过, 非标点保留为 Word
    assert len(utterance.words) == 4
    assert all(isinstance(w, Word) for w in utterance.words)
    assert utterance.words[0].text == "你"
    assert utterance.words[0].start == 0.0
    assert utterance.words[0].end == 0.05
    assert utterance.words[1].text == "好"
    assert utterance.words[2].text == "世"
    assert utterance.words[3].text == "界"
    assert utterance.words[3].start == 0.25
    assert utterance.words[3].end == 0.35


def _iflytek_stream_config(
    app_id: str = "test_app",
    api_key: str = "test_key",
    api_secret: str = "test_secret",
) -> dict:
    cfg = _iflytek_config(app_id=app_id, api_secret=api_secret)
    cfg["api"]["iflytek"]["mode"] = "stream"
    cfg["api"]["iflytek"]["api_key"] = api_key
    cfg["api"]["iflytek"]["language"] = "zh_cn"
    return cfg


def _stream_result_msg(sn: int, pgs: str | None = None, rg: list | None = None) -> str:
    result = {
        "sn": sn,
        "ls": True,
        "bg": 0,
        "ed": 0,
        "ws": [
            {"bg": 10, "ed": 50, "cw": [{"w": "你", "wp": "n"}, {"w": "好", "wp": "n"}]},
            {"bg": 0, "ed": 0, "cw": [{"w": "，", "wp": "p"}]},
        ],
    }
    if pgs:
        result["pgs"] = pgs
    if rg:
        result["rg"] = rg
    return json.dumps({"code": 0, "message": "success", "data": {"status": 0, "result": result}})


_STREAM_END_MSG = json.dumps({"code": 0, "message": "success", "data": {"status": 2}})


def test_iflytek_stream_missing_credentials_not_available():
    client = ModelAPIClient(_iflytek_stream_config(api_key=""))
    assert not client.asr_available


def test_iflytek_stream_transcribe_chunks_and_shifts_timestamps(tmp_path: Path):
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"fake wav bytes")
    client = ModelAPIClient(_iflytek_stream_config())
    assert client.asr_available

    # 120 秒音频 -> 55 + 55 + 10 共 3 块, 每块一次 WebSocket 会话
    fake_samples = np.zeros(120 * 16000, dtype=np.float32)

    connections = []
    for _ in range(3):
        ws = MagicMock()
        ws.recv.side_effect = [_stream_result_msg(1), _STREAM_END_MSG]
        connections.append(ws)

    with patch("librosa.load", return_value=(fake_samples, 16000)):
        with patch("websocket.create_connection", side_effect=connections) as create:
            client.iflytek_client.frame_interval = 0
            result = client.transcribe(str(audio))

    assert create.call_count == 3
    assert len(result) == 3

    # 每块产出 1 句, 标点计入 text 但跳过 words
    expected_offsets = [0.0, 55.0, 110.0]
    for utterance, offset in zip(result, expected_offsets):
        assert isinstance(utterance, Utterance)
        assert utterance.text == "你好，"
        assert utterance.start == pytest.approx(offset + 0.1)
        assert utterance.end == pytest.approx(offset + 0.5)
        assert len(utterance.words) == 2
        assert utterance.words[0].text == "你"
        assert utterance.words[0].start == pytest.approx(offset + 0.1)
        assert utterance.words[0].end == pytest.approx(offset + 0.5)

    # 校验发送帧格式: 首帧带 common/business 且 status=0, 末帧 status=2
    first_send = json.loads(connections[0].send.call_args_list[0].args[0])
    assert first_send["common"] == {"app_id": "test_app"}
    assert first_send["business"]["language"] == "zh_cn"
    assert first_send["data"]["status"] == 0
    assert first_send["data"]["encoding"] == "raw"
    last_send = json.loads(connections[0].send.call_args_list[-1].args[0])
    assert last_send["data"]["status"] == 2


def test_iflytek_stream_wpgs_replace(tmp_path: Path):
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"fake wav bytes")
    client = ModelAPIClient(_iflytek_stream_config())

    fake_samples = np.zeros(10 * 16000, dtype=np.float32)

    ws = MagicMock()
    ws.recv.side_effect = [
        _stream_result_msg(1, pgs="apd"),
        # sn=2 替换 sn=1 的结果
        _stream_result_msg(2, pgs="rpl", rg=[1, 1]),
        _STREAM_END_MSG,
    ]

    with patch("librosa.load", return_value=(fake_samples, 16000)):
        with patch("websocket.create_connection", return_value=ws):
            client.iflytek_client.frame_interval = 0
            result = client.transcribe(str(audio))

    # sn=1 被 sn=2 替换, 只保留一句
    assert len(result) == 1
    assert result[0].text == "你好，"
    assert result[0].start == pytest.approx(0.1)
