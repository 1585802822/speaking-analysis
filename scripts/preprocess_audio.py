#!/usr/bin/env python3
"""预处理导出脚本：对单个录音执行降噪/VAD 切分，按时间顺序导出片段.

解决"预处理后音频顺序错乱"的两项保障：
1. 片段先按 (start, end) 排序再导出，文件名同时带序号与时间戳
   (seg_{idx:03d}_{start:07.2f}-{end:07.2f}s.wav)，任何播放器按文件名
   排序即原始时间顺序。
2. segments.json/meta.json 记录源文件路径与时长，后续分离脚本据此校验，
   避免用 A 录音的时间戳去切 B 录音。

用法:
    python scripts/preprocess_audio.py "data/input/xxx.wav" \
        [--out data/output/preprocessed/run1] [--user-only]
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path
from typing import Any

import soundfile as sf
import yaml

# 确保从项目根目录导入 src 包
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.diarization import DiarizationModule
from src.enrollment import EnrollmentManager
from src.preprocessor import Preprocessor
from src.types import Segment


def load_config() -> dict[str, Any]:
    config_path = Path("config.yaml")
    if not config_path.exists():
        return {}
    with config_path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def denoise_backend_tag(config: dict[str, Any]) -> str:
    pre = config.get("preprocessing", {})
    denoise = pre.get("denoise", {}).get("backend", "spectral")
    vad = pre.get("vad", {}).get("backend", "energy")
    return f"{denoise}+{vad}"


def main() -> None:
    parser = argparse.ArgumentParser(description="预处理并按时间顺序导出音频片段")
    parser.add_argument("audio", help="源录音文件路径")
    parser.add_argument("--out", default="data/output/preprocessed/run", help="输出目录")
    parser.add_argument(
        "--user-only",
        action="store_true",
        help="仅导出目标说话人片段（需已注册声纹）",
    )
    args = parser.parse_args()

    config = load_config()
    audio_path = Path(args.audio)
    if not audio_path.exists():
        print(f"错误：源录音不存在 {audio_path}")
        return

    out_dir = Path(args.out)
    # 清空旧产物前先校验输出目录位于 data/output/ 下，避免误删源码或录音等目录
    output_root = Path("data/output").resolve()
    if output_root not in out_dir.resolve().parents:
        print(f"错误：--out 必须位于 data/output/ 目录之下（收到 {out_dir}），已拒绝执行")
        return
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    started = time.time()
    preprocessor = Preprocessor(config)
    print(f"加载并降噪: {audio_path}")
    y, sr = preprocessor.load_denoised(audio_path)
    duration = len(y) / sr
    print(f"源时长 {duration:.1f}s, 采样率 {sr}Hz, 后端 {denoise_backend_tag(config)}")

    segments: list[Segment] = preprocessor.process(audio_path)

    if args.user_only:
        voiceprint = EnrollmentManager(config).load_voiceprint()
        if voiceprint is None:
            print("错误：未找到注册声纹，无法按 --user-only 过滤")
            return
        module = DiarizationModule(config)
        segments = module.filter_segments_by_voiceprint(segments, audio_path, voiceprint=voiceprint)

    # 顺序保障：无论上游顺序如何，导出前统一按时间排序
    segments = sorted(segments, key=lambda s: (s.start, s.end))

    records = []
    for idx, seg in enumerate(segments):
        start_sample = max(0, int(seg.start * sr))
        end_sample = min(len(y), int(seg.end * sr))
        if end_sample <= start_sample:
            continue
        name = f"seg_{idx:03d}_{seg.start:07.2f}-{seg.end:07.2f}s.wav"
        sf.write(str(out_dir / name), y[start_sample:end_sample], sr)
        records.append(
            {
                "index": idx,
                "file": name,
                "start": round(seg.start, 3),
                "end": round(seg.end, 3),
                "duration": round(seg.end - seg.start, 3),
                "vad_confidence": seg.vad_confidence,
                "speaker_label": seg.speaker_label,
                "speaker_confidence": seg.speaker_confidence,
            }
        )

    with (out_dir / "segments.json").open("w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)

    meta = {
        "backend": denoise_backend_tag(config),
        "source_file": str(audio_path),
        "source_duration_sec": round(duration, 3),
        "user_only": bool(args.user_only),
        "segments_count": len(records),
        "speech_duration_sec": round(sum(r["duration"] for r in records), 3),
        "elapsed_sec": round(time.time() - started, 3),
    }
    with (out_dir / "meta.json").open("w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    print(f"导出 {len(records)} 个片段, 总语音 {meta['speech_duration_sec']:.1f}s -> {out_dir}")
    print(f"元数据: {out_dir / 'meta.json'}")


if __name__ == "__main__":
    main()
