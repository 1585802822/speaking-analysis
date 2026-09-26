"""讯飞录音文件转写大模型版（Ifasr_llm）客户端测试."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.iflytek_asr_client import build_llm_asr_client, iFlytekLlmASRClient


def _client() -> iFlytekLlmASRClient:
    return iFlytekLlmASRClient(app_id="app123", api_key="key456", api_secret="secret789")


def test_configured_requires_app_id_api_key_and_secret():
    assert _client().configured
    assert not iFlytekLlmASRClient("", "k", "s").configured
    assert not iFlytekLlmASRClient("a", "", "s").configured
    assert not iFlytekLlmASRClient("a", "k", "").configured


def test_build_base_string_matches_doc_example():
    """与讯飞文档鉴权示例的 baseString 一致（含 URL 编码与排序）."""
    params = {
        "accessKeyId": "testaccesskeyid",
        "dateTime": "2018-04-13T20:22:53+0800",
        "duration": "56352",
        "fileName": "1分钟音频.mp3",
        "fileSize": "397144",
        "language": "en",
        "signatureRandom": "a0289d60-26b3-4601-ad18-d2179dc95fd2",
    }
    expected = (
        "accessKeyId=testaccesskeyid"
        "&dateTime=2018-04-13T20%3A22%3A53%2B0800"
        "&duration=56352"
        "&fileName=1%E5%88%86%E9%92%9F%E9%9F%B3%E9%A2%91.mp3"
        "&fileSize=397144"
        "&language=en"
        "&signatureRandom=a0289d60-26b3-4601-ad18-d2179dc95fd2"
    )
    assert iFlytekLlmASRClient._build_base_string(params) == expected


def test_build_base_string_skips_empty_values():
    params = {"b": "2", "a": "", "c": None, "d": "4"}
    assert iFlytekLlmASRClient._build_base_string(params) == "b=2&d=4"


def test_make_signature_is_hmac_sha1_base64():
    client = _client()
    params = {"accessKeyId": "key456", "orderId": "ORDER123"}
    base_string = iFlytekLlmASRClient._build_base_string(params)
    expected = base64.b64encode(
        hmac.new(b"secret789", base_string.encode("utf-8"), hashlib.sha1).digest()
    ).decode("utf-8")
    assert client._make_signature(params) == expected


def test_local_datetime_format():
    dt = iFlytekLlmASRClient._local_datetime()
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{4}", dt)


def test_random_signature_length_and_alphabet():
    sig = iFlytekLlmASRClient._random_signature()
    assert len(sig) == 16
    assert all(c.isalnum() for c in sig)


def test_parse_response_raises_on_error_code():
    client = _client()
    with pytest.raises(RuntimeError, match="参数错误"):
        client._parse_response({"code": 100003, "descInfo": "参数错误"})


def test_transcribe_upload_poll_parse(tmp_path: Path):
    audio = tmp_path / "user_all.wav"
    audio.write_bytes(b"fake wav bytes")
    client = _client()

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
                                        {"wb": 0, "we": 50, "cw": [{"w": "你", "wp": "n"}]},
                                        {"wb": 50, "we": 100, "cw": [{"w": "好", "wp": "n"}]},
                                        {"wb": 100, "we": 100, "cw": [{"w": "。", "wp": "p"}]},
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
        "code": "000000",
        "descInfo": "success",
        "content": {"orderId": "ORDER123"},
    }
    result_resp = MagicMock()
    result_resp.raise_for_status = MagicMock()
    result_resp.json.return_value = {
        "code": "000000",
        "descInfo": "success",
        "content": {
            "orderResult": json.dumps(order_result),
            "orderInfo": {"status": 4, "failType": 0},
        },
    }

    def fake_post(url, **kwargs):
        if "upload" in url:
            return upload_resp
        return result_resp

    with patch.object(client, "_random_signature", return_value="AbCdEfGhIjKlMnOp"):
        with patch.object(client, "_local_datetime", return_value="2026-09-26T11:00:00+0800"):
            with patch("requests.post", side_effect=fake_post) as post:
                result = client.transcribe(audio)

    # 两次请求：先 upload，后 getResult
    assert post.call_count == 2
    assert "upload" in post.call_args_list[0].args[0]
    assert "getResult" in post.call_args_list[1].args[0]

    # 上传请求头带 signature + octet-stream
    upload_kwargs = post.call_args_list[0].kwargs
    assert upload_kwargs["headers"]["Content-Type"] == "application/octet-stream"
    assert upload_kwargs["headers"]["signature"]

    # 解析结果：标点跳过，词级时间戳正确
    assert len(result) == 1
    assert result[0].text == "你好。"
    assert result[0].start == 0.0
    assert result[0].end == 1.5
    assert [w.text for w in result[0].words] == ["你", "好"]
    assert result[0].words[0].end == 0.5
    assert result[0].words[1].end == 1.0


def test_transcribe_upload_and_get_result_share_signature_random(tmp_path: Path):
    """上传与查询必须使用同一个 signatureRandom（接口要求）."""
    audio = tmp_path / "a.wav"
    audio.write_bytes(b"x")
    client = _client()

    upload_resp = MagicMock()
    upload_resp.raise_for_status = MagicMock()
    upload_resp.json.return_value = {"code": "000000", "content": {"orderId": "ORDER123"}}
    result_resp = MagicMock()
    result_resp.raise_for_status = MagicMock()
    result_resp.json.return_value = {
        "code": "000000",
        "content": {"orderResult": "", "orderInfo": {"status": 4, "failType": 0}},
    }

    def fake_post(url, **kwargs):
        return upload_resp if "upload" in url else result_resp

    with patch("requests.post", side_effect=fake_post) as post:
        client.transcribe(audio)

    from urllib.parse import parse_qs, urlparse

    upload_qs = parse_qs(urlparse(post.call_args_list[0].args[0]).query)
    result_qs = parse_qs(urlparse(post.call_args_list[1].args[0]).query)
    assert upload_qs["signatureRandom"] == result_qs["signatureRandom"]


def test_build_llm_asr_client_env_fallback(monkeypatch):
    monkeypatch.setenv("IFLYTEK_APP_ID", "env_app")
    monkeypatch.setenv("IFLYTEK_API_KEY", "env_key")
    monkeypatch.setenv("IFLYTEK_API_SECRET", "env_secret")
    config = {
        "api": {
            "enabled": True,
            "timeout": 30,
            "iflytek": {
                "app_id": "",
                "app_id_env": "IFLYTEK_APP_ID",
                "api_key": "",
                "api_key_env": "IFLYTEK_API_KEY",
                "api_secret": "",
                "api_secret_env": "IFLYTEK_API_SECRET",
                "language": "autodialect",
            },
        }
    }
    client = build_llm_asr_client(config)
    assert client is not None
    assert client.app_id == "env_app"
    assert client.api_key == "env_key"
    assert client.api_secret == "env_secret"
    assert client.language == "autodialect"
