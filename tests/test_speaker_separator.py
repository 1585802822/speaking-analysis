"""声纹分离模块测试."""

from __future__ import annotations

import numpy as np
import pytest
import soundfile as sf

from src.speaker_separator import SpeakerSeparator
from src.types import Segment


def _create_wav(path, duration_sec=2.0, sr=16000):
    """生成一个带轻微噪声的测试 WAV."""
    y = np.random.normal(0, 0.01, int(duration_sec * sr)).astype(np.float32)
    sf.write(str(path), y, sr)


@pytest.fixture
def config(tmp_path):
    return {
        "input_dir": str(tmp_path / "input"),
        "output_dir": str(tmp_path / "output"),
        "voiceprint_dir": str(tmp_path / "voiceprint"),
        "segments_dir": str(tmp_path / "segments"),
        "db_path": str(tmp_path / "test.db"),
        "speaker": {
            "similarity_threshold": 0.75,
            "low_confidence_threshold": 0.55,
        },
        "preprocessing": {
            "segmentation": {"parallel_workers": 1},
        },
    }


def _make_segment(start, end, idx, rec_id):
    return Segment(
        start=start,
        end=end,
        segment_index=idx,
        recording_id=rec_id,
    )


def _embedding_with_similarity(voiceprint, similarity):
    """构造一个与 voiceprint 具有指定余弦相似度的向量."""
    reference = voiceprint["embedding"]
    # 构造一个与 reference 正交的单位向量
    orth = np.zeros_like(reference)
    orth[0] = 1.0
    orth = orth - np.dot(orth, reference) * reference
    norm = np.linalg.norm(orth)
    if norm < 1e-8:
        orth = np.zeros_like(reference)
        orth[1] = 1.0
        orth = orth - np.dot(orth, reference) * reference
        norm = np.linalg.norm(orth)
    orth = orth / norm
    # 组合后归一化
    emb = similarity * reference + np.sqrt(1 - similarity**2) * orth
    return emb / np.linalg.norm(emb)


def test_separate_classifies_user_and_other(config, tmp_path, monkeypatch):
    """模拟嵌入：第一个片段与用户声纹完全一致，第二个相似度 0.6（other）."""
    segments_dir = tmp_path / "segments" / "rec1"
    segments_dir.mkdir(parents=True)
    for idx in range(2):
        _create_wav(segments_dir / f"{idx:04d}.wav")

    segments = [
        _make_segment(0.0, 1.0, 0, "rec1"),
        _make_segment(1.5, 2.5, 1, "rec1"),
    ]

    voiceprint = {"embedding": np.ones(192, dtype=np.float32) / np.linalg.norm(np.ones(192))}

    def fake_extract(path, cfg):
        if "0000.wav" in str(path):
            return voiceprint["embedding"]
        return _embedding_with_similarity(voiceprint, 0.6)

    monkeypatch.setattr("src.speaker_separator.extract_embedding", fake_extract)

    separator = SpeakerSeparator(config)
    result = separator.separate(segments, "rec1", voiceprint)

    assert result[0].speaker_label == "user"
    assert result[1].speaker_label == "other"


def test_separate_low_similarity_is_other(config, tmp_path, monkeypatch):
    """相似度低于阈值的一律归为 other（二分，不再产生 needs_review）."""
    segments_dir = tmp_path / "segments" / "rec1"
    segments_dir.mkdir(parents=True)
    _create_wav(segments_dir / "0000.wav")

    segments = [_make_segment(0.0, 1.0, 0, "rec1")]
    voiceprint = {"embedding": np.ones(192, dtype=np.float32) / np.linalg.norm(np.ones(192))}

    def fake_extract(path, cfg):
        # 相似度 0.5，低于 similarity_threshold 0.75
        return _embedding_with_similarity(voiceprint, 0.5)

    monkeypatch.setattr("src.speaker_separator.extract_embedding", fake_extract)

    separator = SpeakerSeparator(config)
    result = separator.separate(segments, "rec1", voiceprint)

    assert result[0].speaker_label == "other"
    assert result[0].needs_review is False


def test_apply_correction_updates_label(config, tmp_path, monkeypatch):
    segments_dir = tmp_path / "segments" / "rec1"
    segments_dir.mkdir(parents=True)
    _create_wav(segments_dir / "0000.wav")

    segments = [_make_segment(0.0, 1.0, 0, "rec1")]
    voiceprint = {"embedding": np.ones(192, dtype=np.float32) / np.linalg.norm(np.ones(192))}

    def fake_extract(path, cfg):
        return voiceprint["embedding"]

    monkeypatch.setattr("src.speaker_separator.extract_embedding", fake_extract)

    separator = SpeakerSeparator(config)
    # 先把片段写入数据库，模拟真实流程
    separator.db.save_recording("rec1", str(segments_dir / "0000.wav"), 2.0)
    separator.db.save_segments("rec1", segments, [str(segments_dir / "0000.wav")])
    separator.separate(segments, "rec1", voiceprint)

    success = separator.apply_correction("rec1", 0, "other")
    assert success is True

    loaded = separator.load_diarization("rec1")
    assert loaded[0].speaker_label == "other"
    assert loaded[0].is_user is False
