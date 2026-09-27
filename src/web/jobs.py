"""Web 后台任务状态管理."""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Job:
    """后台任务状态."""

    id: str
    status: str = "pending"  # pending | running | completed | failed
    message: str = ""
    progress: float = 0.0
    result: Any = None
    error: str | None = None
    created_at: float = field(default_factory=time.time)
    finished_at: float | None = None


class JobStore:
    """内存任务存储，适合 demo 场景."""

    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def create(self) -> Job:
        """创建新任务并返回."""
        job = Job(id=uuid.uuid4().hex[:12])
        with self._lock:
            self._jobs[job.id] = job
        return job

    def get(self, job_id: str) -> Job | None:
        """按 ID 查询任务."""
        with self._lock:
            return self._jobs.get(job_id)

    def update(self, job_id: str, **kwargs: Any) -> None:
        """更新任务字段."""
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            for key, value in kwargs.items():
                if hasattr(job, key):
                    setattr(job, key, value)

    def set_finished(
        self,
        job_id: str,
        status: str,
        result: Any = None,
        error: str | None = None,
        message: str = "",
    ) -> None:
        """标记任务结束."""
        self.update(
            job_id,
            status=status,
            result=result,
            error=error,
            message=message,
            progress=1.0 if status == "completed" else 0.0,
            finished_at=time.time(),
        )
