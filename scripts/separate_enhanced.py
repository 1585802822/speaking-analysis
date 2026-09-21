#!/usr/bin/env python3
"""用 data/voiceprint 全部音频重新注册声纹, 并对 enhanced 片段做声纹分离导出."""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from typing import Any

import librosa
import numpy as np
import yaml

# 确保从项目根目录导入 src 包
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.diarization import DiarizationModule
from src.enrollment import EnrollmentManager
from src.types import Segment

AUDIO_EXTS = (".wav", ".m4a", ".mp3", ".flac")


def load_config() -> dict[str, Any]:
    config_path = Path("config.yaml")
    if not config_path.exists():
        return {}
    with config_path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def reenroll_voiceprint(config: dict[str, Any]) -> dict[str, Any]:
    """用 voiceprint_dir 下全部音频重新注册声纹.

    走 EnrollmentManager.enroll_multi: 能量 VAD 裁剪 + 分块取均值(ECAPA 优先),
    避免整段嵌入被静音污染.
    """
    voiceprint_dir = Path(config.get("voiceprint_dir", "data/voiceprint"))
    files = sorted(
        p for p in voiceprint_dir.iterdir() if p.suffix.lower() in AUDIO_EXTS
    )
    if not files:
        raise RuntimeError(f"{voiceprint_dir} 中没有音频文件, 无法注册声纹")

    for p in files:
        print(f"  注册样本: {p.name}")

    manager = EnrollmentManager({**config, "voiceprint_dir": str(voiceprint_dir)})
    manager.enroll_multi([str(p) for p in files])
    voiceprint = manager.load_voiceprint()
    if voiceprint is None:
        raise RuntimeError("声纹注册失败: embedding.pkl 未生成")
    print(
        f"声纹已重新注册(model={voiceprint.get('model')}, "
        f"chunks={voiceprint.get('chunk_count')}) -> {voiceprint_dir / 'embedding.pkl'}"
    )
    return voiceprint


def export_split_audio(
    split_segments: list[Segment],
    y: np.ndarray,
    sr: int,
    out_dir: Path,
) -> dict[str, int]:
    """按说话人标签导出分离后的音频片段, 并拼接每个说话人的完整文件.

    导出前清空输出目录, 避免多次运行的旧片段混入; 片段按时间排序,
    文件名带时间戳, 按文件名排序即时间顺序.
    """
    import soundfile as sf

    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    counters: dict[str, int] = {}
    merged: dict[str, list[np.ndarray]] = {}
    for seg in sorted(split_segments, key=lambda s: (s.start, s.end)):
        label = seg.speaker_label or "unknown"
        start = max(0, int(seg.start * sr))
        end = min(len(y), int(seg.end * sr))
        if end <= start:
            continue
        chunk = y[start:end]
        label_dir = out_dir / label
        label_dir.mkdir(parents=True, exist_ok=True)
        idx = counters.get(label, 0)
        counters[label] = idx + 1
        sf.write(
            str(label_dir / f"{label}_{idx:03d}_{seg.start:07.2f}-{seg.end:07.2f}s.wav"),
            chunk,
            sr,
        )
        merged.setdefault(label, []).append(chunk)

    for label, chunks in merged.items():
        sf.write(str(out_dir / f"{label}_all.wav"), np.concatenate(chunks), sr)
    return counters


def main() -> None:
    config = load_config()
    enhanced_dir = Path("data/output/preprocessed/enhanced")
    out_root = Path("data/output/separated/enhanced")
    # 整体清空上次的分离结果，避免已不存在的片段目录残留被误认为本次产物
    if out_root.exists():
        shutil.rmtree(out_root)
    out_root.mkdir(parents=True, exist_ok=True)

    print("=" * 50)
    print("1. 重新注册声纹")
    print("=" * 50)
    voiceprint = reenroll_voiceprint(config)

    seg_files = sorted(enhanced_dir.glob("seg_*.wav"))
    if not seg_files:
        print(f"错误：{enhanced_dir} 中没有 seg_*.wav 文件")
        return
    # 打印预处理产物的来源信息, 提醒用户确认片段来自哪份录音
    source_meta = enhanced_dir / "meta.json"
    if source_meta.exists():
        try:
            meta = json.loads(source_meta.read_text(encoding="utf-8"))
            if meta.get("source_file"):
                print(f"预处理来源: {meta['source_file']} ({meta.get('source_duration_sec', '?')}s)")
        except (OSError, ValueError):
            pass
    print("=" * 50)
    print(f"2. 声纹分离 {len(seg_files)} 个增强片段")
    print("=" * 50)

    module = DiarizationModule(config)
    total = {"user": 0, "other": 0, "unknown": 0}
    total_sec = {"user": 0.0, "other": 0.0, "unknown": 0.0}

    for wav in seg_files:
        y, sr = librosa.load(str(wav), sr=16000, mono=True)
        duration = len(y) / sr
        split_segments = module.split_by_voiceprint(
            [Segment(start=0.0, end=duration)],
            wav,
            voiceprint=voiceprint,
            window_sec=3.0,
            hop_sec=1.5,
            audio_array=(y, sr),
        )
        counters = export_split_audio(split_segments, y, sr, out_root / wav.stem)
        for seg in split_segments:
            label = seg.speaker_label or "unknown"
            total[label] = total.get(label, 0) + 1
            total_sec[label] = total_sec.get(label, 0.0) + (seg.end - seg.start)
        print(
            f"  {wav.name}: {duration:6.1f}s -> "
            + " ".join(f"{k}:{v}" for k, v in sorted(counters.items()))
        )

    print("=" * 50)
    print("分离结果统计：")
    for label in sorted(total):
        print(f"  {label}: {total[label]} 段, 共 {total_sec[label]:.1f}s")
    print(f"分离音频已导出到：{out_root}")
    print("=" * 50)


if __name__ == "__main__":
    main()
