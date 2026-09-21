"""ASR 转写模块单元测试."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.transcriber import Transcriber
from src.types import Segment, Utterance, Word


def _transcriber_with_fallback(config: dict) -> Transcriber:
    """构造一个强制使用占位回退的 Transcriber，避免依赖重型模型."""
    transcriber = Transcriber(config, auto_load_model=False)
    transcriber.model = None
    return transcriber


def test_empty_segments_returns_empty():
    transcriber = _transcriber_with_fallback({"asr": {}})
    assert transcriber.transcribe_user_segments(Path("dummy.wav"), []) == []


def test_config_defaults():
    transcriber = Transcriber({}, auto_load_model=False)
    assert transcriber.model_name == "large-v3"
    assert transcriber.device == "auto"
    assert transcriber.compute_type == "int8"
    assert transcriber.language == "zh"
    assert transcriber.beam_size == 5


def test_fallback_returns_one_utterance_per_merged_segment():
    transcriber = _transcriber_with_fallback({"asr": {"model": "tiny", "language": "zh"}})
    segments = [
        Segment(start=0.0, end=1.0),
        Segment(start=1.3, end=2.5),  # 与上一段间隔 0.3s，应合并
    ]
    result = transcriber.transcribe_user_segments(Path("dummy.wav"), segments)

    assert len(result) == 1
    utterance = result[0]
    assert isinstance(utterance, Utterance)
    assert utterance.start == pytest.approx(0.0)
    assert utterance.end == pytest.approx(2.5)
    assert len(utterance.words) == 1
    assert utterance.words[0].start == pytest.approx(0.0)
    assert utterance.words[0].end == pytest.approx(2.5)
    assert "占位" in utterance.text


def test_fallback_keeps_distant_segments_separate():
    transcriber = _transcriber_with_fallback({"asr": {"model": "tiny"}})
    segments = [
        Segment(start=0.0, end=1.0),
        Segment(start=2.0, end=3.0),  # 间隔 1.0s，不合并
    ]
    result = transcriber.transcribe_user_segments(Path("dummy.wav"), segments)

    assert len(result) == 2
    assert result[0].start == pytest.approx(0.0)
    assert result[0].end == pytest.approx(1.0)
    assert result[1].start == pytest.approx(2.0)
    assert result[1].end == pytest.approx(3.0)


def test_fallback_logs_warning(caplog):
    transcriber = _transcriber_with_fallback({"asr": {}})
    with caplog.at_level("WARNING"):
        transcriber.transcribe_user_segments(Path("dummy.wav"), [Segment(start=0.0, end=1.0)])
    assert "ASR 模型未加载" in caplog.text


def _api_config() -> dict:
    return {
        "asr": {"model": "tiny", "language": "zh"},
        "segmentation": {"target_sample_rate": 16000},
        "api": {
            "enabled": True,
            "base_url": "https://gateway.example.com",
            "api_key_env": "TEST_KEY",
            "timeout": 10,
            "endpoints": {"asr": "/asr"},
        },
    }


def test_api_success_uses_gateway_result():
    transcriber = Transcriber(_api_config())
    assert transcriber.api_client.asr_available
    transcriber.model = None  # 不加载本地模型

    fake_path = Path("/tmp/fake_cropped.wav")
    transcriber._crop_to_wav = lambda audio_path, segment: fake_path  # type: ignore[method-assign]

    transcriber.api_client.transcribe = MagicMock(  # type: ignore[method-assign]
        return_value=[
            Utterance(
                text="hello",
                start=0.0,
                end=1.0,
                words=[Word(text="hello", start=0.0, end=1.0, confidence=0.9)],
            )
        ]
    )

    segments = [Segment(start=5.0, end=6.0)]
    result = transcriber.transcribe_user_segments(Path("dummy.wav"), segments)

    assert len(result) == 1
    assert result[0].text == "hello"
    # 时间戳应被加上片段偏移
    assert result[0].start == pytest.approx(5.0)
    assert result[0].end == pytest.approx(6.0)
    transcriber.api_client.transcribe.assert_called_once()


def test_api_failure_falls_back_to_local():
    config = _api_config()
    transcriber = Transcriber(config)
    transcriber.model = None

    fake_path = Path("/tmp/fake_cropped.wav")
    transcriber._crop_to_wav = lambda audio_path, segment: fake_path  # type: ignore[method-assign]
    transcriber.api_client.transcribe = MagicMock(side_effect=RuntimeError("API down"))  # type: ignore[method-assign]

    segments = [Segment(start=0.0, end=1.0)]
    result = transcriber.transcribe_user_segments(Path("dummy.wav"), segments)

    assert len(result) == 1
    assert "占位" in result[0].text
