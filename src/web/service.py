"""流水线阶段编排服务.

把原有 Pipeline.process 拆成可单独调用、可断点续跑的分析/评测任务，
供 Web API 在后台线程中执行。

续跑原则：
- 每个阶段开始前写 run_history(started)，成功后写 completed，
  失败时写 failed 并把 recordings.status 置为 failed；
- 再次运行时按 recordings.status 跳过已完成阶段；
- 人工修正过的说话人标签 / ASR 文本默认受保护，不会被重跑覆盖。
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, Callable

from ..audio_adapter import IFLYTEK_MAX_DURATION_SEC, IFLYTEK_MAX_FILE_SIZE_MB, validate_input
from ..db import Database
from ..enrollment import EnrollmentManager
from ..preprocessor import Preprocessor
from ..pronunciation_analyzer import PronunciationAnalyzer
from ..sentence_segmenter import SentenceSegmenter
from ..speaker_separator import SpeakerSeparator
from ..transcriber import Transcriber
from ..types import Segment, Utterance
from .jobs import JobStore

logger = logging.getLogger(__name__)

# 阶段顺序：数字越大处理得越完整
_STAGE_RANK = {
    None: 0,
    "new": 0,
    "segmented": 1,
    "diarized": 2,
    "transcribed": 3,
    "corrected": 4,
    "evaluated": 5,
}

# run_history 阶段名 → 对应录音状态
_STAGE_TO_STATUS = {
    "segment": "segmented",
    "diarize": "diarized",
    "asr": "transcribed",
    "evaluate": "evaluated",
}

# 终态集合：处于这些状态时不视为“处理中断”
# transcribed / corrected 是分析阶段的正常终点（评测是可选动作），
# 否则每次服务重启都会把已完成分析的录音误标为 failed
_FINAL_STATUSES = (None, "new", "transcribed", "corrected", "evaluated", "failed")

# 阶段名 → 中文标签，用于失败原因与进度提示
_STAGE_LABEL = {
    "segment": "句子切分",
    "diarize": "声纹分离",
    "asr": "语音转写",
    "evaluate": "发音评测",
}

# 重试退避基数（秒）；模块级常量便于测试时 patch 为 0
_RETRY_BASE_DELAY = 2.0


def _stage_rank(status: str | None) -> int:
    return _STAGE_RANK.get(status, 0)


def _load_segments_from_db(db: Database, recording_id: str) -> list[Segment]:
    """从数据库加载片段及声纹标签，用于续跑时跳过切分/分离阶段."""
    segments: list[Segment] = []
    for row in db.get_transcription_view(recording_id):
        seg = Segment(
            start=row["start_sec"],
            end=row["end_sec"],
            segment_index=row["segment_index"],
            recording_id=recording_id,
        )
        # 数据库读取层已把历史 needs_review 归一化为 other
        label = row.get("speaker_label")
        if label in ("user", "other"):
            seg.speaker_label = label
            seg.is_user = label == "user"
            seg.needs_review = False
            seg.speaker_confidence = row.get("speaker_confidence")
        segments.append(seg)
    return segments


def _last_completed_status(db: Database, recording_id: str) -> str | None:
    """从运行历史找最近一次完成的阶段，映射回录音状态."""
    for item in reversed(db.get_run_history(recording_id)):
        if item.get("status") == "completed" and item.get("stage") in _STAGE_TO_STATUS:
            return _STAGE_TO_STATUS[item["stage"]]
    return None


def _resume_status(db: Database, recording_id: str, status: str | None) -> str | None:
    """计算续跑起点：failed 状态回退到最近一次完成的阶段."""
    if status == "failed":
        return _last_completed_status(db, recording_id)
    return status


def _run_stage_with_retry(
    db: Database,
    recording_id: str,
    stage: str,
    job_store: JobStore,
    job_id: str,
    fn: Callable[[], None],
    max_retries: int,
) -> None:
    """执行单个阶段，失败按指数退避重试；每次尝试都写 run_history.

    Args:
        fn: 阶段主体，无参闭包（数据库句柄等由闭包捕获）。
        max_retries: 首次尝试之外的额外重试次数；耗尽后把最后一次异常抛出，
            交由 run_analysis 的顶层 except 收尾。

    说明：重试轨迹完整写入 run_history（每次 started/failed），
    而 _last_completed_status 只认 completed，因此断点续跑不受影响。
    """
    delay = _RETRY_BASE_DELAY
    for attempt in range(max_retries + 1):
        db.save_run_history(recording_id, stage, "started")
        try:
            fn()
        except Exception as exc:
            db.save_run_history(
                recording_id,
                stage,
                "failed",
                error_message=f"第 {attempt + 1} 次尝试: {exc}",
            )
            if attempt >= max_retries:
                raise
            label = _STAGE_LABEL.get(stage, stage)
            logger.warning(
                "阶段 %s 第 %d 次失败，%.0f 秒后重试: %s", stage, attempt + 1, delay, exc
            )
            job_store.update(
                job_id,
                message=f"{label}失败，{delay:.0f} 秒后重试（{attempt + 1}/{max_retries}）...",
            )
            time.sleep(delay)
            delay *= 2
        else:
            db.save_run_history(recording_id, stage, "completed")
            return


def run_analysis(
    config: dict[str, Any],
    audio_path: str,
    recording_id: str,
    job_store: JobStore,
    job_id: str,
    force: bool = False,
) -> None:
    """对单个文件执行预处理 → 声纹分离 → ASR，支持断点续跑.

    Args:
        force: True 时重置该录音全部中间结果后从头重跑
        （人工修正也会被清除）；False 时按状态跳过已完成阶段。
    """
    db: Database | None = None
    current_stage = "segment"
    try:
        db = Database(config["db_path"])
        existing = db.get_recording(recording_id)
        status = existing["status"] if existing else None

        if force:
            db.reset_recording(recording_id)
            status = None
        elif status == "evaluated":
            job_store.set_finished(
                job_id,
                "completed",
                result={"recording_id": recording_id},
                message="该录音已处理完成，如需重跑请选择强制重新分析",
            )
            return
        else:
            status = _resume_status(db, recording_id, status)

        path = Path(audio_path)
        # run_history 外键依赖 recordings 行，新录音先占位插入
        if db.get_recording(recording_id) is None:
            db.ensure_recording(recording_id, str(path))
        job_store.update(job_id, status="running", message="校验音频...", progress=0.03)
        validate_input(
            path,
            max_duration_sec=IFLYTEK_MAX_DURATION_SEC,
            max_file_size_mb=IFLYTEK_MAX_FILE_SIZE_MB,
        )

        # 阶段 1：句子切分（本地预处理，失败多为数据问题，只重试 1 次）
        if _stage_rank(status) < 1:
            current_stage = "segment"
            job_store.update(job_id, message="正在切分句子...", progress=0.2)

            def _do_segment() -> None:
                nonlocal segments
                segmenter = SentenceSegmenter(config)
                preprocessor = Preprocessor(config)
                duration_sec = preprocessor.get_duration(path)
                segments, audio_paths, _meta = segmenter.segment(path, recording_id)
                db.save_recording(
                    recording_id,
                    str(path),
                    duration_sec,
                    segmenter.sample_rate,
                    "segmented",
                )
                db.save_segments(recording_id, segments, audio_paths)
                db.cleanup_orphan_segments(
                    recording_id,
                    [s.segment_index for s in segments if s.segment_index is not None],
                )

            _run_stage_with_retry(
                db, recording_id, "segment", job_store, job_id, _do_segment, max_retries=1
            )
        else:
            job_store.update(job_id, message="已有切分结果，跳过切分...", progress=0.25)
            segments = _load_segments_from_db(db, recording_id)

        # 阶段 2：声纹初次分离（涉及模型加载，重试 2 次）
        if _stage_rank(status) < 2:
            current_stage = "diarize"
            job_store.update(job_id, message="正在声纹分离...", progress=0.45)

            def _do_diarize() -> None:
                nonlocal segments
                enrollment = EnrollmentManager(config)
                separator = SpeakerSeparator(config)
                voiceprint = enrollment.load_voiceprint()
                if voiceprint is None:
                    # 没有注册声纹时全部标记为 other，避免阻塞流程
                    for seg in segments:
                        seg.speaker_label = "other"
                        seg.is_user = False
                        seg.speaker_confidence = 0.0
                        seg.confidence = 0.0
                        seg.needs_review = False
                    separator._save_diarization_json(recording_id, segments)
                    db.save_diarization(recording_id, segments)
                else:
                    segments = separator.separate(segments, recording_id, voiceprint)
                db.update_recording_status(recording_id, "diarized")

            _run_stage_with_retry(
                db, recording_id, "diarize", job_store, job_id, _do_diarize, max_retries=2
            )
        else:
            job_store.update(job_id, message="已有分离结果，跳过声纹分离...", progress=0.5)
            segments = _load_segments_from_db(db, recording_id)

        # 阶段 3：ASR 转写（人工修正过的文本受保护；涉及模型/外部 API，重试 2 次）
        if _stage_rank(status) < 3:
            current_stage = "asr"
            job_store.update(job_id, message="正在转写...", progress=0.75)

            def _do_asr() -> None:
                transcriber = Transcriber(config)
                transcriptions = transcriber.transcribe_segments(path, segments, recording_id)
                db.save_asr_results(recording_id, transcriptions, protect_manual=not force)

            _run_stage_with_retry(
                db, recording_id, "asr", job_store, job_id, _do_asr, max_retries=2
            )
        else:
            job_store.update(job_id, message="已有转写结果，跳过 ASR...", progress=0.9)

        # 收尾：人工修正过的录音状态记为 corrected
        if db.has_manual_asr(recording_id) or db.has_manual_speaker_corrections(recording_id):
            db.update_recording_status(recording_id, "corrected")
        else:
            db.update_recording_status(recording_id, "transcribed")

        job_store.set_finished(
            job_id,
            "completed",
            result={"recording_id": recording_id},
            message="分析完成",
        )
    except Exception as exc:
        logger.exception("分析任务失败: %s", audio_path)
        stage_label = _STAGE_LABEL.get(current_stage, current_stage)
        reason = f"{stage_label}阶段失败：{exc}"
        if db is not None:
            try:
                db.mark_recording_failed(recording_id, reason)
                db.save_run_history(recording_id, current_stage, "failed", error_message=str(exc))
            except Exception as db_exc:  # pragma: no cover - 数据库异常不掩盖原始错误
                logger.warning("写入失败状态时出错: %s", db_exc)
        job_store.set_finished(
            job_id,
            "failed",
            error=str(exc),
            message=f"分析失败：{reason}",
        )


def run_evaluation(
    config: dict[str, Any],
    recording_id: str,
    job_store: JobStore,
    job_id: str,
    force: bool = False,
) -> None:
    """对录音中已确认的用户语音逐句进行 ISE 评测，支持续跑.

    Args:
        force: True 时重新评测全部用户句子；False 时跳过已评测句。
    """
    db: Database | None = None
    try:
        db = Database(config["db_path"])
        recording = db.get_recording(recording_id)
        if recording is None:
            raise ValueError("录音不存在")

        job_store.update(job_id, status="running", message="正在加载数据...", progress=0.1)
        rows = db.get_transcription_view(recording_id)
        user_rows = [row for row in rows if row.get("speaker_label") == "user" and row.get("text")]
        if not user_rows:
            job_store.set_finished(
                job_id,
                "completed",
                result={"recording_id": recording_id},
                message="没有用户语音需要评测",
            )
            return

        evaluated = set() if force else db.get_evaluated_segment_indexes(recording_id, "ise")
        todo = [row for row in user_rows if row["segment_index"] not in evaluated]
        if not todo:
            db.update_recording_status(recording_id, "evaluated")
            job_store.set_finished(
                job_id,
                "completed",
                result={"recording_id": recording_id},
                message="全部句子已评测，无需重复评测",
            )
            return

        db.save_run_history(recording_id, "evaluate", "started")
        analyzer = PronunciationAnalyzer(config)
        audio_path = recording["original_path"]
        total = len(todo)
        failed_indexes: list[int] = []

        for idx, row in enumerate(todo):
            progress = 0.1 + 0.8 * (idx + 1) / total
            job_store.update(
                job_id,
                message=f"正在评测第 {idx + 1}/{total} 句...",
                progress=progress,
            )
            utterance = Utterance(
                text=row["text"],
                start=row["start_sec"],
                end=row["end_sec"],
                words=row.get("words", []),
            )
            try:
                result = analyzer.analyze([utterance], audio_path)
            except Exception as exc:  # 单句评测失败不影响后续句子
                logger.warning("单句评测失败 [%s]: %s", row["segment_index"], exc)
                # 落库失败行：不计入已评测集合，下次评测会自动重跑该句
                db.save_evaluation(
                    recording_id,
                    row["segment_index"],
                    "ise",
                    {},
                    status="failed",
                    error_message=str(exc),
                )
                failed_indexes.append(row["segment_index"])
                continue
            if result.findings:
                db.save_evaluation(
                    recording_id,
                    row["segment_index"],
                    "ise",
                    {"findings": result.findings},
                )

        db.update_recording_status(recording_id, "evaluated")
        db.save_run_history(recording_id, "evaluate", "completed")
        if failed_indexes:
            message = f"ISE 评测完成，{len(failed_indexes)}/{total} 句未评上，可重新评测重试失败句"
        else:
            message = "ISE 评测完成"
        job_store.set_finished(
            job_id,
            "completed",
            result={"recording_id": recording_id},
            message=message,
        )
    except Exception as exc:
        logger.exception("ISE 评测失败: %s", recording_id)
        if db is not None:
            try:
                db.mark_recording_failed(recording_id, f"{_STAGE_LABEL['evaluate']}阶段失败：{exc}")
                db.save_run_history(recording_id, "evaluate", "failed", error_message=str(exc))
            except Exception as db_exc:  # pragma: no cover
                logger.warning("写入失败状态时出错: %s", db_exc)
        job_store.set_finished(
            job_id,
            "failed",
            error=str(exc),
            message=f"评测失败: {exc}",
        )


def recover_interrupted_recordings(db: Database) -> list[str]:
    """服务启动时把上次遗留的非终态录音标记为失败，返回受影响 ID 列表.

    JobStore 是内存存储，服务重启后正在运行的任务已丢失；
    以数据库状态为准，把中断的录音标记为 failed，
    用户可在历史列表点击“继续分析”从最近完成的阶段继续。
    """
    affected: list[str] = []
    for rec in db.list_recordings():
        status = rec.get("status")
        if status not in _FINAL_STATUSES:
            db.mark_recording_failed(
                rec["id"],
                "服务重启导致处理中断，请点击“继续分析”继续处理",
            )
            affected.append(rec["id"])
    return affected
