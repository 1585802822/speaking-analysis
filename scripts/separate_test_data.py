#!/usr/bin/env python3
"""说话人分离批处理脚本：对 01_preprocessed 下每个测试录音的片段做声纹分离导出.

复用 separate_enhanced 的注册与导出逻辑，按录音（test1/test2/test3）分组处理，
每份录音的分离结果独立保留在 output/02_separated/<录音名>/ 下，便于对照查看。

用法:
    python scripts/separate_test_data.py            # 处理 output/01_preprocessed 下全部录音
    python scripts/separate_test_data.py test1      # 只处理指定录音
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from typing import Any

import librosa

# 确保从项目根目录导入 src 包
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.separate_enhanced import (
    export_split_audio,
    load_config,
    reenroll_voiceprint,
)
from src.diarization import DiarizationModule
from src.types import Segment

PREPROCESSED_ROOT = Path("data/output/01_preprocessed")
SEPARATED_ROOT = Path("data/output/02_separated")


def separate_one_recording(
    recording_dir: Path,
    out_dir: Path,
    config: dict[str, Any],
    voiceprint: dict[str, Any],
    module: DiarizationModule,
) -> dict[str, Any]:
    """对单份录音的全部预处理片段执行声纹分离并导出.

    返回统计信息（各标签段数/时长），同时落盘 summary.json 便于留存中间结果。
    """
    seg_files = sorted(recording_dir.glob("seg_*.wav"))
    if not seg_files:
        print(f"错误：{recording_dir} 中没有 seg_*.wav 文件")
        return {}

    source_meta = recording_dir / "meta.json"
    source_info: dict[str, Any] = {}
    if source_meta.exists():
        try:
            source_info = json.loads(source_meta.read_text(encoding="utf-8"))
            if source_info.get("source_file"):
                print(
                    f"预处理来源: {source_info['source_file']} "
                    f"({source_info.get('source_duration_sec', '?')}s)"
                )
        except (OSError, ValueError):
            pass

    print(f"声纹分离 {len(seg_files)} 个增强片段 -> {out_dir}")
    total: dict[str, int] = {}
    total_sec: dict[str, float] = {}
    per_segment: list[dict[str, Any]] = []

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
        counters = export_split_audio(split_segments, y, sr, out_dir / wav.stem)
        for seg in split_segments:
            label = seg.speaker_label or "unknown"
            total[label] = total.get(label, 0) + 1
            total_sec[label] = total_sec.get(label, 0.0) + (seg.end - seg.start)
        per_segment.append(
            {
                "source_segment": wav.name,
                "duration_sec": round(duration, 3),
                "labels": counters,
                "split": [
                    {
                        "label": seg.speaker_label or "unknown",
                        "start": round(seg.start, 3),
                        "end": round(seg.end, 3),
                        "speaker_confidence": round(seg.speaker_confidence or 0.0, 4),
                    }
                    for seg in sorted(split_segments, key=lambda s: (s.start, s.end))
                ],
            }
        )
        print(
            f"  {wav.name}: {duration:6.1f}s -> "
            + " ".join(f"{k}:{v}" for k, v in sorted(counters.items()))
        )

    summary = {
        "source_recording": source_info.get("source_file"),
        "preprocessed_dir": str(recording_dir),
        "segments_processed": len(seg_files),
        "label_counts": total,
        "label_duration_sec": {k: round(v, 3) for k, v in total_sec.items()},
        "per_segment": per_segment,
    }
    with (out_dir / "summary.json").open("w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    return summary


def main() -> None:
    config = load_config()
    args = sys.argv[1:]

    if not PREPROCESSED_ROOT.exists():
        print(f"错误：预处理目录不存在 {PREPROCESSED_ROOT}")
        return

    if args:
        recording_dirs = [PREPROCESSED_ROOT / name for name in args]
        missing = [str(d) for d in recording_dirs if not d.exists()]
        if missing:
            print(f"错误：以下预处理目录不存在: {missing}")
            return
    else:
        recording_dirs = sorted(
            d for d in PREPROCESSED_ROOT.iterdir() if d.is_dir() and list(d.glob("seg_*.wav"))
        )
        if not recording_dirs:
            print(f"错误：{PREPROCESSED_ROOT} 下没有包含片段的录音目录")
            return

    # 整体清空上次的分离结果，避免已不存在的片段目录残留被误认为本次产物
    if SEPARATED_ROOT.exists():
        shutil.rmtree(SEPARATED_ROOT)
    SEPARATED_ROOT.mkdir(parents=True, exist_ok=True)

    print("=" * 50)
    print("1. 重新注册声纹")
    print("=" * 50)
    voiceprint = reenroll_voiceprint(config)

    print("=" * 50)
    print(f"2. 声纹分离 {len(recording_dirs)} 份录音")
    print("=" * 50)
    module = DiarizationModule(config)
    all_summaries: dict[str, Any] = {}
    for recording_dir in recording_dirs:
        out_dir = SEPARATED_ROOT / recording_dir.name
        out_dir.mkdir(parents=True, exist_ok=True)
        print(f"\n>>> 处理 {recording_dir.name}")
        summary = separate_one_recording(recording_dir, out_dir, config, voiceprint, module)
        if summary:
            all_summaries[recording_dir.name] = {
                "label_counts": summary["label_counts"],
                "label_duration_sec": summary["label_duration_sec"],
            }

    print("\n" + "=" * 50)
    print("分离结果统计：")
    for name, s in all_summaries.items():
        counts = " ".join(
            f"{k}:{n}段/{s['label_duration_sec'][k]:.1f}s"
            for k, n in sorted(s["label_counts"].items())
        )
        print(f"  {name}: {counts}")
    print(f"分离音频已导出到：{SEPARATED_ROOT}")
    print("=" * 50)


if __name__ == "__main__":
    main()
