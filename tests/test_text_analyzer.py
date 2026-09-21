"""文本分析单元测试."""

from src.text_analyzer import TextAnalyzer
from src.types import Utterance, Word


def test_detect_fillers():
    config = {
        "analysis": {
            "filler_words": {
                "zh": ["然后", "嗯"],
                "en": ["um", "like"],
            },
            "max_sentence_words": 5,
        }
    }
    analyzer = TextAnalyzer(config)
    utterances = [
        Utterance(
            text="然后然后",
            start=0.0,
            end=2.0,
            words=[
                Word(text="然后", start=0.0, end=0.5),
                Word(text="然后", start=0.5, end=1.0),
            ],
        )
    ]
    result = analyzer.analyze(utterances)
    assert any(f["kind"] == "filler" for f in result.findings)
    assert any(f["kind"] == "repetition" for f in result.findings)
