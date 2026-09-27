"""ASR 按说话人路由测试."""

from __future__ import annotations

from unittest.mock import MagicMock

import numpy as np
import pytest
import soundfile as sf

from src.transcriber import Transcriber
from src.types import Segment, Utterance, Word


def _create_wav(path, duration_sec=2.0, sr=16000):
    y = np.random.normal(0, 0.01, int(duration_sec * sr)).astype(np.float32)
    sf.write(str(path), y, sr)


@pytest.fixture
def tmp_wav(tmp_path):
    wav = tmp_path / "audio.wav"
    _create_wav(wav)
    return wav


@pytest.fixture
def config(tmp_path):
    return {
        "input_dir": str(tmp_path / "input"),
        "output_dir": str(tmp_path / "output"),
        "voiceprint_dir": str(tmp_path / "voiceprint"),
        "asr": {
            "model": "tiny",
            "device": "cpu",
            "compute_type": "int8",
            "language": "zh",
            "beam_size": 5,
            "vad_filter": True,
        },
        "segmentation": {"target_sample_rate": 16000, "parallel_workers": 1},
        "api": {"enabled": False},
    }


def test_user_segments_use_api_asr(tmp_wav, config):
    """user 片段应调用 API 转写."""
    segments = [
        Segment(start=0.0, end=1.0, segment_index=0, speaker_label="user"),
    ]
    transcriber = Transcriber(config, auto_load_model=False)

    api_result = [
        Utterance(
            text="API 结果",
            start=0.0,
            end=1.0,
            words=[Word(text="API", start=0.0, end=1.0)],
        )
    ]
    transcriber.api_client = MagicMock()
    transcriber.api_client.asr_available = True
    transcriber.api_client.transcribe.return_value = api_result
    transcriber.model = None  # 禁用本地模型

    results = transcriber.transcribe_segments(tmp_wav, segments, "rec1")

    assert len(results) == 1
    assert results[0].asr_source == "api"
    assert results[0].text == "API 结果"
    transcriber.api_client.transcribe.assert_called_once()


def test_other_segments_use_local_asr(tmp_wav, config):
    """other 片段应调用本地 ASR."""
    segments = [
        Segment(start=0.0, end=1.0, segment_index=0, speaker_label="other"),
    ]
    transcriber = Transcriber(config, auto_load_model=False)

    transcriber.model = MagicMock()
    transcriber.model.transcribe.return_value = (
        iter(
            [
                MagicMock(
                    text="本地结果",
                    start=0.0,
                    end=1.0,
                    words=[MagicMock(word="本地", start=0.0, end=1.0, probability=None)],
                )
            ]
        ),
        None,
    )

    results = transcriber.transcribe_segments(tmp_wav, segments, "rec1")

    assert len(results) == 1
    assert results[0].asr_source == "local"
    assert results[0].text == "本地结果"


def _local_result_mock(text: str):
    model = MagicMock()
    model.transcribe.return_value = (
        iter([MagicMock(text=text, start=0.0, end=1.0, words=[])]),
        None,
    )
    return model


def test_api_failure_falls_back_to_local(tmp_wav, config):
    """API 抛错时回退本地模型转写."""
    segments = [
        Segment(start=0.0, end=1.0, segment_index=0, speaker_label="user"),
    ]
    transcriber = Transcriber(config, auto_load_model=False)

    transcriber.api_client = MagicMock()
    transcriber.api_client.asr_available = True
    transcriber.api_client.transcribe.side_effect = RuntimeError("API 错误")
    transcriber.model = _local_result_mock("本地结果")

    results = transcriber.transcribe_segments(tmp_wav, segments, "rec1")

    assert len(results) == 1
    assert results[0].asr_source == "local"
    assert results[0].text == "本地结果"
    assert results[0].status == "success"
    transcriber.model.transcribe.assert_called_once()


def test_api_empty_result_falls_back_to_local(tmp_wav, config):
    """API 返回空结果时回退本地模型."""
    segments = [
        Segment(start=0.0, end=1.0, segment_index=0, speaker_label="user"),
    ]
    transcriber = Transcriber(config, auto_load_model=False)

    transcriber.api_client = MagicMock()
    transcriber.api_client.asr_available = True
    transcriber.api_client.transcribe.return_value = []
    transcriber.model = _local_result_mock("本地结果")

    results = transcriber.transcribe_segments(tmp_wav, segments, "rec1")

    assert len(results) == 1
    assert results[0].asr_source == "local"
    assert results[0].text == "本地结果"


def test_both_api_and_local_fail(tmp_wav, config):
    """API 与本地都失败时返回 failed，错误信息汇总两段原因."""
    segments = [
        Segment(start=0.0, end=1.0, segment_index=0, speaker_label="user"),
    ]
    transcriber = Transcriber(config, auto_load_model=False)

    transcriber.api_client = MagicMock()
    transcriber.api_client.asr_available = True
    transcriber.api_client.transcribe.side_effect = RuntimeError("API 错误")
    transcriber.model = MagicMock()
    transcriber.model.transcribe.side_effect = RuntimeError("本地错误")

    results = transcriber.transcribe_segments(tmp_wav, segments, "rec1")

    assert len(results) == 1
    assert results[0].status == "failed"
    assert results[0].text == ""
    assert "API 错误" in results[0].error_message
    assert "本地错误" in results[0].error_message
