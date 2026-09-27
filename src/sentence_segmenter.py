"""句子级音频切分与持久化.

在 ``Preprocessor`` 降噪/VAD 的基础上，把语音区间进一步切分为“一句话一段”，
并持久化保存到 ``data/segments/{recording_id}/`` 目录，供后续声纹分离和 ASR 使用。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import librosa
import numpy as np

from .audio_utils import export_segment
from .preprocessor import Preprocessor
from .recording_id import recording_id_from_path
from .types import Segment

logger = logging.getLogger(__name__)


class SentenceSegmenter:
    """句子级音频切分器."""

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        seg_cfg = config.get("sentence_segmentation", {})
        self.sample_rate = seg_cfg.get(
            "target_sample_rate",
            config.get("preprocessing", {})
            .get("segmentation", {})
            .get("target_sample_rate", 16000),
        )
        self.min_sentence_sec = seg_cfg.get("min_sentence_sec", 0.5)
        self.max_sentence_sec = seg_cfg.get("max_sentence_sec", 15.0)
        self.pause_threshold_sec = seg_cfg.get("pause_threshold_sec", 0.7)
        self.min_pause_sec = seg_cfg.get("min_pause_sec", 0.2)
        self.target_sentence_sec = seg_cfg.get("target_sentence_sec", 2.0)
        self.padding_sec = seg_cfg.get("padding_sec", 0.1)
        self.segments_dir = Path(config.get("segments_dir", "./data/segments"))

    def _detect_speech_intervals(self, y: np.ndarray, sr: int) -> list[tuple[float, float]]:
        """检测有效语音区间，返回秒级起止时间."""
        # 复用 Preprocessor 的 VAD 能力
        preprocessor = Preprocessor(self.config)
        intervals, _ = preprocessor._vad(y, sr)
        return [(start / sr, end / sr) for start, end in intervals]

    def _find_sentence_boundaries(
        self, y: np.ndarray, sr: int, start_sec: float, end_sec: float
    ) -> list[float]:
        """在一个语音区间内，基于能量停顿检测句子边界.

        返回边界时间列表（包含起点和终点）。
        """
        start_sample = int(start_sec * sr)
        end_sample = int(end_sec * sr)
        region = y[start_sample:end_sample]
        if len(region) == 0:
            return [start_sec, end_sec]

        # 分帧计算 RMS 能量
        frame_length = int(sr * 0.02)
        hop_length = int(sr * 0.01)
        rms = librosa.feature.rms(y=region, frame_length=frame_length, hop_length=hop_length)[0]

        # 能量阈值：基于中位数和峰值动态设定，确保不超过峰值
        threshold = np.median(rms) * 2.0 + np.max(rms) * 0.05
        threshold = min(threshold, np.max(rms) * 0.5)
        is_speech = rms > threshold

        # 找连续静音帧超过阈值的点作为边界
        pause_frames_needed = max(1, int(self.pause_threshold_sec * sr / hop_length))
        min_pause_frames = max(1, int(self.min_pause_sec * sr / hop_length))

        boundaries: list[float] = [start_sec]
        silence_start: int | None = None
        for i, speech in enumerate(is_speech):
            if not speech:
                if silence_start is None:
                    silence_start = i
            else:
                if silence_start is not None:
                    silence_frames = i - silence_start
                    if silence_frames >= pause_frames_needed:
                        # 边界取静音终点（下一句语音起点），避免把后句开头截掉
                        boundary_sec = start_sec + i * hop_length / sr
                        boundaries.append(boundary_sec)
                    silence_start = None

        # 处理结尾静音：边界取静音起点（语音终点），不保留拖尾静音
        if silence_start is not None:
            silence_frames = len(is_speech) - silence_start
            if silence_frames >= min_pause_frames:
                boundary_sec = start_sec + silence_start * hop_length / sr
                if boundary_sec > boundaries[-1] + 0.05:
                    boundaries.append(boundary_sec)

        boundaries.append(end_sec)
        return boundaries

    def _split_region_into_sentences(
        self, y: np.ndarray, sr: int, start_sec: float, end_sec: float
    ) -> list[Segment]:
        """把一个语音区间切分为若干句子片段."""
        boundaries = self._find_sentence_boundaries(y, sr, start_sec, end_sec)
        segments: list[Segment] = []
        for i in range(len(boundaries) - 1):
            s = boundaries[i]
            e = boundaries[i + 1]
            # 应用最小/最大时长限制
            duration = e - s
            if duration < self.min_sentence_sec:
                # 太短则合并到下一个边界（如果存在）
                if segments:
                    segments[-1].end = e
                continue
            if duration > self.max_sentence_sec:
                # 太长则在能量最低点强制切分
                sub_segments = self._force_split_long_sentence(y, sr, s, e)
                segments.extend(sub_segments)
            else:
                segments.append(Segment(start=s, end=e))
        return segments

    def _force_split_long_sentence(
        self, y: np.ndarray, sr: int, start_sec: float, end_sec: float
    ) -> list[Segment]:
        """对过长的句子在等分点附近的能量最低处强制切分.

        先按最大句长等分得到目标切点，再在每个切点 ±40% 步长窗口内
        找 RMS 能量谷作为实际切点（兑现“能量最低点切分”的原意）；
        能量谷切点无法满足最小句长约束时回退为等距切分，
        最终仍超长的段在中点补切，保证每段不超过最大句长。
        """
        start_sample = int(start_sec * sr)
        end_sample = int(end_sec * sr)
        region = y[start_sample:end_sample]
        total_sec = end_sec - start_sec
        if len(region) == 0 or total_sec <= self.max_sentence_sec:
            return [Segment(start=start_sec, end=end_sec)]

        n = int(np.ceil(total_sec / self.max_sentence_sec))
        step_sec = total_sec / n
        targets = [start_sec + i * step_sec for i in range(1, n)]

        # 每个等距切点 ±40% 步长窗口内找 RMS 最低帧
        frame_length = int(sr * 0.02)
        hop_length = int(sr * 0.01)
        rms = librosa.feature.rms(y=region, frame_length=frame_length, hop_length=hop_length)[0]
        cuts: list[float] = []
        for target in targets:
            lo_sec = max(start_sec, target - 0.4 * step_sec)
            hi_sec = min(end_sec, target + 0.4 * step_sec)
            lo_frame = int((lo_sec - start_sec) * sr / hop_length)
            hi_frame = min(len(rms) - 1, int((hi_sec - start_sec) * sr / hop_length))
            if hi_frame <= lo_frame:
                cuts.append(target)
                continue
            window_rms = rms[lo_frame : hi_frame + 1]
            valley_offset = int(np.argmin(window_rms))
            # 谷不明显（最低帧能量不低于窗口中位的一半）时退回等分点，
            # 避免在能量平坦的段落里随机偏移
            if window_rms[valley_offset] >= float(np.median(window_rms)) * 0.5:
                cuts.append(target)
            else:
                valley_frame = lo_frame + valley_offset
                cuts.append(start_sec + valley_frame * hop_length / sr)

        # 最小句长校验：切点需离两侧边界足够远且严格递增
        valid: list[float] = [start_sec]
        for cut in cuts:
            if cut - valid[-1] >= self.min_sentence_sec and end_sec - cut >= self.min_sentence_sec:
                valid.append(cut)
        valid.append(end_sec)

        # 有效切点不足（能量谷分布极端）时回退等距切分
        if len(valid) - 1 < n:
            valid = [start_sec] + targets + [end_sec]

        # 后处理：仍超长的段按最大句长补切，保证全部不超长
        final: list[float] = [valid[0]]
        for e in valid[1:]:
            pos = final[-1]
            while e - pos > self.max_sentence_sec:
                pos += self.max_sentence_sec
                final.append(pos)
            final.append(e)

        return [Segment(start=s, end=e) for s, e in zip(final, final[1:])]

    def _merge_short_segments(self, segments: list[Segment]) -> list[Segment]:
        """把间隔很近的相邻短句合并，减少“一句话从中间切开”.

        相邻两句中任一句短于 target_sentence_sec、间隔小于 pause_threshold_sec、
        且合并后不超过 max_sentence_sec 时合并（迭代进行）。
        """
        merged: list[Segment] = []
        for seg in segments:
            if merged:
                prev = merged[-1]
                gap = seg.start - prev.end
                prev_short = prev.end - prev.start < self.target_sentence_sec
                cur_short = seg.end - seg.start < self.target_sentence_sec
                new_dur = seg.end - prev.start
                if (
                    (prev_short or cur_short)
                    and gap < self.pause_threshold_sec
                    and new_dur <= self.max_sentence_sec
                ):
                    prev.end = seg.end
                    continue
            merged.append(seg)
        return merged

    def segment(
        self, audio_path: str | Path, recording_id: str | None = None
    ) -> tuple[list[Segment], list[str], Path]:
        """对音频做句子级切分并持久化.

        Args:
            audio_path: 原始音频路径.
            recording_id: 录音 ID，默认基于音频文件解析路径生成，
                保证不同目录下同名文件互不覆盖.

        Returns:
            (segments, audio_paths, meta_path)
            - segments: 切分后的 Segment 列表，segment_index 已设置.
            - audio_paths: 每个 segment 对应的持久化 WAV 路径.
            - meta_path: meta.json 路径.
        """
        audio_path = Path(audio_path)
        if recording_id is None:
            recording_id = recording_id_from_path(audio_path)

        # 复用 Preprocessor 的降噪流程
        preprocessor = Preprocessor(self.config)
        y, sr = preprocessor.load_denoised(audio_path)

        # 语音区间检测
        speech_intervals = self._detect_speech_intervals(y, sr)
        if not speech_intervals:
            logger.warning("未检测到语音区间: %s", audio_path)
            return [], [], self._meta_path(recording_id)

        # 切分句子
        all_segments: list[Segment] = []
        for start_sec, end_sec in speech_intervals:
            segs = self._split_region_into_sentences(y, sr, start_sec, end_sec)
            all_segments.extend(segs)

        # 相邻短句合并，减少从中间切开
        all_segments = self._merge_short_segments(all_segments)

        # 按时间排序并设置索引
        all_segments.sort(key=lambda s: s.start)
        for idx, seg in enumerate(all_segments):
            seg.segment_index = idx
            seg.recording_id = recording_id

        # 持久化导出
        output_dir = self.segments_dir / recording_id
        output_dir.mkdir(parents=True, exist_ok=True)
        audio_paths: list[str] = []
        for seg in all_segments:
            out_path = output_dir / f"{seg.segment_index:04d}.wav"
            export_segment(
                str(audio_path),
                seg.start - self.padding_sec,
                seg.end + self.padding_sec,
                str(out_path),
                sample_rate=self.sample_rate,
            )
            audio_paths.append(str(out_path))

        # 写 meta.json
        meta = {
            "recording_id": recording_id,
            "original_path": str(audio_path),
            "sample_rate": self.sample_rate,
            "duration_sec": len(y) / sr,
            "processed_at": _utc_now(),
            "segments": [
                {
                    "index": seg.segment_index,
                    "path": path,
                    "start_sec": seg.start,
                    "end_sec": seg.end,
                    "duration_sec": seg.end - seg.start,
                }
                for seg, path in zip(all_segments, audio_paths)
            ],
        }
        meta_path = self._meta_path(recording_id)
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

        return all_segments, audio_paths, meta_path

    def _meta_path(self, recording_id: str) -> Path:
        return self.segments_dir / recording_id / "meta.json"

    def load_segments(self, recording_id: str) -> list[Segment]:
        """从 meta.json 加载已保存的片段列表."""
        meta_path = self._meta_path(recording_id)
        if not meta_path.exists():
            return []
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        segments: list[Segment] = []
        for item in meta.get("segments", []):
            seg = Segment(
                start=item["start_sec"],
                end=item["end_sec"],
                segment_index=item["index"],
                recording_id=recording_id,
            )
            segments.append(seg)
        return segments


def _utc_now() -> str:
    """返回 ISO 格式 UTC 时间字符串."""
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()
