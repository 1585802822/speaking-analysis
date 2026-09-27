#!/usr/bin/env python3
"""一键测试声纹提取与说话人分离."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import yaml

# 确保从项目根目录导入 src 包
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.diarization import DiarizationModule
from src.enrollment import EnrollmentManager
from src.types import Segment


def load_config() -> dict:
    config_path = Path("config.yaml")
    if not config_path.exists():
        return {}
    with config_path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def find_voiceprint_file(voiceprint_dir: Path) -> Path | None:
    """挑选声纹文件: 优先名字含"声纹"的, 其次按时长(文件大小)最长者."""
    audio_exts = (".wav", ".m4a", ".mp3", ".flac")
    candidates = [p for p in voiceprint_dir.iterdir() if p.suffix.lower() in audio_exts]
    if not candidates:
        return None
    named = [p for p in candidates if "声纹" in p.stem]
    pool = named or candidates
    return max(pool, key=lambda p: p.stat().st_size)


def load_preprocessed_segments(preprocessed_dir: Path) -> list[Segment]:
    segments_file = preprocessed_dir / "segments.json"
    if segments_file.exists():
        with segments_file.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return [
            Segment(
                start=item["start"],
                end=item["end"],
                vad_confidence=item.get("vad_confidence", 1.0),
            )
            for item in data
        ]

    # fallback: 从文件名解析 segment_###_start_end.wav
    segments = []
    for wav in sorted(preprocessed_dir.glob("segment_*.wav")):
        parts = wav.stem.split("_")
        if len(parts) >= 4:
            try:
                start = float(parts[2])
                end = float(parts[3])
                segments.append(Segment(start=start, end=end))
            except ValueError:
                continue
    return segments


def export_split_audio(
    split_segments: list[Segment],
    y: np.ndarray,
    sr: int,
    out_dir: Path,
) -> dict[str, Path]:
    """按说话人标签导出分离后的音频片段.

    每个片段保存为 <label>/label_###_<start>-<end>s.wav;
    额外把每个说话人的全部片段拼接成一个完整文件 <label>_all.wav.
    导出前清空输出目录, 片段按时间排序, 避免旧片段混入与顺序错乱.
    """
    import shutil

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
            str(label_dir / f"{label}_{idx:03d}_{seg.start:07.2f}-{seg.end:07.2f}s.wav"), chunk, sr
        )
        merged.setdefault(label, []).append(chunk)

    combined: dict[str, Path] = {}
    for label, chunks in merged.items():
        all_path = out_dir / f"{label}_all.wav"
        sf.write(str(all_path), np.concatenate(chunks), sr)
        combined[label] = all_path
    return combined


def main() -> None:
    config = load_config()
    voiceprint_dir = Path(config.get("voiceprint_dir", "data/voiceprint"))
    preprocessed_dir = Path("data/output/preprocessed")
    # segments.json 的时间戳基于完整录音 20260731-112120.wav (~5670s)
    audio_source = Path("tests/fixtures/raw/20260731-112120.wav")
    if len(sys.argv) > 1:
        audio_source = Path(sys.argv[1])

    print("=" * 50)
    print("声纹提取与说话人分离测试")
    print("=" * 50)

    # 1. 提取声纹
    voiceprint_file = find_voiceprint_file(voiceprint_dir)
    if voiceprint_file is None:
        print(f"错误：在 {voiceprint_dir} 中未找到声纹音频文件")
        return

    print(f"声纹文件：{voiceprint_file}")
    enrollment = EnrollmentManager({**config, "voiceprint_dir": str(voiceprint_dir)})
    enrollment.enroll(str(voiceprint_file))
    voiceprint = enrollment.load_voiceprint()
    if voiceprint is None:
        print("错误：声纹提取失败")
        return
    print(f"声纹嵌入维度：{voiceprint['embedding'].shape}")

    # 2. 加载预处理片段
    if not audio_source.exists():
        print(f"错误：音频源不存在 {audio_source}")
        return

    segments = load_preprocessed_segments(preprocessed_dir)
    print(f"预处理片段数：{len(segments)}")

    if not segments:
        print("没有预处理片段，跳过说话人分离")
        return

    # 检查片段时间范围与音频时长是否匹配，不匹配时裁剪并提示
    import librosa

    audio_duration = librosa.get_duration(path=str(audio_source))

    # 若预处理 meta.json 记录了来源录音，校验其与当前音频是否一致，
    # 避免用 A 录音的时间戳切 B 录音导致内容错乱
    meta_path = preprocessed_dir / "meta.json"
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            src_file = meta.get("source_file")
            src_dur = meta.get("source_duration_sec")
            if src_file and Path(src_file).resolve() != audio_source.resolve():
                print(
                    f"警告：预处理片段来自 {src_file}"
                    f"({'?' if src_dur is None else f'{src_dur:.1f}s'})，"
                    f"与当前音频 {audio_source} 不一致，切片内容可能错乱"
                )
        except (OSError, ValueError):
            pass
    max_end = max(s.end for s in segments)
    if max_end > audio_duration + 1.0:
        kept = [s for s in segments if s.end <= audio_duration]
        print(
            f"警告：片段最大时间 {max_end:.1f}s 超过音频时长 {audio_duration:.1f}s，"
            f"仅处理范围内的 {len(kept)}/{len(segments)} 个片段"
            f"（如需完整分析请传入对应的长录音文件）"
        )
        segments = kept
        if not segments:
            print("音频范围内没有片段，退出")
            return

    # 3. 说话人分离 (传入已加载音频数组, 避免二次 IO)
    y, sr = librosa.load(str(audio_source), sr=16000, mono=True)
    module = DiarizationModule(config)
    split_segments = module.split_by_voiceprint(
        segments,
        audio_source,
        voiceprint=voiceprint,
        window_sec=3.0,
        hop_sec=1.5,
        audio_array=(y, sr),
    )

    # 4. 统计
    stats = {"user": 0, "other": 0, "unknown": 0, "needs_review": 0}
    for seg in split_segments:
        label = seg.speaker_label or "unknown"
        stats[label] = stats.get(label, 0) + 1
        if seg.needs_review:
            stats["needs_review"] += 1

    print("-" * 50)
    print("分离结果统计：")
    print(f"  总窗口/片段数：{len(split_segments)}")
    print(f"  目标说话人 (user)：{stats['user']}")
    print(f"  非目标说话人 (other)：{stats['other']}")
    print(f"  未知/低置信度 (unknown)：{stats['unknown']}")
    print(f"  待复核 (needs_review)：{stats['needs_review']}")

    # 5. 导出分离后的音频（export_split_audio 内部会清空并重建输出目录）
    out_dir = Path("data/output/separated") / audio_source.stem
    combined = export_split_audio(split_segments, y, sr, out_dir)
    print("-" * 50)
    print(f"分离音频已导出到：{out_dir}")
    for label, path in sorted(combined.items()):
        print(
            f"  {label}: {len(list((out_dir / label).glob('*.wav')))} 个片段, 合并文件 {path.name}"
        )
    print("=" * 50)


if __name__ == "__main__":
    main()
