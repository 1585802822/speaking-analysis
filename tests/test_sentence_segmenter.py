"""句子级切分模块测试."""

from __future__ import annotations

import numpy as np
import pytest
import soundfile as sf

from src.sentence_segmenter import SentenceSegmenter
from src.types import Segment


def _create_test_wav(path, segments, sr=16000, noise_factor=0.005):
    """生成包含指定语音段的测试 WAV.

    segments: list of (start_sec, end_sec) 语音区间.
    """
    total_duration = max(end for _start, end in segments) + 1.0
    y = np.random.normal(0, noise_factor, int(total_duration * sr)).astype(np.float32)
    for start, end in segments:
        start_sample = int(start * sr)
        end_sample = int(end * sr)
        # 用 300 Hz 正弦波模拟语音，较高振幅以减少噪声造成的伪停顿
        t = np.arange(end_sample - start_sample) / sr
        y[start_sample:end_sample] += 0.8 * np.sin(2 * np.pi * 300 * t)
    y = np.clip(y, -1.0, 1.0)
    sf.write(str(path), y, sr)


@pytest.fixture
def config(tmp_path):
    return {
        "input_dir": str(tmp_path / "input"),
        "output_dir": str(tmp_path / "output"),
        "voiceprint_dir": str(tmp_path / "voiceprint"),
        "segments_dir": str(tmp_path / "segments"),
        "preprocessing": {
            "denoise": {"backend": "spectral"},
            "vad": {
                "backend": "energy",
                "min_speech_duration_ms": 100,
                "max_silence_duration_ms": 500,
                "threshold": 0.5,
            },
            "segmentation": {"target_sample_rate": 16000},
        },
        "sentence_segmentation": {
            "target_sample_rate": 16000,
            "min_sentence_sec": 0.5,
            "max_sentence_sec": 15.0,
            "pause_threshold_sec": 0.7,
            "min_pause_sec": 0.2,
            "target_sentence_sec": 2.0,
            "padding_sec": 0.05,
        },
    }


def test_segmenter_splits_two_sentences(tmp_path, config):
    wav = tmp_path / "two_sentences.wav"
    # 两个 1 秒语音段，中间间隔 0.8 秒
    _create_test_wav(wav, [(0.5, 1.5), (2.3, 3.3)])

    segmenter = SentenceSegmenter(config)
    segments, audio_paths, meta_path = segmenter.segment(wav, "rec1")

    assert len(segments) == 2
    assert len(audio_paths) == 2
    assert meta_path.exists()
    assert segments[0].segment_index == 0
    assert segments[1].segment_index == 1


def test_segmenter_returns_empty_for_silent_audio(tmp_path, config):
    wav = tmp_path / "silent.wav"
    y = np.zeros(int(2.0 * 16000), dtype=np.float32)
    sf.write(str(wav), y, 16000)

    segmenter = SentenceSegmenter(config)
    segments, audio_paths, meta_path = segmenter.segment(wav, "rec2")

    assert segments == []
    assert audio_paths == []


def test_load_segments_from_meta(tmp_path, config):
    wav = tmp_path / "load_test.wav"
    _create_test_wav(wav, [(0.5, 1.5), (2.3, 3.3)])

    segmenter = SentenceSegmenter(config)
    segmenter.segment(wav, "rec3")

    loaded = segmenter.load_segments("rec3")
    assert len(loaded) == 2
    assert loaded[0].recording_id == "rec3"
    assert loaded[1].recording_id == "rec3"


def _tone(sr: int, duration_sec: float, amplitude: float = 0.8, freq: float = 300.0) -> np.ndarray:
    """生成指定时长的正弦波（模拟语音）."""
    t = np.arange(int(duration_sec * sr)) / sr
    return (amplitude * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def test_merge_short_segments(config):
    """相邻短句（间隔 < 0.7s）合并；间隔够大或句子够长则保留."""
    segmenter = SentenceSegmenter(config)

    short_near = [
        Segment(start=0.0, end=1.0),
        Segment(start=1.5, end=2.5),
    ]
    merged = segmenter._merge_short_segments(short_near)
    assert len(merged) == 1
    assert merged[0].start == 0.0
    assert merged[0].end == 2.5

    # 间隔 0.8s >= pause_threshold_sec，不合并
    far_apart = [
        Segment(start=0.0, end=1.0),
        Segment(start=1.8, end=2.8),
    ]
    assert len(segmenter._merge_short_segments(far_apart)) == 2

    # 都是长句（>= target_sentence_sec），即使间隔近也不合并
    long_sentences = [
        Segment(start=0.0, end=3.0),
        Segment(start=3.3, end=6.3),
    ]
    assert len(segmenter._merge_short_segments(long_sentences)) == 2


def test_sentence_boundary_at_silence_end(config):
    """句边界取静音终点（下一句语音起点），结尾静音取静音起点."""
    segmenter = SentenceSegmenter(config)
    sr = 16000
    tone = _tone(sr, 1.0)

    # 语音 1s + 静音 1s + 语音 1s：边界应为 2.0s（后句起点），不是静音中点 1.5s
    y = np.zeros(3 * sr, dtype=np.float32)
    y[0:sr] = tone
    y[2 * sr : 3 * sr] = tone
    bounds = segmenter._find_sentence_boundaries(y, sr, 0.0, 3.0)
    assert bounds == pytest.approx([0.0, 2.0, 3.0], abs=0.02)

    # 语音 1s + 结尾静音 1s：边界应为 1.0s（语音终点）
    y2 = np.zeros(2 * sr, dtype=np.float32)
    y2[0:sr] = tone
    bounds2 = segmenter._find_sentence_boundaries(y2, sr, 0.0, 2.0)
    assert bounds2 == pytest.approx([0.0, 1.0, 2.0], abs=0.02)


def test_force_split_at_energy_valley(config):
    """长句强制切分落在等分点附近的能量谷，而非等距硬切."""
    segmenter = SentenceSegmenter(config)
    sr = 16000
    total = 30.0
    t = np.arange(int(total * sr)) / sr
    y = (0.8 * np.sin(2 * np.pi * 300 * t)).astype(np.float32)
    # 在 12-14s 处制造能量谷（其余位置能量均匀）
    y[int(12 * sr) : int(14 * sr)] = _tone(sr, 2.0, amplitude=0.02)

    segs = segmenter._force_split_long_sentence(y, sr, 0.0, total)
    cut = segs[0].end
    assert 11.5 < cut < 14.5  # 切点应落在能量谷附近
    # 谷切点距终点 17.99s 超过最大句长，剩余部分会再补切一段
    assert all(seg.end - seg.start <= segmenter.max_sentence_sec for seg in segs)

    # 能量均匀时回退等距切分（15s 处）
    flat = (0.8 * np.sin(2 * np.pi * 300 * t)).astype(np.float32)
    segs_flat = segmenter._force_split_long_sentence(flat, sr, 0.0, total)
    assert len(segs_flat) == 2
    assert segs_flat[0].end == pytest.approx(15.0, abs=0.1)
