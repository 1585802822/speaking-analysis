"""ASR 转写：user 句优先走 ASR API，失败回退本地模型；other 句用本地 faster-whisper."""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from .audio_adapter import crop_for_api
from .model_api_client import ModelAPIClient
from .types import Segment, SegmentTranscription, Utterance, Word

logger = logging.getLogger(__name__)


class Transcriber:
    """ASR 转写器.

    user 句优先走 ASR API（讯飞或统一网关），失败或空结果时回退本地模型；
    other 句直接使用本地 faster-whisper。
    本地模型按需懒加载：首次需要本地转写时才加载，服务启动不被大模型拖慢。
    """

    def __init__(self, config: dict[str, Any], *, auto_load_model: bool = True) -> None:
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
        self._local_model_attempted = False
        self.api_client = ModelAPIClient(config)

        # API 未启用时提前加载本地模型（如旧版 CLI 流程）；API 启用时走懒加载
        if auto_load_model and not self.api_client.enabled:
            self._ensure_local_model()

    def _ensure_local_model(self) -> None:
        """懒加载本地模型：只尝试加载一次，失败后走占位回退."""
        if self.model is not None or self._local_model_attempted:
            return
        self._local_model_attempted = True
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

        # 1) API 启用时必须走 API, 失败直接抛出异常（不降级）
        if self.api_client.enabled:
            if not self.api_client.asr_available:
                raise RuntimeError(
                    "API 已启用但 ASR 未正确配置（缺少讯飞 app_id/api_secret 或网关 endpoint），"
                    "请检查 .env 或 config.yaml 后重试。"
                )
            return self._transcribe_with_api(audio_path, merged_segments)

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
            batch = [self._transcribe_cropped_segment(audio_path, seg) for seg in merged_segments]

        utterances: list[Utterance] = []
        for item in batch:
            utterances.extend(item)
        return utterances

    def transcribe_segments(
        self,
        audio_path: Path,
        segments: list[Segment],
        recording_id: str,
    ) -> list[SegmentTranscription]:
        """按说话人标签为每个句子片段选择 ASR 引擎并转写.

        - ``user`` 片段优先使用 API ASR（付费、准确率高），失败或空结果时回退本地模型
        - ``other`` 片段使用本地 faster-whisper（首次使用时懒加载）
        - 每个片段单独转写，保持单句 ↔ 文本一一对应
        """
        if not segments:
            return []

        results: list[SegmentTranscription] = []
        for seg in segments:
            if seg.segment_index is None or seg.speaker_label is None:
                continue

            use_api = seg.speaker_label == "user"
            transcriptions, error = self._transcribe_one_segment(audio_path, seg, use_api=use_api)
            asr_source = "api" if use_api else "local"

            if not transcriptions and use_api:
                # user 句 API 失败/空结果时回退本地模型再试一次
                api_error = error
                transcriptions, local_error = self._transcribe_one_segment(
                    audio_path, seg, use_api=False
                )
                asr_source = "local"
                error = "；".join(e for e in (api_error, local_error) if e) or None

            if not transcriptions:
                results.append(
                    SegmentTranscription(
                        recording_id=recording_id,
                        segment_index=seg.segment_index,
                        speaker_label=seg.speaker_label,
                        asr_source=asr_source,
                        audio_path=str(audio_path),
                        start=seg.start,
                        end=seg.end,
                        text="",
                        status="failed",
                        error_message=error or "转写结果为空",
                    )
                )
                continue

            # 合并同一片段内可能返回的多个 utterance（通常只有一个）
            text = " ".join(t.text for t in transcriptions).strip()
            words: list[Word] = []
            for t in transcriptions:
                words.extend(t.words)

            results.append(
                SegmentTranscription(
                    recording_id=recording_id,
                    segment_index=seg.segment_index,
                    speaker_label=seg.speaker_label,
                    asr_source=asr_source,
                    audio_path=str(audio_path),
                    start=seg.start,
                    end=seg.end,
                    text=text,
                    words=words,
                    error_message=error,
                )
            )

        return results

    def _transcribe_one_segment(
        self, audio_path: Path, segment: Segment, use_api: bool
    ) -> tuple[list[Utterance], str | None]:
        """转写单个片段，返回 ``(utterances, error_message)``.

        失败不抛异常：错误信息随返回值带出，由调用方决定是否回退.
        """
        tmp_path = self._crop_to_wav(audio_path, segment)
        if tmp_path is None:
            return [], "音频裁剪失败"
        try:
            if use_api:
                if not self.api_client.asr_available:
                    return [], "API ASR 未配置"
                utterances = self.api_client.transcribe(
                    tmp_path, language=None if self.language == "auto" else self.language
                )
                if not utterances:
                    return [], "API 转写结果为空"
                return utterances, None
            else:
                self._ensure_local_model()
                if self.model is None:
                    # 本地模型不可用时返回占位文本，保持流程不中断
                    return self._fallback_transcription([segment]), "本地 ASR 模型未加载"
                utterances = self._run_model(str(tmp_path), offset=0.0)
                if not utterances:
                    return [], "本地转写结果为空"
                return utterances, None
        except Exception as exc:
            logger.warning("片段 %s 转写失败: %s", segment.segment_index, exc)
            return [], f"转写异常: {exc}"
        finally:
            try:
                tmp_path.unlink()
            except OSError:
                pass

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

    def _merge_segments(self, segments: list[Segment], gap_sec: float = 0.5) -> list[Segment]:
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
        """将音频区间裁剪为 API 要求的临时 WAV 文件（16kHz 单声道）."""
        return crop_for_api(
            audio_path,
            segment.start,
            segment.end,
            target_sr=self.sample_rate,
        )

    def _transcribe_cropped_segment(self, audio_path: Path, segment: Segment) -> list[Utterance]:
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
