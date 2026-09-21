"""ASR 转写（Model API Gateway + faster-whisper 本地回退）."""

from __future__ import annotations

import logging
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import librosa
import soundfile as sf

from .model_api_client import ModelAPIClient
from .types import Segment, Utterance, Word

logger = logging.getLogger(__name__)


class Transcriber:
    """ASR 转写器.

    优先调用 Model API Gateway; 未启用或失败时自动回退到 faster-whisper,
    再不可用时返回占位结果, 保证流水线可继续运行.
    """

    def __init__(
        self, config: dict[str, Any], *, auto_load_model: bool = True
    ) -> None:
        self.config = config
        asr_cfg = config.get("asr", {})
        self.model_name = asr_cfg.get("model", "large-v3")
        self.device = asr_cfg.get("device", "auto")
        self.compute_type = asr_cfg.get("compute_type", "int8")
        self.language = asr_cfg.get("language", "zh")
        self.beam_size = asr_cfg.get("beam_size", 5)
        self.vad_filter = asr_cfg.get("vad_filter", True)
        self.sample_rate = config.get("segmentation", {}).get("target_sample_rate", 16000)
        self.parallel_workers = max(
            1, int(config.get("segmentation", {}).get("parallel_workers", 1))
        )
        self.model: Any | None = None
        self.api_client = ModelAPIClient(config)

        # 只有 API 不可用时才提前加载本地模型
        if auto_load_model and not self.api_client.asr_available:
            self._load_local_model()

    def _load_local_model(self) -> None:
        try:
            from faster_whisper import WhisperModel

            self.model = WhisperModel(
                self.model_name,
                device=self.device,
                compute_type=self.compute_type,
            )
            logger.info("已加载 faster-whisper 模型: %s", self.model_name)
        except Exception as exc:  # pragma: no cover - 重型依赖缺失时回退
            logger.warning(
                "无法加载 faster-whisper 模型（%s），ASR 将使用占位结果。错误: %s",
                self.model_name,
                exc,
            )
            self.model = None

    def transcribe_user_segments(
        self, audio_path: Path, user_segments: list[Segment]
    ) -> list[Utterance]:
        """对用户语音片段进行转写，返回带词级时间戳的句子列表."""
        if not user_segments:
            return []

        merged_segments = self._merge_segments(user_segments)

        # 1) 优先 API
        if self.api_client.asr_available:
            try:
                return self._transcribe_with_api(audio_path, merged_segments)
            except Exception as exc:
                logger.warning("ASR API 调用失败，回退本地模型: %s", exc)

        # 2) 本地 faster-whisper（仅在初始化时已加载才使用）
        if self.model is None:
            return self._fallback_transcription(merged_segments)

        if self.parallel_workers > 1 and len(merged_segments) > 1:
            with ThreadPoolExecutor(max_workers=self.parallel_workers) as executor:
                batch = list(
                    executor.map(
                        lambda seg: self._transcribe_cropped_segment(audio_path, seg),
                        merged_segments,
                    )
                )
        else:
            batch = [
                self._transcribe_cropped_segment(audio_path, seg)
                for seg in merged_segments
            ]

        utterances: list[Utterance] = []
        for item in batch:
            utterances.extend(item)
        return utterances

    def _transcribe_with_api(
        self, audio_path: Path, merged_segments: list[Segment]
    ) -> list[Utterance]:
        """裁剪合并后的用户片段并调用 Gateway ASR（支持并行）."""

        def _transcribe_one(seg: Segment) -> list[Utterance]:
            tmp_path = self._crop_to_wav(audio_path, seg)
            if tmp_path is None:
                return []
            try:
                api_utterances = self.api_client.transcribe(
                    tmp_path, language=None if self.language == "auto" else self.language
                )
                for utt in api_utterances:
                    utt.start += seg.start
                    utt.end += seg.start
                    for w in utt.words:
                        w.start += seg.start
                        w.end += seg.start
                return api_utterances
            finally:
                try:
                    tmp_path.unlink()
                except OSError:
                    pass

        if self.parallel_workers > 1 and len(merged_segments) > 1:
            with ThreadPoolExecutor(max_workers=self.parallel_workers) as executor:
                batch = list(executor.map(_transcribe_one, merged_segments))
        else:
            batch = [_transcribe_one(seg) for seg in merged_segments]

        utterances: list[Utterance] = []
        for item in batch:
            utterances.extend(item)
        return utterances

    def _merge_segments(
        self, segments: list[Segment], gap_sec: float = 0.5
    ) -> list[Segment]:
        """合并间隔较小的相邻用户片段，减少模型调用次数."""
        sorted_segments = sorted(segments, key=lambda s: s.start)
        merged: list[Segment] = []
        for seg in sorted_segments:
            if not merged or seg.start > merged[-1].end + gap_sec:
                merged.append(Segment(start=seg.start, end=seg.end))
            else:
                merged[-1].end = max(merged[-1].end, seg.end)
        return merged

    def _crop_to_wav(self, audio_path: Path, segment: Segment) -> Path | None:
        """将音频区间裁剪为临时 WAV 文件."""
        duration = segment.end - segment.start
        if duration <= 0:
            return None
        try:
            y, _ = librosa.load(
                str(audio_path),
                sr=self.sample_rate,
                mono=True,
                offset=segment.start,
                duration=duration,
            )
        except Exception as exc:
            logger.warning(
                "裁剪音频失败 %s [%s-%s]: %s",
                audio_path,
                segment.start,
                segment.end,
                exc,
            )
            return None
        if len(y) == 0:
            return None
        tmp_path = Path(tempfile.mktemp(suffix=".wav"))
        sf.write(str(tmp_path), y, self.sample_rate)
        return tmp_path

    def _transcribe_cropped_segment(
        self, audio_path: Path, segment: Segment
    ) -> list[Utterance]:
        """裁剪出单个用户语音区间并调用 faster-whisper 转写."""
        tmp_path = self._crop_to_wav(audio_path, segment)
        if tmp_path is None:
            return []
        try:
            return self._run_model(str(tmp_path), offset=segment.start)
        finally:
            try:
                tmp_path.unlink()
            except OSError:
                pass

    def _run_model(self, audio_path: str, offset: float = 0.0) -> list[Utterance]:
        """调用 faster-whisper 并将结果映射为项目类型."""
        assert self.model is not None

        # TODO: 中英混合场景下可将 language 设为 None，由模型自动检测
        language = None if self.language in (None, "auto") else self.language
        segments, _info = self.model.transcribe(
            audio_path,
            language=language,
            word_timestamps=True,
            beam_size=self.beam_size,
            vad_filter=self.vad_filter,
        )

        utterances: list[Utterance] = []
        for seg in segments:
            text = seg.text.strip()
            if not text:
                continue

            words: list[Word] = []
            if getattr(seg, "words", None):
                for w in seg.words:
                    word_text = getattr(w, "word", "").strip()
                    if not word_text:
                        continue
                    confidence = getattr(w, "probability", None)
                    words.append(
                        Word(
                            text=word_text,
                            start=w.start + offset,
                            end=w.end + offset,
                            confidence=confidence,
                        )
                    )
            else:
                # 未开启词级时间戳时的兜底：整句作为一个词
                words.append(
                    Word(
                        text=text,
                        start=seg.start + offset,
                        end=seg.end + offset,
                        confidence=None,
                    )
                )

            utterances.append(
                Utterance(
                    text=text,
                    start=seg.start + offset,
                    end=seg.end + offset,
                    words=words,
                )
            )
        return utterances

    def _fallback_transcription(self, merged_segments: list[Segment]) -> list[Utterance]:
        """ASR 模型不可用时返回占位结果，保持下游分析可继续运行."""
        logger.warning("ASR 模型未加载，返回占位转写结果。")
        result: list[Utterance] = []
        for seg in merged_segments:
            result.append(
                Utterance(
                    text="占位转写文本（ASR 模型未加载）",
                    start=seg.start,
                    end=seg.end,
                    words=[
                        Word(
                            text="占位转写文本",
                            start=seg.start,
                            end=seg.end,
                            confidence=None,
                        )
                    ],
                )
            )
        return result
