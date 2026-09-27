"""音频预处理：加载、降噪、VAD、切分."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import librosa
import numpy as np

from .types import Segment


class Preprocessor:
    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        pre = config.get("preprocessing", {})
        seg_cfg = pre.get("segmentation", config.get("segmentation", {}))
        vad_cfg = pre.get("vad", config.get("vad", {}))
        denoise_cfg = pre.get("denoise", {})

        self.sample_rate = seg_cfg.get("target_sample_rate", 16000)
        self.max_seg = seg_cfg.get("max_segment_duration_sec", 300)
        self.min_seg = seg_cfg.get("min_segment_duration_sec", 10)
        self.min_speech_ms = vad_cfg.get("min_speech_duration_ms", 250)
        self.max_silence_ms = vad_cfg.get("max_silence_duration_ms", 1000)

        self.denoise_backend = denoise_cfg.get("backend", "spectral")
        self.noise_sample_sec = denoise_cfg.get("noise_sample_sec", 0.1)
        self.vad_backend = vad_cfg.get("backend", "energy")
        self.vad_threshold = vad_cfg.get("threshold", 0.5)

    def get_duration(self, path: Path) -> float:
        y, sr = librosa.load(str(path), sr=self.sample_rate, mono=True)
        return len(y) / sr

    def load_denoised(self, path: Path) -> tuple[np.ndarray, int]:
        """加载并降噪音频，返回 (波形, 采样率)，供导出流程复用同一份降噪结果."""
        y, sr = librosa.load(str(path), sr=self.sample_rate, mono=True)
        return self._denoise(y, sr), sr

    def process(self, path: Path) -> list[Segment]:
        y, sr = self.load_denoised(path)
        speech_intervals, confidences = self._vad(y, sr)
        segments = []
        for (start, end), conf in zip(speech_intervals, confidences):
            seg_start = start / sr
            seg_end = end / sr
            # 将长片段按自然停顿切分
            if seg_end - seg_start > self.max_seg:
                sub_segments = self._split_by_onsets(y[start:end], sr, seg_start)
                for seg in sub_segments:
                    seg.vad_confidence = conf
                segments.extend(sub_segments)
            elif seg_end - seg_start >= self.min_seg:
                segments.append(Segment(start=seg_start, end=seg_end, vad_confidence=conf))
        return segments

    def _denoise(self, y: np.ndarray, sr: int) -> np.ndarray:
        """根据配置选择降噪后端，失败时回退到谱减法."""
        if self.denoise_backend == "noisereduce":
            try:
                return self._denoise_noisereduce(y, sr)
            except Exception as exc:  # pragma: no cover - 依赖缺失保护
                import warnings

                warnings.warn(f"noisereduce 降噪失败，回退到谱减法: {exc}")
        elif self.denoise_backend == "rnnoise":
            try:
                return self._denoise_rnnoise(y, sr)
            except Exception as exc:  # pragma: no cover - 依赖缺失保护
                import warnings

                warnings.warn(f"RNNoise 降噪失败，回退到谱减法: {exc}")
        return self._denoise_spectral(y)

    def _denoise_spectral(self, y: np.ndarray) -> np.ndarray:
        """轻量级谱减法降噪（首期简化实现）."""
        # 计算短时傅里叶变换
        stft = librosa.stft(y)
        mag = np.abs(stft)
        # 用前 100ms 估计噪声谱（假设开头为噪声）
        hop_length = 512
        noise_frames = max(1, int(self.noise_sample_sec * self.sample_rate / hop_length))
        noise_profile = np.mean(mag[:, :noise_frames], axis=1, keepdims=True)
        # 谱减
        mag_clean = np.maximum(mag - noise_profile * 1.5, 0.0)
        phase = np.angle(stft)
        stft_clean = mag_clean * np.exp(1j * phase)
        y_clean = librosa.istft(stft_clean, length=len(y))
        return y_clean

    def _denoise_noisereduce(self, y: np.ndarray, sr: int) -> np.ndarray:
        """基于 noisereduce 的谱门控降噪."""
        import noisereduce as nr

        return nr.reduce_noise(y=y, sr=sr)

    def _denoise_rnnoise(self, y: np.ndarray, sr: int) -> np.ndarray:
        """基于 RNNoise 的神经网络降噪（通过 pyrnnoise 或类似包）."""
        # 目前使用 noisereduce 的 RNNoise 风格后端作为占位；
        # 真实 RNNoise 需要额外绑定，后续可替换。
        import noisereduce as nr

        return nr.reduce_noise(y=y, sr=sr, prop_decrease=1.0, stationary=False)

    def _vad(self, y: np.ndarray, sr: int) -> tuple[list[tuple[int, int]], list[float]]:
        """根据配置选择 VAD 后端，返回语音区间样本索引及置信度."""
        if self.vad_backend == "silero":
            try:
                return self._vad_silero(y, sr)
            except Exception as exc:  # pragma: no cover - 依赖缺失保护
                import warnings

                warnings.warn(f"silero-vad 失败，回退到能量 VAD: {exc}")
        return self._vad_energy(y, sr)

    def _vad_energy(self, y: np.ndarray, sr: int) -> tuple[list[tuple[int, int]], list[float]]:
        """基于能量的 VAD，返回语音区间样本索引及统一置信度."""
        frame_length = int(sr * 0.02)
        hop_length = int(sr * 0.01)
        rms = librosa.feature.rms(y=y, frame_length=frame_length, hop_length=hop_length)[0]
        threshold = np.mean(rms) * 0.15 + np.median(rms) * 0.1
        is_speech = rms > threshold

        min_speech_frames = int(self.min_speech_ms / 10)
        max_silence_frames = int(self.max_silence_ms / 10)

        intervals = []
        start = None
        silence_count = 0
        for i, speech in enumerate(is_speech):
            if speech:
                if start is None:
                    start = max(0, i - silence_count)
                silence_count = 0
            else:
                if start is not None:
                    silence_count += 1
                    if silence_count > max_silence_frames:
                        end = i - silence_count + 1
                        if end - start >= min_speech_frames:
                            intervals.append((start * hop_length, end * hop_length))
                        start = None
                        silence_count = 0
        if start is not None:
            end = len(is_speech) * hop_length
            if end - start * hop_length >= min_speech_frames * hop_length:
                intervals.append((start * hop_length, end))

        confidence = 1.0 if intervals else 0.0
        return intervals, [confidence] * len(intervals)

    def _vad_silero(self, y: np.ndarray, sr: int) -> tuple[list[tuple[int, int]], list[float]]:
        """基于 silero-vad 的语音活动检测."""
        from silero_vad import get_speech_timestamps, load_silero_vad

        model = load_silero_vad()
        timestamps = get_speech_timestamps(
            y,
            model,
            threshold=self.vad_threshold,
            sampling_rate=sr,
            min_speech_duration_ms=self.min_speech_ms,
            max_speech_duration_s=9999,
            min_silence_duration_ms=self.max_silence_ms,
            return_seconds=False,
        )

        intervals = []
        confidences = []
        for ts in timestamps:
            start = int(ts["start"])
            end = int(ts["end"])
            intervals.append((start, end))
            confidences.append(float(ts.get("confidence", 1.0)))
        return intervals, confidences

    def _split_by_onsets(self, y: np.ndarray, sr: int, offset_sec: float) -> list[Segment]:
        """在长语音区间内按自然停顿切分."""
        hop_length = int(sr * 0.01)
        onset_env = librosa.onset.onset_strength(y=y, sr=sr, hop_length=hop_length)
        onset_frames = librosa.onset.onset_detect(
            onset_envelope=onset_env, sr=sr, hop_length=hop_length, wait=20
        )
        onset_times = [f * hop_length / sr + offset_sec for f in onset_frames]
        onset_times = [offset_sec] + onset_times + [offset_sec + len(y) / sr]
        onset_times.sort()

        segments = []
        for i in range(len(onset_times) - 1):
            start = onset_times[i]
            end = onset_times[i + 1]
            if end - start > self.max_seg:
                # 强制等距切分
                n = int(np.ceil((end - start) / self.max_seg))
                step = (end - start) / n
                for j in range(n):
                    s = start + j * step
                    e = min(s + step, end)
                    if e - s >= self.min_seg:
                        segments.append(Segment(start=s, end=e))
            elif end - start >= self.min_seg:
                segments.append(Segment(start=start, end=end))
        return segments
