"""SQLite 数据访问层.

管理录音、句子片段、声纹分离结果、ASR 结果、人工校正记录之间的关联。
音频 WAV 文件仍保存在 ``data/segments/{recording_id}/`` 目录下，
数据库只存储元数据和关系，便于后续 UI 查询和增量更新。
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .types import Segment, SegmentTranscription


def _utc_now() -> str:
    """返回 ISO 格式 UTC 时间字符串."""
    return datetime.now(timezone.utc).isoformat()


class Database:
    """项目 SQLite 数据库访问封装."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        """建立数据库连接，启用外键约束."""
        conn = sqlite3.connect(str(self.db_path))
        conn.execute("PRAGMA foreign_keys = ON")
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        """首次连接时执行建表脚本，并补齐旧库缺失的列."""
        schema_path = Path(__file__).with_name("schema.sql")
        if not schema_path.exists():
            raise FileNotFoundError(f"数据库表结构脚本不存在: {schema_path}")
        sql = schema_path.read_text(encoding="utf-8")
        with self._connect() as conn:
            conn.executescript(sql)
            self._migrate_schema(conn)

    def _migrate_schema(self, conn: sqlite3.Connection) -> None:
        """为旧库补齐新增列（幂等，已有列则跳过）."""

        def _add_column(table: str, column: str, ddl: str) -> None:
            existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
            if column not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")

        _add_column("recordings", "created_at", "created_at TEXT")
        _add_column("recordings", "run_count", "run_count INTEGER DEFAULT 0")
        _add_column("recordings", "failed_reason", "failed_reason TEXT")
        _add_column("asr_results", "is_manual", "is_manual INTEGER DEFAULT 0")
        _add_column("evaluations", "status", "status TEXT DEFAULT 'success'")
        _add_column("evaluations", "error_message", "error_message TEXT")

        # 数据修复：失败原因只在失败时写入，非 failed 状态不应残留历史失败原因
        conn.execute(
            """
            UPDATE recordings SET failed_reason = NULL
            WHERE status != 'failed' AND failed_reason IS NOT NULL
            """
        )

    # ------------------------------------------------------------------
    # recordings
    # ------------------------------------------------------------------
    def save_recording(
        self,
        recording_id: str,
        original_path: str,
        duration_sec: float,
        sample_rate: int = 16000,
        status: str = "segmented",
    ) -> None:
        """保存或更新录音记录.

        重跑同一录音时保留 created_at，run_count 递增，
        failed_reason 清零。
        """
        now = _utc_now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO recordings
                    (id, original_path, sample_rate, duration_sec, processed_at, status,
                     created_at, run_count, failed_reason)
                VALUES (?, ?, ?, ?, ?, ?, ?, 1, NULL)
                ON CONFLICT(id) DO UPDATE SET
                    original_path=excluded.original_path,
                    sample_rate=excluded.sample_rate,
                    duration_sec=excluded.duration_sec,
                    processed_at=excluded.processed_at,
                    status=excluded.status,
                    failed_reason=NULL,
                    run_count=recordings.run_count + 1
                """,
                (recording_id, original_path, sample_rate, duration_sec, now, status, now),
            )

    def ensure_recording(self, recording_id: str, original_path: str) -> None:
        """确保 recordings 行存在（run_history 外键依赖它）.

        首次分析时占位插入 status='new'、run_count=0，
        后续 save_recording 更新时 run_count 递增为 1。
        """
        now = _utc_now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO recordings
                    (id, original_path, sample_rate, duration_sec, processed_at, status,
                     created_at, run_count, failed_reason)
                VALUES (?, ?, 0, 0.0, ?, 'new', ?, 0, NULL)
                """,
                (recording_id, original_path, now, now),
            )

    def get_recording(self, recording_id: str) -> dict[str, Any] | None:
        """按 ID 查询录音记录."""
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM recordings WHERE id = ?", (recording_id,)).fetchone()
            return dict(row) if row else None

    def list_recordings(self) -> list[dict[str, Any]]:
        """按 processed_at 倒序列出全部录音."""
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM recordings ORDER BY processed_at DESC").fetchall()
            return [dict(row) for row in rows]

    def update_recording_status(self, recording_id: str, status: str) -> None:
        """更新录音处理状态.

        任何状态推进都视为已从失败中恢复，因此一并清空 failed_reason；
        该字段只在 mark_recording_failed 中写入。
        """
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE recordings
                SET status = ?, failed_reason = NULL, processed_at = ?
                WHERE id = ?
                """,
                (status, _utc_now(), recording_id),
            )

    def mark_recording_failed(self, recording_id: str, reason: str) -> None:
        """标记录音处理失败并记录原因（供 UI 展示与续跑定位）."""
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE recordings
                SET status = 'failed', failed_reason = ?, processed_at = ?
                WHERE id = ?
                """,
                (reason, _utc_now(), recording_id),
            )

    # ------------------------------------------------------------------
    # segments
    # ------------------------------------------------------------------
    def save_segments(
        self, recording_id: str, segments: list[Segment], audio_paths: list[str]
    ) -> None:
        """批量保存句子片段.

        Args:
            recording_id: 录音 ID.
            segments: 片段列表，要求已按时间排序且 ``segment_index`` 已设置.
            audio_paths: 与 ``segments`` 一一对应的持久化音频路径.
        """
        if len(segments) != len(audio_paths):
            raise ValueError("segments 与 audio_paths 长度不一致")
        with self._connect() as conn:
            for seg, path in zip(segments, audio_paths):
                conn.execute(
                    """
                    INSERT INTO segments
                        (recording_id, segment_index, audio_path, start_sec, end_sec, duration_sec)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(recording_id, segment_index) DO UPDATE SET
                        audio_path=excluded.audio_path,
                        start_sec=excluded.start_sec,
                        end_sec=excluded.end_sec,
                        duration_sec=excluded.duration_sec
                    """,
                    (
                        recording_id,
                        seg.segment_index,
                        path,
                        seg.start,
                        seg.end,
                        seg.end - seg.start,
                    ),
                )

    def get_segments(self, recording_id: str) -> list[dict[str, Any]]:
        """查询某录音的所有片段."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM segments WHERE recording_id = ? ORDER BY segment_index",
                (recording_id,),
            ).fetchall()
            return [dict(row) for row in rows]

    def get_segment_by_index(self, recording_id: str, segment_index: int) -> dict[str, Any] | None:
        """按录音 ID 和片段索引查询单条片段."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM segments WHERE recording_id = ? AND segment_index = ?",
                (recording_id, segment_index),
            ).fetchone()
            return dict(row) if row else None

    def cleanup_orphan_segments(self, recording_id: str, valid_indices: list[int]) -> None:
        """删除不在最新索引列表中的片段（连同子表数据）.

        重跑切分后片段数量可能变化，多余的旧片段行会成为孤儿数据；
        本方法同时清理数据库行和对应的 WAV 文件。
        """
        if not valid_indices:
            return
        placeholders = ",".join("?" for _ in valid_indices)
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT id, audio_path FROM segments
                WHERE recording_id = ? AND segment_index NOT IN ({placeholders})
                """,
                (recording_id, *valid_indices),
            ).fetchall()
            orphan_ids = [row["id"] for row in rows]
            if not orphan_ids:
                return
            id_placeholders = ",".join("?" for _ in orphan_ids)
            # 先删引用 segment 的子表行，避免外键约束阻止删除
            for table in ("speaker_corrections", "evaluations", "asr_results", "diarization"):
                conn.execute(
                    f"DELETE FROM {table} WHERE segment_id IN ({id_placeholders})",
                    orphan_ids,
                )
            conn.execute(
                f"DELETE FROM segments WHERE id IN ({id_placeholders})",
                orphan_ids,
            )
        for row in rows:
            try:
                Path(row["audio_path"]).unlink(missing_ok=True)
            except OSError:
                pass

    def delete_recording(self, recording_id: str) -> bool:
        """删除整条录音的数据库记录（片段目录由调用方清理）."""
        with self._connect() as conn:
            seg_ids = [
                row["id"]
                for row in conn.execute(
                    "SELECT id FROM segments WHERE recording_id = ?", (recording_id,)
                ).fetchall()
            ]
            if seg_ids:
                id_placeholders = ",".join("?" for _ in seg_ids)
                for table in ("speaker_corrections", "evaluations", "asr_results", "diarization"):
                    conn.execute(
                        f"DELETE FROM {table} WHERE segment_id IN ({id_placeholders})",
                        seg_ids,
                    )
                conn.execute(
                    f"DELETE FROM segments WHERE id IN ({id_placeholders})",
                    seg_ids,
                )
            conn.execute("DELETE FROM run_history WHERE recording_id = ?", (recording_id,))
            cur = conn.execute("DELETE FROM recordings WHERE id = ?", (recording_id,))
            return cur.rowcount > 0

    def reset_recording(self, recording_id: str) -> bool:
        """重置录音的中间结果，仅保留 recordings 行（状态回到 new）.

        用于"强制重新分析"：清空片段、声纹、ASR、评测与运行历史，
        用户手工修正也随之清除。
        """
        with self._connect() as conn:
            seg_ids = [
                row["id"]
                for row in conn.execute(
                    "SELECT id FROM segments WHERE recording_id = ?", (recording_id,)
                ).fetchall()
            ]
            if seg_ids:
                id_placeholders = ",".join("?" for _ in seg_ids)
                for table in ("speaker_corrections", "evaluations", "asr_results", "diarization"):
                    conn.execute(
                        f"DELETE FROM {table} WHERE segment_id IN ({id_placeholders})",
                        seg_ids,
                    )
                conn.execute(
                    f"DELETE FROM segments WHERE id IN ({id_placeholders})",
                    seg_ids,
                )
            conn.execute("DELETE FROM run_history WHERE recording_id = ?", (recording_id,))
            cur = conn.execute(
                """
                UPDATE recordings
                SET status = 'new', failed_reason = NULL, processed_at = ?
                WHERE id = ?
                """,
                (_utc_now(), recording_id),
            )
            return cur.rowcount > 0

    # ------------------------------------------------------------------
    # diarization
    # ------------------------------------------------------------------
    def save_diarization(
        self, recording_id: str, segments: list[Segment], protect_manual: bool = False
    ) -> None:
        """保存声纹分离结果.

        ``segments`` 必须已经设置 ``segment_index`` 和 ``speaker_label``。
        当 ``protect_manual`` 为 True 时，跳过存在人工校正记录的片段，
        避免重跑覆盖用户手工修正的说话人标签。
        """
        protected: set[int] = set()
        if protect_manual:
            protected = self._manually_corrected_segment_ids(recording_id)
        with self._connect() as conn:
            for seg in segments:
                if seg.segment_index is None:
                    continue
                db_seg = self.get_segment_by_index(recording_id, seg.segment_index)
                if db_seg is None:
                    continue
                if protect_manual and db_seg["id"] in protected:
                    continue
                conn.execute(
                    """
                    INSERT INTO diarization
                        (segment_id, speaker_label, confidence, needs_review, created_at)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(segment_id) DO UPDATE SET
                        speaker_label=excluded.speaker_label,
                        confidence=excluded.confidence,
                        needs_review=excluded.needs_review,
                        created_at=excluded.created_at
                    """,
                    (
                        db_seg["id"],
                        seg.speaker_label or "unknown",
                        seg.speaker_confidence,
                        seg.needs_review,
                        _utc_now(),
                    ),
                )

    def _manually_corrected_segment_ids(self, recording_id: str) -> set[int]:
        """返回该录音下存在人工说话人校正的 segment_id 集合."""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT c.segment_id FROM speaker_corrections c
                JOIN segments s ON c.segment_id = s.id
                WHERE s.recording_id = ?
                """,
                (recording_id,),
            ).fetchall()
            return {row["segment_id"] for row in rows}

    def has_manual_speaker_corrections(self, recording_id: str) -> bool:
        """该录音是否有人工说话人校正记录."""
        return bool(self._manually_corrected_segment_ids(recording_id))

    def has_manual_asr(self, recording_id: str) -> bool:
        """该录音是否有人工修正的 ASR 文本."""
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) AS n FROM asr_results a
                JOIN segments s ON a.segment_id = s.id
                WHERE s.recording_id = ? AND (a.is_manual = 1 OR a.asr_source = 'manual')
                """,
                (recording_id,),
            ).fetchone()
            return bool(row["n"])

    def get_diarization(self, recording_id: str) -> list[dict[str, Any]]:
        """查询某录音的所有声纹分离结果."""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT d.*, s.segment_index
                FROM diarization d
                JOIN segments s ON d.segment_id = s.id
                WHERE s.recording_id = ?
                ORDER BY s.segment_index
                """,
                (recording_id,),
            ).fetchall()
            return [dict(row) for row in rows]

    def get_segments_by_speaker(
        self, recording_id: str, speaker_label: str
    ) -> list[dict[str, Any]]:
        """按说话人标签查询片段."""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT s.*, d.speaker_label, d.confidence, d.needs_review
                FROM segments s
                JOIN diarization d ON s.id = d.segment_id
                WHERE s.recording_id = ? AND d.speaker_label = ?
                ORDER BY s.segment_index
                """,
                (recording_id, speaker_label),
            ).fetchall()
            return [dict(row) for row in rows]

    # ------------------------------------------------------------------
    # ASR results
    # ------------------------------------------------------------------
    def save_asr_results(
        self,
        recording_id: str,
        transcriptions: list[SegmentTranscription],
        protect_manual: bool = False,
    ) -> None:
        """保存 ASR 转写结果.

        当 ``protect_manual`` 为 True 时，跳过人工修正过的片段，
        避免重跑覆盖用户手工修改的 ASR 文本。
        """
        with self._connect() as conn:
            for tx in transcriptions:
                db_seg = self.get_segment_by_index(recording_id, tx.segment_index)
                if db_seg is None:
                    continue
                if protect_manual:
                    manual = conn.execute(
                        "SELECT is_manual, asr_source FROM asr_results WHERE segment_id = ?",
                        (db_seg["id"],),
                    ).fetchone()
                    if manual and (manual["is_manual"] or manual["asr_source"] == "manual"):
                        continue
                words_json = json.dumps(
                    [{"text": w.text, "start": w.start, "end": w.end} for w in tx.words],
                    ensure_ascii=False,
                )
                conn.execute(
                    """
                    INSERT INTO asr_results
                        (segment_id, asr_source, text, words_json,
                         status, error_message, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(segment_id) DO UPDATE SET
                        asr_source=excluded.asr_source,
                        text=excluded.text,
                        words_json=excluded.words_json,
                        status=excluded.status,
                        error_message=excluded.error_message,
                        created_at=excluded.created_at
                    """,
                    (
                        db_seg["id"],
                        tx.asr_source,
                        tx.text,
                        words_json,
                        tx.status,
                        tx.error_message,
                        _utc_now(),
                    ),
                )

    def get_asr_results(self, recording_id: str) -> list[dict[str, Any]]:
        """查询某录音的所有 ASR 结果."""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT a.*, s.segment_index
                FROM asr_results a
                JOIN segments s ON a.segment_id = s.id
                WHERE s.recording_id = ?
                ORDER BY s.segment_index
                """,
                (recording_id,),
            ).fetchall()
            return [dict(row) for row in rows]

    def update_asr_text(self, recording_id: str, segment_index: int, text: str) -> bool:
        """更新或插入某片段的 ASR 文本，标记为人工修正."""
        db_seg = self.get_segment_by_index(recording_id, segment_index)
        if db_seg is None:
            return False
        segment_id = db_seg["id"]
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO asr_results
                    (segment_id, asr_source, text, words_json, status, error_message, created_at,
                     is_manual)
                VALUES (?, 'manual', ?, '[]', 'success', NULL, ?, 1)
                ON CONFLICT(segment_id) DO UPDATE SET
                    asr_source='manual',
                    text=excluded.text,
                    words_json=COALESCE(asr_results.words_json, '[]'),
                    status='success',
                    error_message=NULL,
                    created_at=excluded.created_at,
                    is_manual=1
                """,
                (segment_id, text, _utc_now()),
            )
        return True

    # ------------------------------------------------------------------
    # speaker corrections
    # ------------------------------------------------------------------
    def apply_speaker_correction(
        self, recording_id: str, segment_index: int, new_label: str
    ) -> bool:
        """应用人工校正，更新 diarization 标签并记录校正历史.

        返回是否成功更新。
        """
        return self.update_speaker_label(recording_id, segment_index, new_label)

    def update_speaker_label(self, recording_id: str, segment_index: int, new_label: str) -> bool:
        """更新说话人标签，仅支持 user / other，并记录校正历史."""
        if new_label not in {"user", "other"}:
            raise ValueError("new_label 必须是 'user' 或 'other'")
        db_seg = self.get_segment_by_index(recording_id, segment_index)
        if db_seg is None:
            return False
        segment_id = db_seg["id"]
        with self._connect() as conn:
            row = conn.execute(
                "SELECT speaker_label FROM diarization WHERE segment_id = ?",
                (segment_id,),
            ).fetchone()
            old_label = row["speaker_label"] if row else "unknown"
            conn.execute(
                """
                INSERT INTO speaker_corrections (segment_id, old_label, new_label, corrected_at)
                VALUES (?, ?, ?, ?)
                """,
                (segment_id, old_label, new_label, _utc_now()),
            )
            needs_review = False  # 二分类后不再产生待复核档，保留列以兼容旧数据
            conn.execute(
                """
                INSERT INTO diarization
                    (segment_id, speaker_label, confidence, needs_review, created_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(segment_id) DO UPDATE SET
                    speaker_label=excluded.speaker_label,
                    confidence=excluded.confidence,
                    needs_review=excluded.needs_review,
                    created_at=excluded.created_at
                """,
                (segment_id, new_label, None, needs_review, _utc_now()),
            )
        return True

    def get_correction_history(self, recording_id: str | None = None) -> list[dict[str, Any]]:
        """查询人工校正历史."""
        sql = """
            SELECT c.*, s.recording_id, s.segment_index
            FROM speaker_corrections c
            JOIN segments s ON c.segment_id = s.id
        """
        params: tuple[Any, ...] = ()
        if recording_id is not None:
            sql += " WHERE s.recording_id = ?"
            params = (recording_id,)
        sql += " ORDER BY c.corrected_at DESC"
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
            return [dict(row) for row in rows]

    # ------------------------------------------------------------------
    # convenience: full transcription view
    # ------------------------------------------------------------------
    def get_transcription_view(self, recording_id: str) -> list[dict[str, Any]]:
        """返回某录音的完整转写视图，包含片段、声纹、ASR 结果."""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    s.segment_index,
                    s.audio_path,
                    s.start_sec,
                    s.end_sec,
                    d.speaker_label,
                    d.confidence AS speaker_confidence,
                    d.needs_review,
                    a.asr_source,
                    a.text,
                    a.words_json,
                    a.status,
                    a.error_message
                FROM segments s
                LEFT JOIN diarization d ON s.id = d.segment_id
                LEFT JOIN asr_results a ON s.id = a.segment_id
                WHERE s.recording_id = ?
                ORDER BY s.segment_index
                """,
                (recording_id,),
            ).fetchall()
            results = []
            for row in rows:
                item = dict(row)
                # 历史数据的 needs_review 标签在读取层归一化为 other
                if item.get("speaker_label") == "needs_review":
                    item["speaker_label"] = "other"
                try:
                    item["words"] = json.loads(item.pop("words_json") or "[]")
                except json.JSONDecodeError:
                    item["words"] = []
                results.append(item)
            return results

    # ------------------------------------------------------------------
    # evaluations
    # ------------------------------------------------------------------
    def save_evaluation(
        self,
        recording_id: str,
        segment_index: int,
        eval_type: str,
        result: dict[str, Any],
        status: str = "success",
        error_message: str | None = None,
    ) -> bool:
        """保存某片段的评测结果.

        Args:
            status: ``success`` 或 ``failed``；失败行不计入已评测集合，可被重跑覆盖。
            error_message: 失败原因，仅在 ``status="failed"`` 时有意义。
        """
        db_seg = self.get_segment_by_index(recording_id, segment_index)
        if db_seg is None:
            return False
        segment_id = db_seg["id"]
        result_json = json.dumps(result, ensure_ascii=False)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO evaluations
                    (segment_id, eval_type, result_json, status, error_message, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(segment_id, eval_type) DO UPDATE SET
                    result_json=excluded.result_json,
                    status=excluded.status,
                    error_message=excluded.error_message,
                    created_at=excluded.created_at
                """,
                (segment_id, eval_type, result_json, status, error_message, _utc_now()),
            )
        return True

    def get_evaluations(self, recording_id: str) -> list[dict[str, Any]]:
        """按 segment_index 返回某录音的评测结果."""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT e.*, s.segment_index
                FROM evaluations e
                JOIN segments s ON e.segment_id = s.id
                WHERE s.recording_id = ?
                ORDER BY s.segment_index, e.created_at
                """,
                (recording_id,),
            ).fetchall()
            results = []
            for row in rows:
                item = dict(row)
                try:
                    item["result"] = json.loads(item.pop("result_json") or "{}")
                except json.JSONDecodeError:
                    item["result"] = {}
                results.append(item)
            return results

    def get_evaluated_segment_indexes(self, recording_id: str, eval_type: str = "ise") -> set[int]:
        """返回该录音已评测的 segment_index 集合（用于续跑时跳过）.

        只统计成功的评测行；失败行留待下次评测重跑。
        旧数据没有 status 列，按成功兼容。
        """
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT s.segment_index FROM evaluations e
                JOIN segments s ON e.segment_id = s.id
                WHERE s.recording_id = ? AND e.eval_type = ?
                  AND (e.status IS NULL OR e.status = 'success')
                """,
                (recording_id, eval_type),
            ).fetchall()
            return {row["segment_index"] for row in rows}

    # ------------------------------------------------------------------
    # run history
    # ------------------------------------------------------------------
    def save_run_history(
        self,
        recording_id: str,
        stage: str,
        status: str,
        error_message: str | None = None,
    ) -> None:
        """记录一次阶段运行事件，用于断点续跑时定位中断位置."""
        now = _utc_now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO run_history
                    (recording_id, stage, status, started_at, finished_at, error_message)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    recording_id,
                    stage,
                    status,
                    now,
                    now if status != "started" else None,
                    error_message,
                ),
            )

    def get_run_history(self, recording_id: str) -> list[dict[str, Any]]:
        """按时间顺序返回某录音的阶段运行历史."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM run_history WHERE recording_id = ? ORDER BY id",
                (recording_id,),
            ).fetchall()
            return [dict(row) for row in rows]

    def close(self) -> None:
        """数据库连接由上下文自动管理，本方法仅作占位兼容."""
        pass
