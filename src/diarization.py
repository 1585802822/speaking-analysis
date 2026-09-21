"""说话人分离与用户语音筛选."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import librosa
import numpy as np

from .embeddings import extract_embedding_from_array
from .segment_filter import filter_target_speaker
from .types import Segment


class DiarizationModule:
    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        speaker_cfg = config.get("speaker", {})
        self.similarity_threshold = speaker_cfg.get(
            "similarity_threshold",
            config.get("preprocessing", {}).get("speaker_filter", {}).get(
                "similarity_threshold", 0.75
            ),
        )
        self.low_confidence_threshold = speaker_cfg.get(
            "low_confidence_threshold",
            config.get("preprocessing", {}).get("speaker_filter", {}).get(
                "low_confidence_threshold", 0.55
            ),
        )
        self.parallel_workers = max(
            1,
            int(
                config.get("segmentation", {}).get(
                    "parallel_workers",
                    config.get("preprocessing", {})
                    .get("segmentation", {})
                    .get("parallel_workers", 1),
                )
            ),
        )

    @staticmethod
    def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
        """计算两个向量的余弦相似度，零向量安全."""
        a = np.asarray(a, dtype=np.float32)
        b = np.asarray(b, dtype=np.float32)
        norm_a = float(np.linalg.norm(a))
        norm_b = float(np.linalg.norm(b))
        if norm_a < 1e-8 or norm_b < 1e-8:
            return 0.0
        return float(np.dot(a, b) / (norm_a * norm_b))

    def _extract_segment_embedding(
        self, seg: Segment, audio_path: str | Path | None, audio_array: tuple[np.ndarray, int] | None = None
    ) -> np.ndarray:
        """从音频路径或数组中提取指定片段的嵌入向量.

        默认使用本地 MFCC 统计特征回退；单元测试可通过 monkey-patch 替换此方法。
        传入 audio_array=(y, sr) 后跳过文件加载, 避免重复 IO.
        """
        if audio_array is not None:
            y, sr = audio_array
        elif audio_path is not None and Path(audio_path).exists():
            y, sr = self._load_audio(audio_path)
        else:
            return np.zeros(1, dtype=np.float32)
        start_sample = int(seg.start * sr)
        end_sample = int(seg.end * sr)
        start_sample = max(0, min(start_sample, len(y)))
        end_sample = max(0, min(end_sample, len(y)))
        if end_sample <= start_sample:
            return np.zeros(1, dtype=np.float32)
        return extract_embedding_from_array(y[start_sample:end_sample], sr, self.config)

    def _load_audio(self, audio_path: str | Path) -> tuple[np.ndarray, int]:
        """加载音频为单声道 16kHz 数组."""
        import librosa

        y, sr = librosa.load(str(audio_path), sr=16000, mono=True)
        return y, sr

    def identify_user(
        self,
        segments: list[Segment],
        voiceprint: dict[str, Any] | None,
        audio_path: str | Path | None = None,
    ) -> list[Segment]:
        """从片段中识别用户语音.

        对每个片段提取本地音频嵌入，与注册声纹计算余弦相似度并筛选用户语音。
        当音频路径不存在或嵌入提取失败时，置信度置 0 并过滤，避免误识别。
        """
        if voiceprint is None:
            raise RuntimeError("未找到注册声纹，请先执行注册流程。")

        reference = np.asarray(voiceprint["embedding"], dtype=np.float32)
        reference_norm = float(np.linalg.norm(reference))
        if reference_norm < 1e-8:
            # 注册声纹异常时安全降级：所有片段都标记为非用户
            for seg in segments:
                seg.is_user = False
                seg.speaker_label = "unknown"
                seg.speaker_confidence = 0.0
                seg.confidence = 0.0
            return []

        def _embed(seg: Segment) -> np.ndarray:
            return self._extract_segment_embedding(seg, audio_path)

        if self.parallel_workers > 1 and len(segments) > 1:
            with ThreadPoolExecutor(max_workers=self.parallel_workers) as executor:
                embeddings = list(executor.map(_embed, segments))
        else:
            embeddings = [_embed(seg) for seg in segments]

        results = []
        for seg, seg_emb in zip(segments, embeddings):
            try:
                similarity = self._cosine_similarity(reference, seg_emb)
            except Exception:
                # 片段过短或异常时给中等置信度，让用户人工确认
                similarity = self.low_confidence_threshold - 0.05

            is_user = similarity >= self.similarity_threshold
            seg.is_user = is_user
            seg.speaker_label = "user" if is_user else "other"
            seg.speaker_confidence = similarity
            seg.confidence = similarity
            if similarity < self.low_confidence_threshold:
                seg.needs_review = True
            results.append(seg)

        return [s for s in results if s.is_user]

    def filter_segments_by_voiceprint(
        self,
        segments: list[Segment],
        audio_path: str | Path,
        voiceprint: dict[str, Any] | None = None,
    ) -> list[Segment]:
        """按声纹从音频文件中筛选目标说话人片段.

        与 identify_user 相比，本方法直接加载音频数组后调用 segment_filter，
        避免多次 IO，并统一写入 Segment 元数据。
        """
        if voiceprint is None:
            voiceprint = self.config.get("voiceprint")
        if voiceprint is None:
            raise RuntimeError("未找到注册声纹，请先执行注册流程。")

        y, sr = librosa.load(str(audio_path), sr=16000, mono=True)
        speaker_cfg = self.config.get("speaker", {})
        pre_filter_cfg = self.config.get("preprocessing", {}).get("speaker_filter", {})
        enabled = pre_filter_cfg.get("enabled", speaker_cfg.get("enabled", True))
        if not enabled:
            for seg in segments:
                seg.is_user = True
                seg.speaker_label = "user"
            return segments

        similarity_threshold = pre_filter_cfg.get(
            "similarity_threshold", self.similarity_threshold
        )
        low_confidence_threshold = pre_filter_cfg.get(
            "low_confidence_threshold", self.low_confidence_threshold
        )

        return filter_target_speaker(
            segments,
            y,
            sr,
            np.asarray(voiceprint["embedding"], dtype=np.float32),
            self.config,
            similarity_threshold=similarity_threshold,
            low_confidence_threshold=low_confidence_threshold,
            parallel_workers=self.parallel_workers,
        )

    def split_by_voiceprint(
        self,
        segments: list[Segment],
        audio_path: str | Path,
        voiceprint: dict[str, Any] | None = None,
        window_sec: float = 3.0,
        hop_sec: float = 1.5,
        audio_array: tuple[np.ndarray, int] | None = None,
    ) -> list[Segment]:
        """对预处理片段按滑动窗口二次切分，实现说话人分离.

        对每个 Segment 生成固定长度的滑动子窗口，提取嵌入后与注册声纹比对，
        根据相似度阈值标记 speaker_label，最后合并连续同标签窗口。

        Parameters
        ----------
        audio_array : 可选的 (y, sr) 元组, 传入后跳过文件加载; 测试时可避免 IO.
        """
        if voiceprint is None:
            voiceprint = self.config.get("voiceprint")
        if voiceprint is None:
            raise RuntimeError("未找到注册声纹，请先执行注册流程。")

        if audio_array is not None:
            y, sr = audio_array
        else:
            y, sr = librosa.load(str(audio_path), sr=16000, mono=True)
        reference = np.asarray(voiceprint["embedding"], dtype=np.float32)
        reference_norm = float(np.linalg.norm(reference))
        if reference_norm < 1e-8:
            for seg in segments:
                seg.is_user = False
                seg.speaker_label = "unknown"
                seg.speaker_confidence = 0.0
                seg.confidence = 0.0
                seg.needs_review = True
            return []

        speaker_cfg = self.config.get("speaker", {})
        pre_filter_cfg = self.config.get("preprocessing", {}).get("speaker_filter", {})
        similarity_threshold = pre_filter_cfg.get(
            "similarity_threshold", self.similarity_threshold
        )
        low_confidence_threshold = pre_filter_cfg.get(
            "low_confidence_threshold", self.low_confidence_threshold
        )

        window_samples = int(window_sec * sr)
        hop_samples = max(1, int(hop_sec * sr))
        min_seg_samples = max(1, int(0.5 * sr))  # 不足半秒的片段直接跳过

        windows: list[Segment] = []
        for seg in sorted(segments, key=lambda s: (s.start, s.end)):
            seg_start_sample = max(0, int(seg.start * sr))
            seg_end_sample = max(0, int(seg.end * sr))
            if seg_end_sample - seg_start_sample < min_seg_samples:
                continue
            if seg_end_sample - seg_start_sample <= window_samples:
                windows.append(
                    Segment(start=seg_start_sample / sr, end=seg_end_sample / sr)
                )
                continue
            seg_windows: list[Segment] = []
            start = seg_start_sample
            while start + window_samples < seg_end_sample:
                seg_windows.append(
                    Segment(start=start / sr, end=(start + window_samples) / sr)
                )
                start += hop_samples
            # 尾窗回退补足整窗，避免过短窗口导致嵌入失真、标签抖动
            tail_start = seg_end_sample - window_samples
            if not seg_windows or tail_start > int(seg_windows[-1].start * sr):
                seg_windows.append(
                    Segment(start=tail_start / sr, end=seg_end_sample / sr)
                )
            else:
                seg_windows[-1].end = seg_end_sample / sr
            windows.extend(seg_windows)

        def _embed(seg: Segment) -> np.ndarray:
            return self._extract_segment_embedding(seg, str(audio_path), audio_array=(y, sr))

        if self.parallel_workers > 1 and len(windows) > 1:
            with ThreadPoolExecutor(max_workers=self.parallel_workers) as executor:
                embeddings = list(executor.map(_embed, windows))
        else:
            embeddings = [_embed(seg) for seg in windows]

        for seg, seg_emb in zip(windows, embeddings):
            try:
                similarity = self._cosine_similarity(reference, seg_emb)
            except Exception:
                similarity = low_confidence_threshold - 0.05

            if similarity >= similarity_threshold:
                label = "user"
            elif similarity >= low_confidence_threshold:
                label = "other"
            else:
                label = "unknown"
                seg.needs_review = True

            seg.speaker_label = label
            seg.speaker_confidence = similarity
            seg.confidence = similarity
            seg.is_user = label == "user"

        self._smooth_window_labels(windows)
        return self._merge_same_speaker_windows(windows)

    @staticmethod
    def _smooth_window_labels(windows: list[Segment]) -> None:
        """消除孤立的窗口标签翻转：左右相邻窗口标签一致且不同于当前窗口时采用邻居标签.

        滑动窗口分类在说话人交界处容易产生单窗口误判，先平滑再合并
        可以减少碎片片段。
        """
        if len(windows) < 3:
            return
        labels = [w.speaker_label for w in windows]
        for i in range(1, len(labels) - 1):
            left, center, right = labels[i - 1], labels[i], labels[i + 1]
            if left is not None and left == right and center != left:
                windows[i].speaker_label = left
                windows[i].is_user = left == "user"
                windows[i].needs_review = left == "unknown"

    @staticmethod
    def _merge_same_speaker_windows(windows: list[Segment]) -> list[Segment]:
        """合并连续同说话人窗口，并裁剪相邻片段的重叠区.

        滑动窗口步长小于窗长时相邻窗口存在重叠，若直接按窗口端点拼接，
        相邻两个说话人的片段会共享同一段音频（导出后表现为"有重合"）。
        这里先把连续同标签窗口聚合为 run（待复核标志传播到整个 run），
        再将相邻 run 的重叠区从中点切开，保证输出片段按时间排序、
        连续且互不重叠。
        """
        if not windows:
            return []

        ordered = sorted(windows, key=lambda w: (w.start, w.end))

        # 1) 聚合连续同标签窗口；待复核标志传播到整个 run，
        #    避免连续 unknown 窗口被拆成大量碎片片段
        runs: list[dict[str, Any]] = []
        for win in ordered:
            if runs:
                last = runs[-1]
                if win.speaker_label == last["label"]:
                    duration_last = last["end"] - last["start"]
                    duration_win = win.end - win.start
                    total = duration_last + duration_win
                    if (
                        total > 0
                        and last["confidence"] is not None
                        and win.speaker_confidence is not None
                    ):
                        last["confidence"] = (
                            last["confidence"] * duration_last
                            + win.speaker_confidence * duration_win
                        ) / total
                    last["end"] = max(last["end"], win.end)
                    last["needs_review"] = last["needs_review"] or win.needs_review
                    continue
            runs.append(
                {
                    "start": win.start,
                    "end": win.end,
                    "label": win.speaker_label,
                    "confidence": win.speaker_confidence,
                    "is_user": win.is_user,
                    "needs_review": win.needs_review,
                }
            )

        # 2) 相邻 run 重叠时以重叠区中点为共同边界
        for i in range(len(runs) - 1):
            cur, nxt = runs[i], runs[i + 1]
            if nxt["start"] < cur["end"]:
                boundary = (nxt["start"] + cur["end"]) / 2.0
                cur["end"] = boundary
                nxt["start"] = boundary

        merged: list[Segment] = []
        for run in runs:
            if run["end"] - run["start"] <= 1e-6:
                continue
            if merged and run["start"] < merged[-1].end - 1e-9:
                # 中间 run 被裁剪耗尽丢弃后，后一段可能仍越过前一段结尾，
                # 以前一段结尾为硬边界，保证输出任何情况下互不重叠
                run["start"] = merged[-1].end
                if run["end"] - run["start"] <= 1e-6:
                    continue
            merged.append(
                Segment(
                    start=run["start"],
                    end=run["end"],
                    speaker_label=run["label"],
                    speaker_confidence=run["confidence"],
                    confidence=run["confidence"],
                    is_user=run["is_user"],
                    needs_review=run["needs_review"],
                )
            )
        return merged
