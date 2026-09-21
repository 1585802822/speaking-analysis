"""音频片段过滤：目标说话人筛选与低置信度标记."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import numpy as np

from .embeddings import extract_embedding_from_array
from .types import Segment


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
    seg: Segment,
    audio: np.ndarray,
    sr: int,
    config: dict[str, Any],
) -> np.ndarray:
    """从已加载音频数组中提取指定片段的嵌入向量."""
    start_sample = int(seg.start * sr)
    end_sample = int(seg.end * sr)
    start_sample = max(0, min(start_sample, len(audio)))
    end_sample = max(0, min(end_sample, len(audio)))
    if end_sample <= start_sample:
        return np.zeros(1, dtype=np.float32)
    return extract_embedding_from_array(audio[start_sample:end_sample], sr, config)


def mark_low_confidence(
    segments: list[Segment], low_confidence_threshold: float
) -> list[Segment]:
    """标记置信度低于阈值的片段需要人工复核."""
    for seg in segments:
        conf = seg.speaker_confidence if seg.speaker_confidence is not None else seg.confidence
        if conf is not None and conf < low_confidence_threshold:
            seg.needs_review = True
    return segments


def filter_target_speaker(
    segments: list[Segment],
    audio: np.ndarray,
    sr: int,
    enroll_embedding: np.ndarray,
    config: dict[str, Any],
    similarity_threshold: float,
    low_confidence_threshold: float | None = None,
    parallel_workers: int = 1,
) -> list[Segment]:
    """保留声纹相似度高于阈值的目标说话人片段，并标记低置信度片段.

    Args:
        segments: 预处理得到的音频片段列表.
        audio: 已加载的单声道音频数组.
        sr: 音频采样率.
        enroll_embedding: 注册声纹嵌入向量.
        config: 项目配置.
        similarity_threshold: 判定为目标说话人的相似度阈值.
        low_confidence_threshold: 低置信度阈值，低于此值标记 needs_review.
        parallel_workers: 并行提取嵌入的工作线程数.

    Returns:
        被判定为目标说话人的片段列表（原地修改传入的 Segment 元数据）.
    """
    reference = np.asarray(enroll_embedding, dtype=np.float32)
    reference_norm = float(np.linalg.norm(reference))
    if reference_norm < 1e-8:
        for seg in segments:
            seg.is_user = False
            seg.speaker_label = "unknown"
            seg.speaker_confidence = 0.0
            seg.confidence = 0.0
        return []

    def _embed(seg: Segment) -> np.ndarray:
        return _extract_segment_embedding(seg, audio, sr, config)

    if parallel_workers > 1 and len(segments) > 1:
        with ThreadPoolExecutor(max_workers=parallel_workers) as executor:
            embeddings = list(executor.map(_embed, segments))
    else:
        embeddings = [_embed(seg) for seg in segments]

    results = []
    for seg, seg_emb in zip(segments, embeddings):
        try:
            similarity = _cosine_similarity(reference, seg_emb)
        except Exception:
            similarity = (low_confidence_threshold or 0.0) - 0.05

        is_user = similarity >= similarity_threshold
        seg.is_user = is_user
        seg.speaker_label = "user" if is_user else "other"
        seg.speaker_confidence = similarity
        seg.confidence = similarity

        if low_confidence_threshold is not None and similarity < low_confidence_threshold:
            seg.needs_review = True

        if is_user:
            results.append(seg)

    return results
