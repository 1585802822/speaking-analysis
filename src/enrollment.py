"""声纹注册与管理."""

from __future__ import annotations

import json
import pickle
from pathlib import Path
from typing import Any

import numpy as np

from .embeddings import extract_embedding, extract_speaker_center


class EnrollmentManager:
    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        self.voiceprint_dir = Path(config["voiceprint_dir"])
        self.voiceprint_dir.mkdir(parents=True, exist_ok=True)
        self.embedding_path = self.voiceprint_dir / "embedding.pkl"
        self.meta_path = self.voiceprint_dir / "meta.json"

    def enroll(self, audio_path: str) -> None:
        """提取并保存用户声纹嵌入(单文件, 兼容旧流程)."""
        embedding = self._extract_embedding(audio_path)
        voiceprint = {
            "embedding": embedding,
            "samples": [str(audio_path)],
            "positive_samples": [],
            "negative_samples": [],
            "model": self._current_model_name(),
            "chunk_count": 1,
        }
        with self.embedding_path.open("wb") as f:
            pickle.dump(voiceprint, f)
        meta = {
            "enrolled": True,
            "samples": [str(audio_path)],
            "feedback_history": [],
        }
        with self.meta_path.open("w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
        print(f"声纹已保存到 {self.embedding_path}")

    def enroll_multi(self, audio_paths: list[str]) -> None:
        """用多个注册音频提取声纹中心并保存.

        对每个音频先做能量 VAD 裁剪再分块取嵌入, 块均值作为声纹中心,
        避免整段嵌入被开头/尾部静音污染.
        """
        center, chunk_count = extract_speaker_center(audio_paths, self.config)
        voiceprint = {
            "embedding": center,
            "samples": [str(p) for p in audio_paths],
            "positive_samples": [],
            "negative_samples": [],
            "model": self._current_model_name(),
            "chunk_count": chunk_count,
        }
        with self.embedding_path.open("wb") as f:
            pickle.dump(voiceprint, f)
        meta = {
            "enrolled": True,
            "samples": [str(p) for p in audio_paths],
            "feedback_history": [],
            "chunk_count": chunk_count,
        }
        with self.meta_path.open("w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
        print(
            f"声纹已用 {len(audio_paths)} 个文件({chunk_count} 个有效块)"
            f"保存到 {self.embedding_path}"
        )

    @staticmethod
    def _current_model_name() -> str:
        """当前生效的说话人嵌入模型标识."""
        from . import embeddings as emb

        if emb._ECAPA_CLASSIFIER:
            return "ecapa"
        return "mfcc-fallback"

    def load_voiceprint(self) -> dict[str, Any] | None:
        if not self.embedding_path.exists():
            return None
        with self.embedding_path.open("rb") as f:
            return pickle.load(f)

    def update_voiceprint(
        self,
        positive_samples: list[str],
        negative_samples: list[str] | None = None,
    ) -> None:
        """增量更新声纹中心.

        正面样本拉近中心, 负面样本推远中心. 真实 embedding 由 speechbrain/pyannote 提供,
        不可用时回退到本地 MFCC 统计特征.
        """
        voiceprint = self.load_voiceprint()
        if voiceprint is None:
            raise RuntimeError("未找到注册声纹")

        center = np.asarray(voiceprint["embedding"], dtype=np.float32)
        speaker_cfg = self.config.get("speaker", {})
        positive_lr = float(speaker_cfg.get("positive_lr", 0.25))
        negative_lr = float(speaker_cfg.get("negative_lr", 0.15))

        if positive_samples:
            pos_embs = np.stack(
                [self._extract_embedding(p) for p in positive_samples]
            )
            pos_mean = pos_embs.mean(axis=0)
            center = center + positive_lr * (pos_mean - center)

        negative_samples = negative_samples or []
        if negative_samples:
            neg_embs = np.stack(
                [self._extract_embedding(p) for p in negative_samples]
            )
            neg_mean = neg_embs.mean(axis=0)
            # 将中心推离负面样本均值, 同时保持单位长度
            push = center - negative_lr * (neg_mean - center)
            center = push

        norm = np.linalg.norm(center) + 1e-8
        voiceprint["embedding"] = (center / norm).astype(np.float32)
        voiceprint.setdefault("positive_samples", []).extend(positive_samples)
        voiceprint.setdefault("negative_samples", []).extend(negative_samples)

        with self.embedding_path.open("wb") as f:
            pickle.dump(voiceprint, f)

        meta = {"enrolled": True, "samples": [], "feedback_history": []}
        if self.meta_path.exists():
            try:
                meta = json.loads(self.meta_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                pass
        meta.setdefault("feedback_history", []).append(
            {
                "positive": [str(p) for p in positive_samples],
                "negative": [str(n) for n in negative_samples],
            }
        )
        with self.meta_path.open("w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)

    def _extract_embedding(self, audio_path: str) -> np.ndarray:
        """提取单条音频的嵌入."""
        return extract_embedding(audio_path, self.config)
