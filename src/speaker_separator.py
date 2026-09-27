"""声纹分离模块：对每句话做初次说话人分类.

基于已注册的用户声纹，对 ``SentenceSegmenter`` 切分出的每个句子片段
提取嵌入并计算余弦相似度，二分输出 ``user`` / ``other`` 标签
（相似度达到阈值判为 user，否则一律 other）。
分类结果同时写入数据库，供后续 ASR 路由和 UI 展示使用。
"""

from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import numpy as np

from .db import Database
from .diarization import DiarizationModule
from .embeddings import extract_embedding
from .enrollment import EnrollmentManager
from .types import Segment

logger = logging.getLogger(__name__)


class SpeakerSeparator:
    """基于声纹的说话人初次分离器."""

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        self.enrollment = EnrollmentManager(config)
        self.diarization = DiarizationModule(config)
        speaker_cfg = config.get("speaker", {})
        self.similarity_threshold = speaker_cfg.get(
            "similarity_threshold",
            config.get("preprocessing", {})
            .get("speaker_filter", {})
            .get("similarity_threshold", 0.75),
        )
        self.low_confidence_threshold = speaker_cfg.get(
            "low_confidence_threshold",
            config.get("preprocessing", {})
            .get("speaker_filter", {})
            .get("low_confidence_threshold", 0.55),
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
        self.segments_dir = Path(config.get("segments_dir", "./data/segments"))
        db_path = config.get("db_path", "./data/db/speaking_analysis.db")
        self.db = Database(db_path)

    def separate(
        self,
        segments: list[Segment],
        recording_id: str,
        voiceprint: dict[str, Any] | None = None,
    ) -> list[Segment]:
        """对片段列表做声纹分类.

        Args:
            segments: 已设置 ``segment_index`` 的 Segment 列表.
            recording_id: 录音 ID.
            voiceprint: 可选的注册声纹；未提供时自动加载.

        Returns:
            原地修改后的 Segment 列表，包含 ``speaker_label``、
            ``speaker_confidence``、``is_user``（``needs_review`` 恒为 False，
            保留字段以兼容旧数据）。
        """
        if voiceprint is None:
            voiceprint = self.enrollment.load_voiceprint()
        if voiceprint is None:
            raise RuntimeError("未找到注册声纹，请先执行注册流程。")

        reference = np.asarray(voiceprint["embedding"], dtype=np.float32)
        reference_norm = float(np.linalg.norm(reference))
        if reference_norm < 1e-8:
            logger.warning("注册声纹为零向量，所有片段标记为 other")
            for seg in segments:
                seg.is_user = False
                seg.speaker_label = "other"
                seg.speaker_confidence = 0.0
                seg.confidence = 0.0
                seg.needs_review = False
            return segments

        def _embed(seg: Segment) -> np.ndarray:
            if seg.segment_index is None:
                return np.zeros(1, dtype=np.float32)
            audio_path = self._segment_audio_path(recording_id, seg.segment_index)
            if not audio_path.exists():
                return np.zeros(1, dtype=np.float32)
            try:
                return extract_embedding(str(audio_path), self.config)
            except Exception as exc:
                logger.warning("提取片段嵌入失败 %s: %s", audio_path, exc)
                return np.zeros(1, dtype=np.float32)

        if self.parallel_workers > 1 and len(segments) > 1:
            with ThreadPoolExecutor(max_workers=self.parallel_workers) as executor:
                embeddings = list(executor.map(_embed, segments))
        else:
            embeddings = [_embed(seg) for seg in segments]

        for seg, seg_emb in zip(segments, embeddings):
            similarity = self.diarization._cosine_similarity(reference, seg_emb)
            seg.speaker_confidence = similarity
            seg.confidence = similarity

            # 二分：达到阈值判为 user，其余一律 other（不需要人工复核档）
            if similarity >= self.similarity_threshold:
                seg.speaker_label = "user"
                seg.is_user = True
            else:
                seg.speaker_label = "other"
                seg.is_user = False
            seg.needs_review = False

        # 保存 diarization.json
        self._save_diarization_json(recording_id, segments)
        # 保存到数据库
        self.db.save_diarization(recording_id, segments)
        return segments

    def _segment_audio_path(self, recording_id: str, segment_index: int) -> Path:
        return self.segments_dir / recording_id / f"{segment_index:04d}.wav"

    def _save_diarization_json(self, recording_id: str, segments: list[Segment]) -> None:
        """把声纹分离结果写入 diarization.json."""
        diarization_path = self.segments_dir / recording_id / "diarization.json"
        diarization_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "recording_id": recording_id,
            "similarity_threshold": self.similarity_threshold,
            "low_confidence_threshold": self.low_confidence_threshold,
            "results": [
                {
                    "segment_index": seg.segment_index,
                    "speaker_label": seg.speaker_label,
                    "confidence": seg.speaker_confidence,
                    "needs_review": seg.needs_review,
                }
                for seg in segments
            ],
        }
        diarization_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def load_diarization(self, recording_id: str) -> list[Segment]:
        """从数据库加载声纹分离结果并构造 Segment 列表.

        历史数据的 needs_review 标签在此归一化为 other（读取层兼容旧数据）.
        """
        rows = self.db.get_diarization(recording_id)
        segments: list[Segment] = []
        for row in rows:
            label = row["speaker_label"]
            if label == "needs_review":
                label = "other"
            seg = Segment(
                start=row.get("start_sec", 0.0),
                end=row.get("end_sec", 0.0),
                segment_index=row["segment_index"],
                recording_id=recording_id,
                speaker_label=label,
                speaker_confidence=row.get("confidence"),
                is_user=label == "user",
                needs_review=False,
            )
            segments.append(seg)
        return segments

    def apply_correction(
        self,
        recording_id: str,
        segment_index: int,
        new_label: str,
        voiceprint: dict[str, Any] | None = None,
    ) -> bool:
        """应用人工校正，只更新当前录音的 diarization 结果.

        声纹的长期更新策略待后续确定，本方法不影响声纹文件。
        """
        if new_label not in ("user", "other"):
            raise ValueError("new_label 必须是 'user' 或 'other'")

        success = self.db.apply_speaker_correction(recording_id, segment_index, new_label)
        if not success:
            return False

        # 同时更新 diarization.json
        segments = self.load_diarization(recording_id)
        for seg in segments:
            if seg.segment_index == segment_index:
                seg.speaker_label = new_label
                seg.is_user = new_label == "user"
                seg.needs_review = False
        self._save_diarization_json(recording_id, segments)
        return True
