"""发音标准/正音分析.

- 优先：调用讯飞语音评测（ISE）API, 对用户片段输出准确度/流利度/完整度分数,
  并解析中文音素级（声母/韵母）发音细节, 判断普通话/英语发音是否标准。
- 回退：当未启用 ISE 或未提供音频路径时, 使用 pypinyin/phonemizer 给出
  拼音/音标参考, 对 ASR 低置信度字词给出正音建议。
"""

from __future__ import annotations

import logging
import re
import tempfile
import warnings
from pathlib import Path
from typing import Any

from .embeddings import crop_audio_segment
from .iflytek_evaluation_client import build_evaluation_client
from .types import AnalysisResult, Utterance, Word

logger = logging.getLogger(__name__)

try:
    import pypinyin
    from pypinyin import Style, lazy_pinyin
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
        pron_cfg = config.get("analysis", {}).get("pronunciation", {})
        self.low_confidence_threshold = pron_cfg.get("low_confidence_threshold", 0.65)
        self.phoneme_check = pron_cfg.get("phoneme_check", True)
        self.standard_threshold = pron_cfg.get("standard_threshold", 80)

    def analyze(
        self, utterances: list[Utterance], audio_path: str | Path | None = None
    ) -> AnalysisResult:
        """分析发音, 优先 ISE 打分, 回退到拼音/音标提示."""
        # 仅在提供音频路径时才尝试 ISE 评测
        ise_client = build_evaluation_client(self.config) if audio_path is not None else None

        if ise_client is not None:
            findings = self._analyze_with_ise(ise_client, audio_path, utterances)
        else:
            findings = self._analyze_local(utterances)

        summary = f"发现 {len(findings)} 个发音相关提示。" if findings else "未发现明显发音问题。"
        return AnalysisResult(dimension="pronunciation", findings=findings, summary=summary)

    def _analyze_with_ise(
        self,
        ise_client: Any,
        audio_path: str | Path,
        utterances: list[Utterance],
    ) -> list[dict[str, Any]]:
        """逐句调用 ISE 评测, 输出量化分数与标准判定."""
        findings: list[dict[str, Any]] = []
        for utt in utterances:
            text = utt.text.strip()
            if not text or utt.end - utt.start <= 0:
                continue
            try:
                with tempfile.TemporaryDirectory() as tmpdir:
                    seg_wav = crop_audio_segment(
                        audio_path,
                        utt.start,
                        utt.end,
                        Path(tmpdir) / "seg.wav",
                    )
                    language = self._detect_language(text)
                    scores = ise_client.evaluate(seg_wav, text, language=language)
            except Exception as exc:  # 单句评测失败不影响整体流程
                logger.warning("ISE 评测失败 [%s] “%s”: %s", utt.start, text, exc)
                continue

            overall = scores.get("overall_score")
            standard = overall is not None and overall >= self.standard_threshold
            verdict = "标准" if standard else "不标准，建议跟读练习"
            finding: dict[str, Any] = {
                "kind": "ise_score",
                "start": utt.start,
                "end": utt.end,
                "text": text,
                "overall_score": overall,
                "accuracy_score": scores.get("accuracy_score"),
                "fluency_score": scores.get("fluency_score"),
                "integrity_score": scores.get("integrity_score"),
                "standard": standard,
            }
            parts = [f"{utt.start:.2f}s-{utt.end:.2f}s “{text}” 发音{verdict}"]
            if overall is not None:
                parts.append(f"总分 {overall:.1f}")
            detail = []
            if scores.get("accuracy_score") is not None:
                detail.append(f"准确度 {scores['accuracy_score']:.1f}")
            if scores.get("fluency_score") is not None:
                detail.append(f"流利度 {scores['fluency_score']:.1f}")
            if scores.get("integrity_score") is not None:
                detail.append(f"完整度 {scores['integrity_score']:.1f}")
            if detail:
                parts.append("（" + "、".join(detail) + "）")
            finding["message"] = " ".join(parts)
            findings.append(finding)

            # 音素级发音细节: 只为不标准的音素生成 finding, 避免报告噪音.
            # beg_pos/end_pos 单位为帧（1 帧 = 10ms）, 换算成秒后加上句子起始偏移.
            for ph in scores.get("phone_details") or []:
                if ph.get("is_correct"):
                    continue
                phone_text = (ph.get("phone") or "").strip()
                word_text = (ph.get("word_text") or "").strip()
                if not phone_text and not word_text:
                    continue
                start = utt.start + int(ph.get("beg_pos") or 0) * 0.01
                end = utt.start + int(ph.get("end_pos") or 0) * 0.01
                error_type = ph.get("error_type") or "发音偏差"
                pinyin = ph.get("pinyin") or ""
                tone = ph.get("tone") or ""
                phone_finding: dict[str, Any] = {
                    "kind": "ise_phone",
                    "start": start,
                    "end": end,
                    "word_text": word_text,
                    "phone": phone_text,
                    "pinyin": pinyin,
                    "tone": tone,
                    "is_yun": ph.get("is_yun"),
                    "error_type": error_type,
                    "is_correct": False,
                }
                tone_part = f"（{tone}）" if tone else ""
                word_part = f"「{word_text}」的" if word_text else ""
                phone_finding["message"] = (
                    f"{start:.2f}s {word_part}音素「{phone_text}」发音不标准：{error_type}"
                    f"{tone_part}，拼音 {pinyin}，建议跟读纠正"
                )
                findings.append(phone_finding)
        return findings

    def _analyze_local(self, utterances: list[Utterance]) -> list[dict[str, Any]]:
        """未启用 ISE 时, 标记低置信度词并给出拼音/音标参考."""
        findings: list[dict[str, Any]] = []
        for utt in utterances:
            for word in utt.words:
                conf = word.confidence if word.confidence is not None else 1.0
                if conf < self.low_confidence_threshold:
                    findings.extend(self._pronunciation_findings(word, conf, low_confidence=True))
                elif self.phoneme_check:
                    # 即使置信度不低, 也对复杂发音给出练习提示(目前仅对英文长词)
                    findings.extend(self._pronunciation_findings(word, conf, low_confidence=False))
        return findings

    def _detect_language(self, text: str) -> str | None:
        """根据文本内容粗判评测语言, 无法判断时返回 None（使用配置默认值）."""
        if self._is_chinese(text):
            return "cn"
        if self._is_english(text):
            return "en"
        return None

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
                    f"{word.start:.2f}s “{text}” 标准音标为 /{phonemes}/, 建议对照练习口型与重音"
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
        return any("一" <= ch <= "鿿" for ch in text)

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
