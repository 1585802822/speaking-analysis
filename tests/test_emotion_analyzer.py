"""情感/语气分析测试."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from src.emotion_analyzer import EmotionAnalyzer
from src.types import Segment


def _base_config() -> dict:
    return {"analysis": {"emotion": {"model": "dummy/emotion2vec"}}}


def test_analyze_returns_result_for_empty_segments(tmp_path: Path):
    analyzer = EmotionAnalyzer(_base_config())
    result = analyzer.analyze(tmp_path / "nonexistent.wav", [])
    assert result.dimension == "emotion"
    assert len(result.findings) == 0
    assert "未检测到用户语音" in result.summary


def test_fallback_when_model_and_librosa_unavailable(tmp_path: Path):
    analyzer = EmotionAnalyzer(_base_config())
    assert analyzer.model is None
    segments = [Segment(start=0.0, end=1.0, speaker="user")]
    with patch.object(analyzer, "_analyze_with_prosody") as mock_prosody:
        mock_prosody.return_value = [
            {
                "kind": "emotion",
                "message": "fallback",
                "start": segments[0].start,
                "end": segments[-1].end,
                "label": "neutral",
            }
        ]
        result = analyzer.analyze(tmp_path / "nonexistent.wav", segments)
    assert result.dimension == "emotion"
    assert len(result.findings) == 1
    assert result.findings[0]["label"] == "neutral"


def test_prosody_analysis_with_mocked_librosa(tmp_path: Path):
    analyzer = EmotionAnalyzer(_base_config())
    segments = [Segment(start=0.0, end=1.0, speaker="user")]

    fake_y = MagicMock()
    fake_sr = 16000
    fake_rms = MagicMock()
    fake_rms.__getitem__ = MagicMock(return_value=np.array([0.1] * 100))
    fake_times = np.arange(100, dtype=float)

    with patch("src.emotion_analyzer.librosa") as mock_librosa:
        mock_librosa.load.return_value = (fake_y, fake_sr)
        mock_librosa.feature.rms.return_value = fake_rms
        mock_librosa.frames_to_time.side_effect = [fake_times, fake_times]
        mock_librosa.pyin.return_value = (
            np.array([120.0] * 100),
            np.array([True] * 100),
            None,
        )
        mock_librosa.note_to_hz.side_effect = [65.0, 2093.0]

        result = analyzer.analyze(tmp_path / "fake.wav", segments)

    assert result.dimension == "emotion"
    assert len(result.findings) == 1
    assert result.findings[0]["kind"] == "emotion"
    assert "label" in result.findings[0]


def test_model_branch_placeholder(tmp_path: Path):
    config = _base_config()
    analyzer = EmotionAnalyzer(config)
    # 强制模拟模型已加载, 验证占位推理分支
    analyzer.model = MagicMock()
    analyzer.feature_extractor = MagicMock()
    segments = [Segment(start=0.0, end=1.0)]
    result = analyzer.analyze(tmp_path / "fake.wav", segments)
    assert result.dimension == "emotion"
    assert any(f["label"] == "neutral" for f in result.findings)
