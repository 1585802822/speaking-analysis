"""讯飞 ISE 语音评测客户端测试."""

import hashlib
from unittest.mock import MagicMock, patch

from src.iflytek_evaluation_client import (
    build_evaluation_client,
    iFlytekEvaluationClient,
)


def _client(app_id: str = "app123", api_key: str = "key456") -> iFlytekEvaluationClient:
    return iFlytekEvaluationClient(app_id=app_id, api_key=api_key)


def test_configured_requires_app_id_and_api_key():
    assert _client().configured
    assert not _client(app_id="").configured
    assert not _client(api_key="").configured


def test_normalize_language():
    assert _client()._normalize_language("cn") == "zh_cn"
    assert _client()._normalize_language("zh") == "zh_cn"
    assert _client()._normalize_language("en") == "en_us"
    assert _client()._normalize_language("en_us") == "en_us"


def test_collect_scores_extracts_nested_scores():
    payload = {
        "code": "0",
        "data": {
            "read_sentence": {
                "rec_paper": {
                    "read_sentence": {
                        "total_score": 85.5,
                        "phone_score": 82.0,
                        "tone_score": 88.0,
                        "fluency_score": 79.5,
                        "integrity_score": 90.0,
                    }
                }
            }
        },
    }
    scores = _client()._collect_scores(payload["data"])
    assert scores["total_score"] == 85.5
    assert scores["phone_score"] == 82.0
    assert scores["fluency_score"] == 79.5
    assert scores["integrity_score"] == 90.0


def test_normalize_result_maps_scores():
    payload = {
        "code": "0",
        "data": {
            "read_sentence": {
                "rec_paper": {
                    "read_sentence": {
                        "total_score": 85.5,
                        "phone_score": 82.0,
                        "fluency_score": 79.5,
                        "integrity_score": 90.0,
                    }
                }
            }
        },
    }
    result = _client()._normalize_result(payload)
    assert result["overall_score"] == 85.5
    assert result["accuracy_score"] == 82.0  # 中文用 phone_score 映射准确度
    assert result["fluency_score"] == 79.5
    assert result["integrity_score"] == 90.0


def test_normalize_result_raises_on_error_code():
    with __import__("pytest").raises(RuntimeError, match="ISE"):
        _client()._normalize_result({"code": "10105", "desc": "illegal access"})


def test_evaluate_sends_correct_signature_and_parses():
    client = _client()
    fake_audio_b64 = "QUJD"  # "ABC" 的 base64
    response_payload = {
        "code": "0",
        "desc": "success",
        "data": {
            "read_sentence": {
                "rec_paper": {
                    "read_sentence": {
                        "total_score": 90.0,
                        "word_score": 88.0,
                        "fluency_score": 91.0,
                        "integrity_score": 95.0,
                    }
                }
            }
        },
    }

    with patch.object(client, "_read_audio_base64", return_value=fake_audio_b64):
        mock_resp = MagicMock()
        mock_resp.json.return_value = response_payload
        mock_resp.raise_for_status.return_value = None
        with patch("src.iflytek_evaluation_client.requests.post", return_value=mock_resp) as post:
            result = client.evaluate("dummy.wav", "hello world", language="en")

    # 校验鉴权请求头
    _, kwargs = post.call_args
    headers = kwargs["headers"]
    assert headers["X-Appid"] == "app123"
    base64_param = headers["X-Param"]
    cur_time = headers["X-CurTime"]
    expected_check = hashlib.md5(("key456" + cur_time + base64_param).encode("utf-8")).hexdigest()
    assert headers["X-CheckSum"] == expected_check

    # 校验请求体
    data = kwargs["data"]
    assert data["text"] == "hello world"
    assert data["audio"] == fake_audio_b64

    # 校验归一化结果（英文用 word_score 映射准确度）
    assert result["overall_score"] == 90.0
    assert result["accuracy_score"] == 88.0


def test_evaluate_requires_nonempty_text():
    with __import__("pytest").raises(ValueError, match="非空"):
        _client().evaluate("dummy.wav", "  ")


def test_build_evaluation_client_env_var_fallback(monkeypatch):
    monkeypatch.setenv("IFLYTEK_APP_ID", "env_app")
    monkeypatch.setenv("IFLYTEK_API_KEY", "env_key")
    config = {
        "api": {
            "enabled": True,
            "timeout": 30,
            "iflytek": {
                "evaluation": {
                    "app_id": "",
                    "app_id_env": "IFLYTEK_APP_ID",
                    "api_key": "",
                    "api_key_env": "IFLYTEK_API_KEY",
                    "category": "read_sentence",
                    "language": "cn",
                }
            },
        }
    }
    client = build_evaluation_client(config)
    assert client is not None
    assert client.app_id == "env_app"
    assert client.api_key == "env_key"
    assert client.category == "read_sentence"


def test_build_evaluation_client_none_when_disabled():
    assert build_evaluation_client({"api": {"enabled": False}}) is None
    assert build_evaluation_client({"api": {"enabled": True, "iflytek": {}}}) is None
