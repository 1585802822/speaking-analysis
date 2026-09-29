"""FastAPI REST 路由."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse

from ..db import Database
from ..recording_id import recording_id_from_path
from .jobs import JobStore
from .schemas import (
    AnalyzeRequest,
    EvaluationJobResponse,
    JobResponse,
    OKResponse,
    ScanRequest,
    SpeakerUpdateRequest,
    TextUpdateRequest,
)
from .service import run_analysis, run_evaluation

router = APIRouter()
logger = logging.getLogger(__name__)


def _config(request: Request) -> dict[str, Any]:
    return request.app.state.config


def _job_store(request: Request) -> JobStore:
    return request.app.state.job_store


def _db(request: Request) -> Database:
    return Database(_config(request)["db_path"])


@router.get("/recordings")
def list_recordings(request: Request) -> dict[str, Any]:
    """返回全部录音历史."""
    return {"recordings": _db(request).list_recordings()}


@router.get("/recordings/{recording_id}")
def get_recording(recording_id: str, request: Request) -> dict[str, Any]:
    """返回单条录音详情."""
    rec = _db(request).get_recording(recording_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="录音不存在")
    return rec


@router.get("/recordings/{recording_id}/transcription")
def get_transcription(recording_id: str, request: Request) -> dict[str, Any]:
    """返回某录音的完整转写视图."""
    return {"segments": _db(request).get_transcription_view(recording_id)}


@router.post("/scan")
def scan_directory(payload: ScanRequest, request: Request) -> dict[str, Any]:
    """扫描目录，返回支持的音频文件列表."""
    config = _config(request)
    target = Path(payload.path)
    if not target.exists() or not target.is_dir():
        raise HTTPException(status_code=400, detail="路径不存在或不是目录")

    formats = config.get("audio_formats", [".wav", ".mp3", ".m4a", ".flac"])
    files = []
    for child in target.iterdir():
        if child.is_file() and child.suffix.lower() in formats:
            files.append(
                {
                    "name": child.name,
                    "path": str(child),
                    "ext": child.suffix.lower(),
                }
            )
    return {"files": sorted(files, key=lambda x: x["name"])}


@router.post("/analyze")
def analyze_files(payload: AnalyzeRequest, request: Request) -> JobResponse:
    """为选中的音频文件启动后台分析任务.

    同一文件重复分析时按数据库状态自动续跑；
    ``force=true`` 则重置中间结果后从头重跑。
    """
    import threading

    config = _config(request)
    job_store = _job_store(request)
    job_ids: list[str] = []

    for file_path in payload.files:
        path = Path(file_path)
        if not path.exists():
            raise HTTPException(status_code=400, detail=f"文件不存在: {file_path}")

        recording_id = recording_id_from_path(file_path)
        job = job_store.create()
        job_ids.append(job.id)
        threading.Thread(
            target=run_analysis,
            args=(config, str(path), recording_id, job_store, job.id, payload.force),
            daemon=True,
        ).start()

    return JobResponse(job_ids=job_ids)


@router.get("/jobs/{job_id}")
def get_job(job_id: str, request: Request) -> dict[str, Any]:
    """查询任务当前快照."""
    job = _job_store(request).get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    return job.__dict__


async def _sse_stream(job_store: JobStore, job_id: str) -> Any:
    """SSE 进度流生成器：每 0.5s 推送一次完整任务快照，终态后断开.

    事件名与浏览器的传输层错误刻意区分：进度用 ``update``，
    业务错误（任务不存在）用 ``job_error``——若沿用 ``error``，
    会与 EventSource 原生的错误回调同名，前端无法分辨是业务错误还是断线。
    """
    while True:
        job = job_store.get(job_id)
        if job is None:
            yield 'event: job_error\ndata: {"detail": "任务不存在或已丢失"}\n\n'
            break

        data = json.dumps(job.__dict__, ensure_ascii=False, default=str)
        yield f"event: update\ndata: {data}\n\n"

        if job.status in ("completed", "failed"):
            break
        await asyncio.sleep(0.5)


@router.get("/jobs/{job_id}/stream")
def stream_job(job_id: str, request: Request) -> StreamingResponse:
    """通过 SSE 实时推送任务进度.

    即使任务不存在也不直接返回 404，而是进入流内推送 ``job_error`` 事件；
    这样前端 EventSource 能收到业务错误，不会把连接失败误报为 SSE 连接错误。
    """
    job_store = _job_store(request)
    return StreamingResponse(
        _sse_stream(job_store, job_id),
        media_type="text/event-stream",
    )


@router.get("/recordings/{recording_id}/segments/{segment_index}/audio")
def get_segment_audio(recording_id: str, segment_index: int, request: Request) -> FileResponse:
    """返回片段音频 WAV 文件."""
    seg = _db(request).get_segment_by_index(recording_id, segment_index)
    if seg is None:
        raise HTTPException(status_code=404, detail="片段不存在")
    path = Path(seg["audio_path"])
    if not path.exists():
        raise HTTPException(status_code=404, detail="音频文件不存在")
    return FileResponse(path, media_type="audio/wav")


@router.put("/recordings/{recording_id}/segments/{segment_index}/speaker")
def update_speaker(
    recording_id: str,
    segment_index: int,
    payload: SpeakerUpdateRequest,
    request: Request,
) -> OKResponse:
    """更新片段说话人标签，并把录音状态推进为已校正."""
    if payload.speaker_label not in {"user", "other"}:
        raise HTTPException(status_code=400, detail="无效的说话人标签")
    db = _db(request)
    if not db.update_speaker_label(recording_id, segment_index, payload.speaker_label):
        raise HTTPException(status_code=404, detail="片段不存在")
    db.update_recording_status(recording_id, "corrected")
    return OKResponse()


@router.put("/recordings/{recording_id}/segments/{segment_index}/text")
def update_text(
    recording_id: str,
    segment_index: int,
    payload: TextUpdateRequest,
    request: Request,
) -> OKResponse:
    """更新片段 ASR 文本，并把录音状态推进为已校正."""
    db = _db(request)
    if not db.update_asr_text(recording_id, segment_index, payload.text):
        raise HTTPException(status_code=404, detail="片段不存在")
    db.update_recording_status(recording_id, "corrected")
    return OKResponse()


@router.post("/recordings/{recording_id}/continue")
def continue_recording(recording_id: str, request: Request) -> EvaluationJobResponse:
    """继续处理一条未完成的录音，从最近完成的阶段接着跑."""
    import threading

    config = _config(request)
    job_store = _job_store(request)
    rec = _db(request).get_recording(recording_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="录音不存在")
    if rec["status"] == "evaluated":
        raise HTTPException(status_code=400, detail="该录音已全部处理完成")

    job = job_store.create()
    threading.Thread(
        target=run_analysis,
        args=(config, rec["original_path"], recording_id, job_store, job.id, False),
        daemon=True,
    ).start()
    return EvaluationJobResponse(job_id=job.id)


@router.delete("/recordings/{recording_id}")
def delete_recording(recording_id: str, request: Request) -> OKResponse:
    """删除整条录音：数据库记录与片段目录一并清理."""
    import shutil

    config = _config(request)
    db = _db(request)
    if db.get_recording(recording_id) is None:
        raise HTTPException(status_code=404, detail="录音不存在")

    db.delete_recording(recording_id)
    seg_dir = Path(config["segments_dir"]) / recording_id
    if seg_dir.exists():
        shutil.rmtree(seg_dir, ignore_errors=True)
    return OKResponse()


@router.post("/recordings/{recording_id}/reset")
def reset_recording(recording_id: str, request: Request) -> OKResponse:
    """重置录音的中间结果（片段、声纹、ASR、评测、手工修正）.

    仅保留 recordings 行，之后可通过“继续分析”从头重跑。
    """
    import shutil

    config = _config(request)
    db = _db(request)
    if db.get_recording(recording_id) is None:
        raise HTTPException(status_code=404, detail="录音不存在")

    db.reset_recording(recording_id)
    seg_dir = Path(config["segments_dir"]) / recording_id
    if seg_dir.exists():
        shutil.rmtree(seg_dir, ignore_errors=True)
    return OKResponse()


@router.post("/recordings/{recording_id}/evaluate")
def evaluate_recording(
    recording_id: str,
    request: Request,
    force: bool = False,
) -> EvaluationJobResponse:
    """为录音启动 ISE 评测任务.

    ``force=true`` 重新评测全部用户句子；默认跳过已评测句。
    """
    import threading

    config = _config(request)
    job_store = _job_store(request)
    if _db(request).get_recording(recording_id) is None:
        raise HTTPException(status_code=404, detail="录音不存在")

    job = job_store.create()
    threading.Thread(
        target=run_evaluation,
        args=(config, recording_id, job_store, job.id, force),
        daemon=True,
    ).start()
    return EvaluationJobResponse(job_id=job.id)


@router.get("/recordings/{recording_id}/evaluations")
def get_evaluations(recording_id: str, request: Request) -> dict[str, Any]:
    """返回录音的全部评测结果."""
    return {"evaluations": _db(request).get_evaluations(recording_id)}
