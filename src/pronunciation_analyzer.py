"""发音标准/正音分析.

中文: 使用 pypinyin 标注拼音与声调, 对 ASR 低置信度字词给出正音建议.
英文: 使用 phonemizer 给出标准音素, 对 ASR 低置信度单词给出音标练习建议.

当工具未安装时, 回退到仅基于 ASR 置信度的发音提示.
"""

from __future__ import annotations

import re
import warnings
from typing import Any

from .types import AnalysisResult, Utterance, Word

try:
    import pypinyin
    from pypinyin import lazy_pinyin, Style
except ImportError:  # pragma: no cover - 测试环境可能未安装
    pypinyin = None
    lazy_pinyin = None
    Style = None

try:
    from phonemizer import phonemize
except ImportError:  # pragma: no cover - 测试环境可能未安装
    phonemize = None


class PronunciationAnalyzer:
    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        self.low_confidence_threshold = config["analysis"]["pronunciation"][
            "low_confidence_threshold"
        ]
        self.phoneme_check = config["analysis"]["pronunciation"].get(
            "phoneme_check", True
        )

    def analyze(self, utterances: list[Utterance]) -> AnalysisResult:
        """标记低置信度词/字并给出正音建议."""
        findings = []
        for utt in utterances:
            for word in utt.words:
                conf = word.confidence if word.confidence is not None else 1.0
                if conf < self.low_confidence_threshold:
                    findings.extend(
                        self._pronunciation_findings(word, conf, low_confidence=True)
                    )
                elif self.phoneme_check:
                    # 即使置信度不低, 也对复杂发音给出练习提示(目前仅对英文长词)
                    findings.extend(self._pronunciation_findings(word, conf, low_confidence=False))

        summary = (
            f"发现 {len(findings)} 个发音相关提示。"
            if findings
            else "未发现明显发音置信度问题。"
        )
        return AnalysisResult(
            dimension="pronunciation", findings=findings, summary=summary
        )

    def _pronunciation_findings(
        self, word: Word, confidence: float, low_confidence: bool
    ) -> list[dict[str, Any]]:
        """针对单个词生成正音发现."""
        text = word.text.strip()
        if not text:
            return []

        findings = []
        if self._is_chinese(text):
            pinyin_result = self._pinyin_with_tone(text)
            if pinyin_result:
                pinyin, tones = pinyin_result
                finding = {
                    "kind": "pronunciation",
                    "message": (
                        f"{word.start:.2f}s “{text}” 拼音为 [{pinyin}], "
                        f"声调 {' '.join(tones)}; 建议跟读练习, 注意声调饱满"
                    ),
                    "start": word.start,
                    "end": word.end,
                    "word": text,
                    "pinyin": pinyin,
                    "tones": tones,
                }
                if low_confidence:
                    finding["message"] = (
                        f"{word.start:.2f}s “{text}” ASR 置信度较低 ({confidence:.2f}), "
                        f"疑似发音偏差; 拼音 [{pinyin}], 声调 {' '.join(tones)}"
                    )
                    finding["confidence"] = confidence
                findings.append(finding)
            elif low_confidence:
                # pypinyin 不可用时仍标记低置信度中文字词
                findings.append(
                    {
                        "kind": "pronunciation",
                        "message": (
                            f"{word.start:.2f}s “{text}” ASR 置信度较低 ({confidence:.2f}), "
                            f"建议跟读练习并注意声调(需安装 pypinyin 获取拼音)"
                        ),
                        "start": word.start,
                        "end": word.end,
                        "word": text,
                        "confidence": confidence,
                    }
                )
        elif self._is_english(text):
            phonemes = self._english_phonemes(text)
            finding = {
                "kind": "pronunciation",
                "message": (
                    f"{word.start:.2f}s “{text}” 标准音标为 /{phonemes}/, "
                    f"建议对照练习口型与重音"
                ),
                "start": word.start,
                "end": word.end,
                "word": text,
                "phonemes": phonemes,
            }
            if low_confidence:
                finding["message"] = (
                    f"{word.start:.2f}s “{text}” ASR 置信度较低 ({confidence:.2f}), "
                    f"疑似音素发音偏差; 标准音标 /{phonemes}/"
                )
                finding["confidence"] = confidence
            findings.append(finding)
        return findings

    @staticmethod
    def _is_chinese(text: str) -> bool:
        return any("\u4e00" <= ch <= "\u9fff" for ch in text)

    @staticmethod
    def _is_english(text: str) -> bool:
        # 仅包含 ASCII 字母(允许常见连字符/撇号), 不含中文
        return re.fullmatch(r"[A-Za-z\-']+", text) is not None

    def _pinyin_with_tone(self, text: str) -> tuple[str, list[str]] | None:
        """使用 pypinyin 获取拼音和声调数字."""
        if lazy_pinyin is None or Style is None:
            return None
        try:
            pinyin_list = lazy_pinyin(text, style=Style.TONE3)
            pinyin = " ".join(pinyin_list)
            tone_list = lazy_pinyin(text, style=Style.TONE3)
            tones = [self._extract_tone(py) for py in tone_list]
            return pinyin, tones
        except Exception as exc:
            warnings.warn(f"pypinyin 处理失败 '{text}': {exc}")
            return None

    @staticmethod
    def _extract_tone(pinyin: str) -> str:
        """从带声调数字的拼音中提取声调."""
        match = re.search(r"[1-5]$", pinyin)
        if match:
            return match.group(0)
        return "0"

    def _english_phonemes(self, text: str) -> str:
        """使用 phonemizer 获取英文音素."""
        if phonemize is None:
            return "TODO: 需要 phonemizer/espeak"
        try:
            phones = phonemize(
                text,
                language="en-us",
                backend="espeak",
                strip=True,
                preserve_punctuation=False,
                with_stress=True,
            )
            return phones.strip()
        except Exception as exc:
            warnings.warn(f"phonemizer 处理失败 '{text}': {exc}")
            return "TODO: 需要 phonemizer/espeak"
