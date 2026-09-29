"""一次性修复：还原被误判为「人工修正」的 ASR 行.

背景
----
vue / element / alpine 三套原型页的文本框在失焦时**无条件**提交
（缺 native 页的「内容变了才提交」判断），试听时只要点过文本框，
原文就会被写成 ``is_manual=1`` / ``asr_source='manual'``，
进而把录音状态误判为 ``corrected``。

本脚本把这类「内容其实没变」的行还原回非人工来源。
为避免误删真实编辑，只还原满足以下任一条件的行：

- 文本为空（试听点击不可能产生有意义的空文本编辑）
- 文本等于 ASR 占位文本（原文没被改动过）

用法
----
    uv run python scripts/fix_misjudged_manual_asr.py --recording-id 4bbc286330a4
    uv run python scripts/fix_misjudged_manual_asr.py --recording-id 4bbc286330a4 --apply

不加 ``--apply`` 只预览，不做任何修改。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config import load_config  # noqa: E402
from src.db import Database  # noqa: E402

# ASR 模型未加载时的占位文本（见 src/transcriber.py）
PLACEHOLDER_TEXTS = {"占位转写文本（ASR 模型未加载）", "占位转写文本"}

# 还原后的来源标记：取该录音的主流来源，仅作展示用
RESTORED_SOURCE = "local"


def find_misjudged_rows(db: Database, recording_id: str) -> list[dict]:
    """找出内容未变却被标记为人工修正的 ASR 行."""
    with db._connect() as conn:
        rows = conn.execute(
            """
            SELECT s.segment_index, a.text, a.is_manual, a.asr_source
            FROM asr_results a
            JOIN segments s ON a.segment_id = s.id
            WHERE s.recording_id = ?
              AND (a.is_manual = 1 OR a.asr_source = 'manual')
            ORDER BY s.segment_index
            """,
            (recording_id,),
        ).fetchall()

    misjudged = []
    for row in rows:
        text = (row["text"] or "").strip()
        if text == "" or text in PLACEHOLDER_TEXTS:
            misjudged.append(dict(row))
    return misjudged


def revert_rows(db: Database, recording_id: str, segment_indexes: list[int]) -> int:
    """把指定片段的人工修正标记还原，返回受影响行数."""
    if not segment_indexes:
        return 0
    placeholders = ",".join("?" for _ in segment_indexes)
    with db._connect() as conn:
        cursor = conn.execute(
            f"""
            UPDATE asr_results
            SET is_manual = 0, asr_source = ?
            WHERE segment_id IN (
                SELECT id FROM segments
                WHERE recording_id = ? AND segment_index IN ({placeholders})
            )
            """,
            [RESTORED_SOURCE, recording_id, *segment_indexes],
        )
        return cursor.rowcount


def fix_recording_status(db: Database, recording_id: str) -> str | None:
    """若录音已无人为修正痕迹，把被误判的 failed 状态改回 transcribed."""
    if db.has_manual_asr(recording_id) or db.has_manual_speaker_corrections(recording_id):
        return None

    recording = db.get_recording(recording_id)
    if recording is None or recording["status"] != "failed":
        return None

    # 只有转写阶段确实完成过，才说明分析本身是成功的
    completed_stages = {
        item["stage"] for item in db.get_run_history(recording_id) if item["status"] == "completed"
    }
    if "asr" not in completed_stages:
        return None

    db.update_recording_status(recording_id, "transcribed")
    return "transcribed"


def main() -> int:
    parser = argparse.ArgumentParser(description="还原被误判为人工修正的 ASR 行")
    parser.add_argument("--recording-id", required=True, help="目标录音 ID")
    parser.add_argument("--db", default=None, help="数据库路径，默认取 config.yaml")
    parser.add_argument("--apply", action="store_true", help="真正写入；缺省只预览")
    args = parser.parse_args()

    db_path = args.db or load_config()["db_path"]
    db = Database(db_path)
    print(f"数据库: {db_path}")

    recording = db.get_recording(args.recording_id)
    if recording is None:
        print(f"找不到录音: {args.recording_id}")
        return 1
    print(f"录音 {args.recording_id}: status={recording['status']}")
    print(f"  failed_reason={recording['failed_reason']!r}")

    rows = find_misjudged_rows(db, args.recording_id)
    if not rows:
        print("没有需要还原的行。")
        return 0

    print(f"\n待还原 {len(rows)} 行（内容未变却标记为人工修正）:")
    for row in rows:
        preview = (row["text"] or "")[:30]
        print(f"  segment_index={row['segment_index']} text={preview!r}")

    if not args.apply:
        print("\n预览模式，未做修改。加 --apply 执行。")
        return 0

    affected = revert_rows(db, args.recording_id, [row["segment_index"] for row in rows])
    print(f"\n已还原 {affected} 行。")

    new_status = fix_recording_status(db, args.recording_id)
    if new_status:
        print(f"录音状态已修正为: {new_status}（并清空 failed_reason）")
    else:
        print("录音状态无需修正（仍有人工修正痕迹或状态本就不是 failed）。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
