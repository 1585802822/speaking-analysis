"""讯飞 ISE 语音评测客户端测试（流式版 WebSocket）."""

import base64
import hashlib
import hmac
import json
import re
from pathlib import Path
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlparse

import pytest

from src.iflytek_evaluation_client import (
    build_evaluation_client,
    iFlytekEvaluationClient,
    iFlytekVoiceInsightClient,
)


def _client(
    app_id: str = "app123", api_key: str = "key456", api_secret: str = "secret789"
) -> iFlytekEvaluationClient:
    return iFlytekEvaluationClient(app_id=app_id, api_key=api_key, api_secret=api_secret)


class _FakeWS:
    """模拟 WebSocket 连接, 记录发送帧并按序返回响应."""

    def __init__(self, responses: list[str]) -> None:
        self.sent: list[dict] = []
        self._responses = list(responses)

    def send(self, payload: str) -> None:
        self.sent.append(json.loads(payload))

    def recv(self) -> str:
        if self._responses:
            return self._responses.pop(0)
        return json.dumps({"code": 0, "data": {"status": 2, "result": {}}})

    def close(self) -> None:
        pass


def test_configured_requires_app_id_api_key_and_secret():
    assert _client().configured
    assert not _client(app_id="").configured
    assert not _client(api_key="").configured
    assert not _client(api_secret="").configured


def test_normalize_language():
    assert _client()._normalize_language("cn") == "zh_cn"
    assert _client()._normalize_language("zh") == "zh_cn"
    assert _client()._normalize_language("en") == "en_us"
    assert _client()._normalize_language("en_us") == "en_us"


def test_entity_for_language():
    assert _client()._entity_for("zh_cn") == "cn_vip"
    assert _client()._entity_for("en_us") == "en_vip"


def test_collect_scores_extracts_nested_scores():
    payload = {
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
        },
    }
    scores = _client()._collect_scores(payload)
    assert scores["total_score"] == 85.5
    assert scores["phone_score"] == 82.0
    assert scores["fluency_score"] == 79.5
    assert scores["integrity_score"] == 90.0


def test_extract_scores_from_xml():
    xml = (
        '<?xml version="1.0"?><FinalResult>'
        '<read_sentence total_score="97.5" phone_score="88.0" '
        'fluency_score="90.0" integrity_score="95.0"/>'
        "</FinalResult>"
    )
    scores = _client()._extract_scores_from_xml(xml)
    assert scores["total_score"] == 97.5
    assert scores["phone_score"] == 88.0
    assert scores["fluency_score"] == 90.0
    assert scores["integrity_score"] == 95.0


def test_extract_phones_from_xml():
    xml = (
        '<?xml version="1.0"?><xml_result>'
        '<read_sentence total_score="85.0" phone_score="82.0">'
        '<sentence beg_pos="0" end_pos="40" content="你好" time_len="40">'
        '<word beg_pos="0" end_pos="20" symbol="ni3" content="你" time_len="20">'
        '<syll dp_message="0" rec_node_type="paper">'
        '<phone perr_msg="0" mono_tone="TONE3" is_yun="0" rec_node_type="paper"/>'
        '<phone perr_msg="2" mono_tone="TONE3" is_yun="1" rec_node_type="paper"/>'
        "</syll>"
        "</word>"
        '<word beg_pos="20" end_pos="40" symbol="hao3" content="好" time_len="20">'
        '<syll dp_message="0" rec_node_type="paper">'
        '<phone perr_msg="0" mono_tone="TONE3" is_yun="1" rec_node_type="paper"/>'
        "</syll>"
        "</word>"
        "</sentence>"
        "</read_sentence></xml_result>"
    )
    phones = iFlytekEvaluationClient._extract_phones_from_xml(xml)
    assert len(phones) == 3

    ni_phones = [p for p in phones if p["word_text"] == "你"]
    assert len(ni_phones) == 2
    initial = next(p for p in ni_phones if p["is_yun"] == 0)
    assert initial["phone"] == "n"
    assert initial["is_correct"] is True
    final = next(p for p in ni_phones if p["is_yun"] == 1)
    assert final["phone"] == "i"
    assert final["is_correct"] is False
    assert final["error_type"] == "调型错"

    hao_phone = next(p for p in phones if p["word_text"] == "好")
    assert hao_phone["phone"] == "ao"
    assert hao_phone["is_yun"] == 1
    assert hao_phone["is_correct"] is True
    assert hao_phone["error_type"] == ""


def test_extract_phones_from_xml_ignores_silent_and_noise():
    xml = (
        '<?xml version="1.0"?><xml_result>'
        '<read_sentence total_score="85.0">'
        '<sentence content="你">'
        '<word beg_pos="0" end_pos="20" symbol="ni3" content="你">'
        '<syll dp_message="0" rec_node_type="sil" content="sil">'
        '<phone perr_msg="2" mono_tone="TONE3" is_yun="0" rec_node_type="sil" content="sil"/>'
        "</syll>"
        '<syll dp_message="0" rec_node_type="paper">'
        '<phone perr_msg="0" mono_tone="TONE3" is_yun="0" rec_node_type="paper"/>'
        "</syll>"
        "</word>"
        "</sentence>"
        "</read_sentence></xml_result>"
    )
    phones = iFlytekEvaluationClient._extract_phones_from_xml(xml)
    # sil 节点被过滤, 只保留 paper 节点
    assert len(phones) == 1
    assert phones[0]["is_correct"] is True
    assert phones[0]["rec_node_type"] == "paper"


def test_evaluate_chinese_parses_phone_details():
    client = _client()
    xml = (
        '<?xml version="1.0"?><xml_result>'
        '<read_sentence total_score="85.0" phone_score="82.0" '
        'fluency_score="88.0" integrity_score="90.0">'
        '<sentence content="你">'
        '<word beg_pos="10" end_pos="30" symbol="ni3" content="你">'
        '<syll dp_message="0" rec_node_type="paper">'
        '<phone perr_msg="0" mono_tone="TONE3" is_yun="0" rec_node_type="paper"/>'
        '<phone perr_msg="2" mono_tone="TONE3" is_yun="1" rec_node_type="paper"/>'
        "</syll>"
        "</word>"
        "</sentence>"
        "</read_sentence></xml_result>"
    )
    b64 = base64.b64encode(xml.encode("utf-8")).decode("ascii")
    fake = _FakeWS(
        [json.dumps({"code": 0, "message": "success", "data": {"status": 2, "data": b64}})]
    )
    with patch.object(client, "_read_pcm", return_value=b"\x00\x00" * 640):
        with patch("websocket.create_connection", return_value=fake):
            result = client.evaluate("dummy.wav", "你", language="cn")

    assert result["phone_details"] == [
        {
            "word_text": "你",
            "pinyin": "ni3",
            "tone": "三声",
            "phone": "n",
            "is_yun": 0,
            "is_correct": True,
            "error_type": "",
            "beg_pos": 10,
            "end_pos": 30,
            "rec_node_type": "paper",
        },
        {
            "word_text": "你",
            "pinyin": "ni3",
            "tone": "三声",
            "phone": "i",
            "is_yun": 1,
            "is_correct": False,
            "error_type": "调型错",
            "beg_pos": 10,
            "end_pos": 30,
            "rec_node_type": "paper",
        },
    ]


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
    with pytest.raises(RuntimeError, match="ISE"):
        _client()._normalize_result({"code": "10105", "desc": "illegal access"})


def test_build_url_uses_hmac_sha256_signature():
    client = _client()
    url = client._build_url()
    assert url.startswith("wss://ise-api.xfyun.cn/v2/open-ise")

    qs = parse_qs(urlparse(url).query)
    assert qs["host"][0] == "ise-api.xfyun.cn"
    date = qs["date"][0]

    auth_origin = base64.b64decode(qs["authorization"][0]).decode("utf-8")
    assert 'api_key="key456"' in auth_origin
    assert 'algorithm="hmac-sha256"' in auth_origin

    sig = re.search(r'signature="([^"]+)"', auth_origin).group(1)
    expected_origin = f"host: ise-api.xfyun.cn\ndate: {date}\nGET /v2/open-ise HTTP/1.1"
    expected_sig = base64.b64encode(
        hmac.new(b"secret789", expected_origin.encode("utf-8"), hashlib.sha256).digest()
    ).decode("utf-8")
    assert sig == expected_sig


def test_evaluate_streams_and_parses_nested_json():
    client = _client()
    fake = _FakeWS(
        [
            json.dumps({"code": 0, "message": "success", "data": {"status": 1, "result": {}}}),
            json.dumps(
                {
                    "code": 0,
                    "message": "success",
                    "data": {
                        "status": 2,
                        "result": {
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
                    },
                }
            ),
        ]
    )
    with patch.object(client, "_read_pcm", return_value=b"\x00\x00" * 640):
        with patch("websocket.create_connection", return_value=fake) as create_conn:
            result = client.evaluate("dummy.wav", "hello world", language="en")

    # 连接地址带鉴权参数
    url = create_conn.call_args[0][0]
    assert url.startswith("wss://ise-api.xfyun.cn/v2/open-ise")
    assert "authorization=" in url

    # 第一帧：ssb 参数与参考文本（文本需带 BOM 头）
    first = fake.sent[0]
    assert first["common"]["app_id"] == "app123"
    assert first["business"]["sub"] == "ise"
    assert first["business"]["ent"] == "en_vip"
    assert first["business"]["category"] == "read_sentence"
    assert first["business"]["text"].startswith("﻿")
    assert first["business"]["text"].endswith("hello world")

    # 有音频帧与结束帧
    assert any(f["business"]["cmd"] == "auw" for f in fake.sent)
    assert fake.sent[-1]["data"]["status"] == 2

    # 归一化结果（英文用 word_score 映射准确度）
    assert result["overall_score"] == 90.0
    assert result["accuracy_score"] == 88.0
    assert result["fluency_score"] == 91.0
    assert result["integrity_score"] == 95.0


def test_evaluate_chinese_uses_cn_vip_and_parses_base64_xml():
    client = _client()
    xml = (
        '<FinalResult><read_sentence total_score="85.0" phone_score="82.0" '
        'fluency_score="88.0" integrity_score="90.0"/></FinalResult>'
    )
    b64 = base64.b64encode(xml.encode("utf-8")).decode("ascii")
    fake = _FakeWS(
        [json.dumps({"code": 0, "message": "success", "data": {"status": 2, "data": b64}})]
    )
    with patch.object(client, "_read_pcm", return_value=b"\x00\x00" * 640):
        with patch("websocket.create_connection", return_value=fake):
            result = client.evaluate("dummy.wav", "你好世界", language="cn")

    assert fake.sent[0]["business"]["ent"] == "cn_vip"
    assert result["overall_score"] == 85.0
    assert result["accuracy_score"] == 82.0  # 中文用 phone_score 映射准确度
    assert result["fluency_score"] == 88.0
    assert result["integrity_score"] == 90.0


def test_evaluate_raises_on_websocket_error_code():
    client = _client()
    fake = _FakeWS([json.dumps({"code": 10163, "message": "数据过长"})])
    with patch.object(client, "_read_pcm", return_value=b"\x00\x00" * 640):
        with patch("websocket.create_connection", return_value=fake):
            with pytest.raises(RuntimeError, match="数据过长"):
                client.evaluate("dummy.wav", "你好世界")


def test_evaluate_requires_nonempty_text():
    with pytest.raises(ValueError, match="非空"):
        _client().evaluate("dummy.wav", "  ")


def test_build_evaluation_client_env_var_fallback(monkeypatch):
    monkeypatch.setenv("IFLYTEK_APP_ID", "env_app")
    monkeypatch.setenv("IFLYTEK_API_KEY", "env_key")
    monkeypatch.setenv("IFLYTEK_API_SECRET", "env_secret")
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
                    "api_secret": "",
                    "api_secret_env": "IFLYTEK_API_SECRET",
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
    assert client.api_secret == "env_secret"
    assert client.category == "read_sentence"


def test_build_evaluation_client_none_when_disabled():
    assert build_evaluation_client({"api": {"enabled": False}}) is None
    assert build_evaluation_client({"api": {"enabled": True, "iflytek": {}}}) is None


# ---- Spark VAA 语音分析客户端 ----


def _vaa_client() -> iFlytekVoiceInsightClient:
    return iFlytekVoiceInsightClient(api_key="key456", api_secret="secret789")


def test_voice_insight_build_url_uses_hmac_sha256():
    client = _vaa_client()
    url = client._build_url("POST", "/api/v1/voice-insight/create")
    assert url.startswith("http://spark-openapi.cn-huabei-1.xf-yun.com/api/v1/voice-insight/create")

    qs = parse_qs(urlparse(url).query)
    assert qs["host"][0] == "spark-openapi.cn-huabei-1.xf-yun.com"
    date = qs["date"][0]

    auth_origin = base64.b64decode(qs["authorization"][0]).decode("utf-8")
    assert 'api_key="key456"' in auth_origin
    assert 'algorithm="hmac-sha256"' in auth_origin

    sig = re.search(r'signature="([^"]+)"', auth_origin).group(1)
    expected_origin = (
        f"host: spark-openapi.cn-huabei-1.xf-yun.com\ndate: {date}\n"
        "POST /api/v1/voice-insight/create HTTP/1.1"
    )
    expected_sig = base64.b64encode(
        hmac.new(b"secret789", expected_origin.encode("utf-8"), hashlib.sha256).digest()
    ).decode("utf-8")
    assert sig == expected_sig


def test_voice_insight_create_task_sends_body_and_auth():
    client = _vaa_client()
    fake_resp = MagicMock()
    fake_resp.raise_for_status = MagicMock()
    fake_resp.json.return_value = {"code": 0, "data": {"task_id": "task-123"}}
    with patch("requests.post", return_value=fake_resp) as post:
        task_id = client._create_task("https://example.com/a.wav", "prompt-here")
    assert task_id == "task-123"

    url = post.call_args[0][0]
    assert "voice-insight/create" in url
    body = post.call_args[1]["json"]
    assert body["taskType"] == "audioFile"
    assert body["audioFileURL"] == "https://example.com/a.wav"
    assert body["modelCode"] == "xdeepseekv31"
    assert body["subTasks"][0]["is_customize"] is True
    assert body["subTasks"][0]["customize_prompt"] == "prompt-here"


def test_voice_insight_normalize_from_dict():
    client = _vaa_client()
    data = {
        "status": "Finish",
        "sub_task_results": [
            {"result": {"overall": 85, "accuracy": 82, "fluency": 80, "integrity": 90}}
        ],
    }
    result = client._normalize_result(data)
    assert result["overall_score"] == 85.0
    assert result["accuracy_score"] == 82.0
    assert result["fluency_score"] == 80.0
    assert result["integrity_score"] == 90.0


def test_voice_insight_normalize_from_markdown_string():
    client = _vaa_client()
    data = {
        "sub_task_results": [
            {
                "result": (
                    '```json\n{"overall": 90, "accuracy": 88, "fluency": 91, "integrity": 95}\n```'
                )
            }
        ]
    }
    result = client._normalize_result(data)
    assert result["overall_score"] == 90.0
    assert result["accuracy_score"] == 88.0
    assert result["fluency_score"] == 91.0
    assert result["integrity_score"] == 95.0


def test_voice_insight_parse_json_like():
    assert iFlytekVoiceInsightClient._parse_json_like('{"a": 1}') == {"a": 1}
    assert iFlytekVoiceInsightClient._parse_json_like('```json\n{"a": 1}\n```') == {"a": 1}
    assert iFlytekVoiceInsightClient._parse_json_like('结果如下：{"a": 1}，请参考') == {"a": 1}
    assert iFlytekVoiceInsightClient._parse_json_like("无 JSON 文本") is None


def test_voice_insight_resolve_audio_url():
    client = _vaa_client()
    # 已是 URL 时直接透传
    assert client._resolve_audio_url("https://example.com/a.wav") == "https://example.com/a.wav"
    # 本地路径未配置解析器时报错
    with pytest.raises(RuntimeError, match="audioFileURL"):
        client._resolve_audio_url(Path("local.wav"))
    # 配置解析器后走解析器
    client.audio_url_resolver = lambda p: f"http://x/{p.name}"
    assert client._resolve_audio_url(Path("local.wav")) == "http://x/local.wav"


def test_build_evaluation_client_voice_insight_mode():
    config = {
        "api": {
            "enabled": True,
            "timeout": 30,
            "iflytek": {
                "evaluation": {
                    "mode": "voice_insight",
                    "api_key": "key",
                    "api_secret": "secret",
                    "model_code": "x1",
                }
            },
        }
    }
    client = build_evaluation_client(config)
    assert isinstance(client, iFlytekVoiceInsightClient)
    assert client.model_code == "x1"
