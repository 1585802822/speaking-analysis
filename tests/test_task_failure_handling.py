"""任务失败处理与状态误判修复的测试.

覆盖四个修复面：
- 失败原因生命周期（成功推进即清空，含启动迁移对存量脏数据的修复）
- 阶段级自动重试（重试轨迹、耗尽行为、不破坏断点续跑）
- 单句评测失败记录（落库、不计入已评测集合、可重跑）
- SSE 事件协议（进度用 update、业务错误用 job_error）
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from src.config import load_config
from src.db import Database
from src.types import Segment
from src.web import service
from src.web.api import _sse_stream
from src.web.jobs import JobStore
from src.web.main import create_app


@pytest.fixture
def db(tmp_path: Path) -> Database:
    return Database(tmp_path / "test.db")


@pytest.fixture
def client(tmp_path: Path):
    """创建使用临时数据库的 TestClient."""
    config = load_config()
    config["db_path"] = str(tmp_path / "test.db")
    config["segments_dir"] = str(tmp_path / "segments")
    config["voiceprint_dir"] = str(tmp_path / "voiceprint")
    config["output_dir"] = str(tmp_path / "output")
    return TestClient(create_app(config))


# ----------------------------------------------------------------------
# 失败原因生命周期
# ----------------------------------------------------------------------


def test_update_status_clears_failed_reason(db: Database) -> None:
    """状态成功推进时清空历史失败原因."""
    db.save_recording("rec1", "/a.wav", 10.0, 16000, "segmented")
    db.mark_recording_failed("rec1", "句子切分阶段失败：boom")
    assert db.get_recording("rec1")["failed_reason"]

    db.update_recording_status("rec1", "transcribed")
    row = db.get_recording("rec1")
    assert row["status"] == "transcribed"
    assert row["failed_reason"] is None


def test_migration_clears_stale_failed_reason(tmp_path: Path) -> None:
    """启动迁移修复存量脏数据，同时保留真实失败原因（幂等）."""
    db_path = tmp_path / "test.db"
    db = Database(db_path)
    db.save_recording("rec1", "/a.wav", 10.0, 16000, "transcribed")
    db.save_recording("rec2", "/b.wav", 10.0, 16000, "segmented")
    db.mark_recording_failed("rec2", "语音转写阶段失败：boom")
    # 模拟历史遗留：非 failed 状态却带着失败原因
    with db._connect() as conn:
        conn.execute(
            "UPDATE recordings SET failed_reason = '服务重启导致处理中断' WHERE id = 'rec1'"
        )

    # 重新打开数据库即重跑迁移
    reopened = Database(db_path)
    assert reopened.get_recording("rec1")["failed_reason"] is None
    assert reopened.get_recording("rec2")["failed_reason"] == "语音转写阶段失败：boom"


def test_final_statuses_include_completed_analysis() -> None:
    """transcribed / corrected 是分析流水线的正常终点，重启不得误判为中断."""
    assert "transcribed" in service._FINAL_STATUSES
    assert "corrected" in service._FINAL_STATUSES


# ----------------------------------------------------------------------
# 阶段级自动重试
# ----------------------------------------------------------------------


def _stage_history(db: Database, recording_id: str) -> list[tuple[str, str]]:
    return [(item["stage"], item["status"]) for item in db.get_run_history(recording_id)]


def test_run_stage_with_retry_succeeds_after_transient_failure(
    db: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    """瞬时故障被重试吸收，重试轨迹完整写入 run_history."""
    monkeypatch.setattr(service, "_RETRY_BASE_DELAY", 0.0)
    db.ensure_recording("rec1", "/a.wav")
    store = JobStore()
    job = store.create()
    attempts: list[int] = []

    def fn() -> None:
        attempts.append(1)
        if len(attempts) < 3:
            raise RuntimeError("瞬时故障")

    service._run_stage_with_retry(db, "rec1", "asr", store, job.id, fn, max_retries=2)

    assert len(attempts) == 3
    assert _stage_history(db, "rec1") == [
        ("asr", "started"),
        ("asr", "failed"),
        ("asr", "started"),
        ("asr", "failed"),
        ("asr", "started"),
        ("asr", "completed"),
    ]
    assert "重试" in (store.get(job.id).message or "")


def test_run_stage_with_retry_raises_when_exhausted(
    db: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    """重试耗尽后抛出最后一次异常，交由顶层收尾."""
    monkeypatch.setattr(service, "_RETRY_BASE_DELAY", 0.0)
    db.ensure_recording("rec1", "/a.wav")
    store = JobStore()
    job = store.create()

    def fn() -> None:
        raise RuntimeError("始终失败")

    with pytest.raises(RuntimeError):
        service._run_stage_with_retry(db, "rec1", "asr", store, job.id, fn, max_retries=1)

    assert _stage_history(db, "rec1") == [
        ("asr", "started"),
        ("asr", "failed"),
        ("asr", "started"),
        ("asr", "failed"),
    ]


def test_retry_history_does_not_break_resume(db: Database, monkeypatch: pytest.MonkeyPatch) -> None:
    """重试留下的 failed 记录不影响续跑起点（只看最近一次 completed）."""
    monkeypatch.setattr(service, "_RETRY_BASE_DELAY", 0.0)
    db.ensure_recording("rec1", "/a.wav")
    store = JobStore()
    job = store.create()
    calls = {"n": 0}

    def fn() -> None:
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("第一次失败")

    service._run_stage_with_retry(db, "rec1", "segment", store, job.id, fn, max_retries=1)

    assert service._last_completed_status(db, "rec1") == "segmented"


# ----------------------------------------------------------------------
# 单句评测失败记录
# ----------------------------------------------------------------------


def _seed_segment(db: Database, recording_id: str = "rec1", index: int = 0) -> None:
    db.ensure_recording(recording_id, "/a.wav")
    seg = Segment(start=0.0, end=1.0, segment_index=index, recording_id=recording_id)
    db.save_segments(recording_id, [seg], [f"/seg/{index}.wav"])


def test_failed_evaluation_not_counted_as_evaluated(db: Database) -> None:
    """失败行落库但不计入已评测集合，因此下次评测会重跑该句."""
    _seed_segment(db)

    assert db.save_evaluation("rec1", 0, "ise", {}, status="failed", error_message="服务超时")
    assert db.get_evaluated_segment_indexes("rec1") == set()

    evals = db.get_evaluations("rec1")
    assert evals[0]["status"] == "failed"
    assert evals[0]["error_message"] == "服务超时"


def test_successful_reevaluation_overwrites_failed_row(db: Database) -> None:
    """重跑成功后失败行被覆盖，该句进入已评测集合."""
    _seed_segment(db)
    db.save_evaluation("rec1", 0, "ise", {}, status="failed", error_message="服务超时")

    assert db.save_evaluation("rec1", 0, "ise", {"findings": []})

    assert db.get_evaluated_segment_indexes("rec1") == {0}
    eval_row = db.get_evaluations("rec1")[0]
    assert eval_row["status"] == "success"
    assert eval_row["error_message"] is None


def test_legacy_evaluation_without_status_counts_as_evaluated(db: Database) -> None:
    """旧数据没有 status 值，按成功兼容."""
    _seed_segment(db)
    with db._connect() as conn:
        segment_id = conn.execute("SELECT id FROM segments WHERE segment_index = 0").fetchone()[
            "id"
        ]
        conn.execute(
            """
            INSERT INTO evaluations (segment_id, eval_type, result_json, status, created_at)
            VALUES (?, 'ise', '{}', NULL, '2026-01-01T00:00:00Z')
            """,
            (segment_id,),
        )

    assert db.get_evaluated_segment_indexes("rec1") == {0}


# ----------------------------------------------------------------------
# SSE 事件协议
# ----------------------------------------------------------------------


def _collect_sse(store: JobStore, job_id: str) -> list[str]:
    async def collect() -> list[str]:
        return [chunk async for chunk in _sse_stream(store, job_id)]

    return asyncio.run(collect())


def test_sse_pushes_update_frame_and_stops_on_terminal_status() -> None:
    """终态任务推一帧 update 后立即断流."""
    store = JobStore()
    job = store.create()
    store.set_finished(job.id, "completed", result={}, message="分析完成")

    frames = _collect_sse(store, job.id)

    assert len(frames) == 1
    assert frames[0].startswith("event: update\n")
    assert '"status": "completed"' in frames[0]


def test_sse_pushes_failed_frame_for_failed_job() -> None:
    """失败任务同样以 update 推送终态，便于前端展示失败原因."""
    store = JobStore()
    job = store.create()
    store.set_finished(job.id, "failed", error="boom", message="分析失败：语音转写阶段失败：boom")

    frames = _collect_sse(store, job.id)

    assert frames[0].startswith("event: update\n")
    assert '"status": "failed"' in frames[0]


def test_sse_uses_job_error_event_for_missing_job() -> None:
    """任务不存在用 job_error 事件，与浏览器网络层错误区分开."""
    frames = _collect_sse(JobStore(), "missing-job")

    assert len(frames) == 1
    assert frames[0].startswith("event: job_error\n")
    assert "任务不存在" in frames[0]


def test_sse_stream_endpoint_emits_named_update_event(client: Any) -> None:
    """HTTP 层确认事件名与 media type（回归：前端曾只监听 onmessage 收不到命名事件）."""
    store = client.app.state.job_store
    job = store.create()
    store.set_finished(job.id, "completed", result={}, message="分析完成")

    response = client.get(f"/api/jobs/{job.id}/stream")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "event: update" in response.text
