"""音频特征分析."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import librosa
import numpy as np

from .types import AnalysisResult, Segment, Utterance


class AudioAnalyzer:
    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        self.sample_rate = config["segmentation"]["target_sample_rate"]
        self.min_pause = config["analysis"]["min_pause_sec"]
        self.max_pause = config["analysis"]["max_pause_sec"]

    def analyze(
        self, audio_path: Path, utterances: list[Utterance], user_segments: list[Segment]
    ) -> AnalysisResult:
        y, sr = librosa.load(str(audio_path), sr=self.sample_rate, mono=True)
        findings = []
        findings.extend(self._analyze_speech_rate(utterances, user_segments))
        findings.extend(self._analyze_pauses(y, sr, utterances))
        findings.extend(self._analyze_volume(y, sr, utterances))
        findings.extend(self._analyze_clarity(y, sr, utterances))

        summary_parts = []
        if utterances and user_segments:
            total_words = sum(len(u.words) for u in utterances)
            total_min = sum(s.end - s.start for s in user_segments) / 60.0
            rate = total_words / total_min if total_min > 0 else 0
            summary_parts.append(f"平均语速约 {rate:.0f} 词/分钟。")
        if any(f["kind"] == "fast_speech" for f in findings):
            summary_parts.append("部分区间语速偏快。")
        if any(f["kind"] == "pause" for f in findings):
            summary_parts.append("存在停顿问题。")
        summary = " ".join(summary_parts) if summary_parts else "音频特征分析待补充。"

        return AnalysisResult(dimension="audio", findings=findings, summary=summary)

    def _analyze_speech_rate(
        self, utterances: list[Utterance], user_segments: list[Segment]
    ) -> list[dict[str, Any]]:
        findings = []
        if not utterances or not user_segments:
            return findings
        total_speech_sec = sum(s.end - s.start for s in user_segments)
        total_words = sum(len(u.words) for u in utterances)
        avg_rate = total_words / (total_speech_sec / 60.0) if total_speech_sec > 0 else 0

        for utt in utterances:
            duration = utt.end - utt.start
            word_count = len(utt.words)
            if duration <= 0:
                continue
            rate = word_count / (duration / 60.0)
            if rate > avg_rate * 1.3 and rate > 180:
                findings.append(
                    {
                        "kind": "fast_speech",
                        "message": (
                            f"{utt.start:.2f}s - {utt.end:.2f}s 语速偏快 "
                            f"({rate:.0f} 词/分钟)，建议放慢"
                        ),
                        "start": utt.start,
                        "end": utt.end,
                        "rate": rate,
                    }
                )
        return findings

    def _analyze_pauses(
        self, y: np.ndarray, sr: int, utterances: list[Utterance]
    ) -> list[dict[str, Any]]:
        findings = []
        if len(utterances) < 2:
            return findings
        for i in range(len(utterances) - 1):
            gap = utterances[i + 1].start - utterances[i].end
            if gap > self.max_pause:
                findings.append(
                    {
                        "kind": "pause",
                        "message": (
                            f"{utterances[i].end:.2f}s - {utterances[i + 1].start:.2f}s "
                            f"停顿过长 ({gap:.2f}s)"
                        ),
                        "start": utterances[i].end,
                        "end": utterances[i + 1].start,
                        "duration": gap,
                    }
                )
        return findings

    def _analyze_volume(
        self, y: np.ndarray, sr: int, utterances: list[Utterance]
    ) -> list[dict[str, Any]]:
        findings = []
        frame_length = int(sr * 0.02)
        hop_length = int(sr * 0.01)
        rms = librosa.feature.rms(y=y, frame_length=frame_length, hop_length=hop_length)[0]
        times = librosa.frames_to_time(np.arange(len(rms)), sr=sr, hop_length=hop_length)
        mean_rms = np.mean(rms)
        threshold_low = mean_rms * 0.4

        in_low = False
        low_start = 0.0
        for t, value in zip(times, rms):
            if value < threshold_low and not in_low:
                in_low = True
                low_start = t
            elif value >= threshold_low and in_low:
                in_low = False
                if t - low_start > 1.0:
                    findings.append(
                        {
                            "kind": "low_volume",
                            "message": f"{low_start:.2f}s - {t:.2f}s 音量较低，可能不够清晰",
                            "start": low_start,
                            "end": t,
                        }
                    )
        return findings

    def _analyze_clarity(self, y: np.ndarray, sr: int, utterances: list[Utterance]) -> list[dict[str, Any]]:
        """用频谱质心/带宽粗略估计清晰度."""
        findings = []
        spec_bw = librosa.feature.spectral_bandwidth(y=y, sr=sr)[0]
        mean_bw = np.mean(spec_bw)
        if mean_bw < 1000:
            findings.append(
                {
                    "kind": "clarity",
                    "message": "整体频谱带宽较窄，部分发音可能不够清晰",
                    "start": 0.0,
                    "end": len(y) / sr,
                }
            )
        return findings
