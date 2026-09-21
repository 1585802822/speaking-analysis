"""情感/语气分析.

优先加载 emotion2vec 等预训练模型; 不可用时回退到基于 librosa 的韵律起伏分析.
"""

from __future__ import annotations

import warnings
from pathlib import Path
from typing import Any

import numpy as np

from .types import AnalysisResult, Segment

try:
    import librosa
except ImportError:  # pragma: no cover - 测试环境可能未安装
    librosa = None


class EmotionAnalyzer:
    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        self.model = None
        self.feature_extractor = None
        self._load_model()

    def _load_model(self) -> None:
        """尝试加载 emotion2vec 或类似模型, 失败则使用本地回退."""
        model_name = (
            self.config.get("analysis", {})
            .get("emotion", {})
            .get("model", "emotion2vec/emotion2vec_plus_base")
        )
        try:
            # TODO: emotion2vec 官方仓库使用 modelscope/funasr, 这里保留 transformers 加载接口.
            # 当环境安装了对应依赖后可按实际 API 调整.
            from transformers import AutoFeatureExtractor, AutoModel

            self.feature_extractor = AutoFeatureExtractor.from_pretrained(model_name)
            self.model = AutoModel.from_pretrained(model_name)
        except Exception as exc:
            warnings.warn(
                f"无法加载情感模型 {model_name}, 将使用本地韵律特征回退: {exc}"
            )
            self.model = None
            self.feature_extractor = None

    def analyze(self, audio_path: Path, user_segments: list[Segment]) -> AnalysisResult:
        """分析情感和语气起伏."""
        if not user_segments:
            return AnalysisResult(
                dimension="emotion",
                findings=[],
                summary="未检测到用户语音, 跳过情感分析。",
            )

        if self.model is not None:
            findings = self._analyze_with_model(audio_path, user_segments)
        else:
            findings = self._analyze_with_prosody(audio_path, user_segments)

        if not findings:
            summary = "未检测到明显情感/语气异常。"
        else:
            labels = [f.get("label", "unknown") for f in findings]
            summary = (
                f"检测到 {len(findings)} 个情感/语气区间, "
                f"主要标签: {', '.join(set(labels))}。"
            )
        return AnalysisResult(dimension="emotion", findings=findings, summary=summary)

    def _analyze_with_model(
        self, audio_path: Path, user_segments: list[Segment]
    ) -> list[dict[str, Any]]:
        """使用预训练模型推理(占位实现, 需按实际模型 API 补全)."""
        # TODO: 按 emotion2vec 实际接口实现逐段推理, 目前仅在模型加载成功时返回占位结果.
        warnings.warn("情感模型已加载, 但模型推理逻辑仍为 TODO, 返回占位标签。")
        return [
            {
                "kind": "emotion",
                "message": "整体情绪偏中性(模型推理待实现)",
                "start": user_segments[0].start,
                "end": user_segments[-1].end,
                "label": "neutral",
                "score": 0.5,
            }
        ]

    def _analyze_with_prosody(
        self, audio_path: Path, user_segments: list[Segment]
    ) -> list[dict[str, Any]]:
        """基于音高/能量/语速的本地韵律起伏分析."""
        if librosa is None:
            warnings.warn("librosa 未安装, 无法提取韵律特征")
            return [
                {
                    "kind": "emotion",
                    "message": "整体情绪偏中性(模型与 librosa 均不可用)",
                    "start": user_segments[0].start,
                    "end": user_segments[-1].end,
                    "label": "neutral",
                }
            ]

        try:
            y, sr = librosa.load(str(audio_path), sr=16000, mono=True)
        except Exception as exc:
            warnings.warn(f"加载音频失败: {exc}")
            return [
                {
                    "kind": "emotion",
                    "message": "音频加载失败, 无法分析情感",
                    "start": user_segments[0].start,
                    "end": user_segments[-1].end,
                    "label": "unknown",
                }
            ]

        hop_length = int(sr * 0.01)
        frame_length = int(sr * 0.02)
        rms = librosa.feature.rms(
            y=y, frame_length=frame_length, hop_length=hop_length
        )[0]
        times = librosa.frames_to_time(np.arange(len(rms)), sr=sr, hop_length=hop_length)

        # 使用 pyin 提取基频, 失败则使用 yin
        try:
            f0, voiced_flag, _ = librosa.pyin(
                y, fmin=librosa.note_to_hz("C2"), fmax=librosa.note_to_hz("C7"), sr=sr
            )
            f0_times = librosa.frames_to_time(np.arange(len(f0)), sr=sr)
        except Exception:
            f0 = librosa.yin(
                y, fmin=librosa.note_to_hz("C2"), fmax=librosa.note_to_hz("C7"), sr=sr
            )
            f0_times = librosa.frames_to_time(np.arange(len(f0)), sr=sr)

        findings = []
        for seg in user_segments:
            mask_rms = (times >= seg.start) & (times < seg.end)
            seg_rms = rms[mask_rms]
            f0_mask = (f0_times >= seg.start) & (f0_times < seg.end)
            seg_f0 = f0[f0_mask]
            seg_f0 = seg_f0[~np.isnan(seg_f0)]

            if len(seg_rms) == 0:
                continue

            energy_mean = float(np.mean(seg_rms))
            energy_std = float(np.std(seg_rms))
            if len(seg_f0) > 0:
                pitch_mean = float(np.mean(seg_f0))
                pitch_std = float(np.std(seg_f0))
                pitch_variation = pitch_std / (pitch_mean + 1e-8)
            else:
                pitch_mean = 0.0
                pitch_std = 0.0
                pitch_variation = 0.0

            label, message = self._prosody_label(
                energy_mean, energy_std, pitch_mean, pitch_variation
            )
            findings.append(
                {
                    "kind": "emotion",
                    "message": message,
                    "start": seg.start,
                    "end": seg.end,
                    "label": label,
                    "energy_mean": round(energy_mean, 4),
                    "pitch_mean": round(pitch_mean, 2),
                    "pitch_variation": round(pitch_variation, 4),
                }
            )

        return findings

    def _prosody_label(
        self,
        energy_mean: float,
        energy_std: float,
        pitch_mean: float,
        pitch_variation: float,
    ) -> tuple[str, str]:
        """根据韵律特征给出简单标签."""
        # 阈值仅作演示, 实际可配置
        if energy_std > 0.15 and pitch_variation > 0.15:
            return (
                "excited",
                "该区间音高与能量起伏较大, 听起来较兴奋或富有感染力",
            )
        if energy_mean < 0.05 and pitch_variation < 0.08:
            return (
                "flat",
                "该区间音量偏低且音高变化平缓, 可能显得平淡, 建议增加语气起伏",
            )
        if pitch_variation > 0.18 and energy_mean > 0.08:
            return (
                "tense",
                "该区间音高抖动明显且音量较大, 可能显得紧张, 建议放松语速",
            )
        return ("neutral", "该区间情绪/语气整体平稳")
