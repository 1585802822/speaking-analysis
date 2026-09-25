"""发音分析测试."""

import importlib.util
from unittest.mock import MagicMock, patch

from src.pronunciation_analyzer import PronunciationAnalyzer
from src.types import Utterance, Word

PYPINYIN_AVAILABLE = importlib.util.find_spec("pypinyin") is not None
PHONEMIZER_AVAILABLE = importlib.util.find_spec("phonemizer") is not None


def _config(phoneme_check: bool = True) -> dict:
    return {
        "analysis": {
            "pronunciation": {
                "low_confidence_threshold": 0.65,
                "phoneme_check": phoneme_check,
            }
        }
    }


def test_low_confidence_words_flagged():
    # 关闭音素检查，仅验证低置信度词被标记
    analyzer = PronunciationAnalyzer(_config(phoneme_check=False))
    utterances = [
        Utterance(
            text="hello",
            start=0.0,
            end=1.0,
            words=[
                Word(text="hello", start=0.0, end=1.0, confidence=0.5),
                Word(text="world", start=1.0, end=2.0, confidence=0.9),
            ],
        )
    ]
    result = analyzer.analyze(utterances)
    assert result.dimension == "pronunciation"
    assert any(f["word"] == "hello" and f.get("confidence") == 0.5 for f in result.findings)
    assert not any(f["word"] == "world" for f in result.findings)


def test_chinese_word_gets_pinyin_when_available():
    analyzer = PronunciationAnalyzer(_config())
    utterances = [
        Utterance(
            text="中",
            start=0.0,
            end=0.5,
            words=[Word(text="中", start=0.0, end=0.5, confidence=0.5)],
        )
    ]
    result = analyzer.analyze(utterances)
    finding = next((f for f in result.findings if f["word"] == "中"), None)
    assert finding is not None
    if PYPINYIN_AVAILABLE:
        assert "pinyin" in finding
        assert finding["tones"]
    else:
        # 缺少 pypinyin 时仍给出低置信度提示, 只是没有拼音字段
        assert "confidence" in finding


def test_english_word_gets_phoneme_tip():
    analyzer = PronunciationAnalyzer(_config())
    utterances = [
        Utterance(
            text="hello",
            start=0.0,
            end=1.0,
            words=[Word(text="hello", start=0.0, end=1.0, confidence=0.9)],
        )
    ]
    result = analyzer.analyze(utterances)
    # phoneme_check=True 时即使置信度不低也会给出提示
    finding = next((f for f in result.findings if f["word"] == "hello"), None)
    assert finding is not None
    assert "phonemes" in finding
    # 若系统未安装 espeak，phonemizer 会回退到 TODO 提示
    if PHONEMIZER_AVAILABLE:
        assert isinstance(finding["phonemes"], str)


def test_phoneme_check_disabled():
    analyzer = PronunciationAnalyzer(_config(phoneme_check=False))
    utterances = [
        Utterance(
            text="hello",
            start=0.0,
            end=1.0,
            words=[Word(text="hello", start=0.0, end=1.0, confidence=0.9)],
        )
    ]
    result = analyzer.analyze(utterances)
    assert len(result.findings) == 0


def _ise_config() -> dict:
    return {
        "analysis": {"pronunciation": {"standard_threshold": 80}},
        "api": {"enabled": True},
    }


def test_ise_scoring_marks_standard(tmp_path):
    analyzer = PronunciationAnalyzer(_ise_config())
    fake_client = MagicMock()
    fake_client.evaluate.return_value = {
        "overall_score": 90.0,
        "accuracy_score": 88.0,
        "fluency_score": 91.0,
        "integrity_score": 95.0,
    }
    utterances = [Utterance(text="你好世界", start=0.0, end=1.5, words=[])]

    with patch("src.pronunciation_analyzer.build_evaluation_client", return_value=fake_client):
        with patch(
            "src.pronunciation_analyzer.crop_audio_segment",
            return_value=tmp_path / "seg.wav",
        ):
            result = analyzer.analyze(utterances, audio_path="dummy.wav")

    assert len(result.findings) == 1
    finding = result.findings[0]
    assert finding["kind"] == "ise_score"
    assert finding["overall_score"] == 90.0
    assert finding["standard"] is True
    assert "标准" in finding["message"]


def test_ise_scoring_marks_not_standard_below_threshold(tmp_path):
    analyzer = PronunciationAnalyzer(_ise_config())
    fake_client = MagicMock()
    fake_client.evaluate.return_value = {
        "overall_score": 60.0,
        "accuracy_score": 55.0,
        "fluency_score": 62.0,
        "integrity_score": 70.0,
    }
    utterances = [Utterance(text="hello", start=0.0, end=1.0, words=[])]

    with patch("src.pronunciation_analyzer.build_evaluation_client", return_value=fake_client):
        with patch(
            "src.pronunciation_analyzer.crop_audio_segment",
            return_value=tmp_path / "seg.wav",
        ):
            result = analyzer.analyze(utterances, audio_path="dummy.wav")

    finding = result.findings[0]
    assert finding["standard"] is False
    assert "不标准" in finding["message"]
