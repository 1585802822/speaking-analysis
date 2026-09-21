"""文本分析."""

from __future__ import annotations

import re
from typing import Any

from .types import AnalysisResult, Utterance, Word


class TextAnalyzer:
    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        self.filler_words_zh = set(config["analysis"]["filler_words"]["zh"])
        self.filler_words_en = set(config["analysis"]["filler_words"]["en"])
        self.max_sentence_words = config["analysis"]["max_sentence_words"]

    def analyze(self, utterances: list[Utterance]) -> AnalysisResult:
        findings = []
        findings.extend(self._detect_fillers(utterances))
        findings.extend(self._detect_repetitions(utterances))
        findings.extend(self._detect_long_sentences(utterances))
        findings.extend(self._detect_logic_connectors(utterances))

        summary_parts = []
        if any(f["kind"] == "filler" for f in findings):
            summary_parts.append("存在填充词使用。")
        if any(f["kind"] == "repetition" for f in findings):
            summary_parts.append("存在重复表达。")
        if any(f["kind"] == "long_sentence" for f in findings):
            summary_parts.append("存在过长句子。")
        summary = " ".join(summary_parts) if summary_parts else "文本表达整体良好。"

        return AnalysisResult(dimension="text", findings=findings, summary=summary)

    def _detect_fillers(self, utterances: list[Utterance]) -> list[dict[str, Any]]:
        findings = []
        for utt in utterances:
            for word in utt.words:
                text = word.text.strip().lower()
                if text in self.filler_words_zh or text in self.filler_words_en:
                    findings.append(
                        {
                            "kind": "filler",
                            "message": f"{word.start:.2f}s 使用填充词“{word.text}”",
                            "start": word.start,
                            "end": word.end,
                            "word": word.text,
                        }
                    )
        return findings

    def _detect_repetitions(self, utterances: list[Utterance]) -> list[dict[str, Any]]:
        findings = []
        for utt in utterances:
            words = [w.text for w in utt.words]
            for i in range(len(words) - 1):
                if words[i] and words[i] == words[i + 1]:
                    start = utt.words[i].start
                    end = utt.words[i + 1].end
                    findings.append(
                        {
                            "kind": "repetition",
                            "message": f"{start:.2f}s - {end:.2f}s 连续重复“{words[i]}”",
                            "start": start,
                            "end": end,
                            "word": words[i],
                        }
                    )
        return findings

    def _detect_long_sentences(self, utterances: list[Utterance]) -> list[dict[str, Any]]:
        findings = []
        for utt in utterances:
            count = len(utt.words)
            if count > self.max_sentence_words:
                findings.append(
                    {
                        "kind": "long_sentence",
                        "message": (
                            f"{utt.start:.2f}s - {utt.end:.2f}s 句子过长 "
                            f"({count} 词)，建议拆分为 2-3 个短句"
                        ),
                        "start": utt.start,
                        "end": utt.end,
                        "word_count": count,
                    }
                )
        return findings

    def _detect_logic_connectors(self, utterances: list[Utterance]) -> list[dict[str, Any]]:
        """统计逻辑连接词密度，作为结构参考."""
        findings = []
        connectors = {"然后", "所以", "但是", "因此", "而且", "不过", "因为", "另外"}
        for utt in utterances:
            count = sum(1 for w in utt.words if w.text in connectors)
            if count >= 3:
                findings.append(
                    {
                        "kind": "logic_connector",
                        "message": (
                            f"{utt.start:.2f}s - {utt.end:.2f}s 使用了 {count} 个逻辑连接词，"
                            "注意避免堆砌"
                        ),
                        "start": utt.start,
                        "end": utt.end,
                        "count": count,
                    }
                )
        return findings
