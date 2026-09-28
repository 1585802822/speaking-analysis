"""FastAPI 应用工厂."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from ..config import ensure_dirs, load_config
from ..db import Database
from .api import router as api_router
from .jobs import JobStore
from .service import recover_interrupted_recordings

logger = logging.getLogger(__name__)


def create_app(config: dict[str, Any] | None = None) -> FastAPI:
    """创建并配置 FastAPI 应用."""
    if config is None:
        config = load_config()
    ensure_dirs(config)

    app = FastAPI(title="日常录音分析工具 Web UI")
    app.state.config = config
    app.state.job_store = JobStore()

    # 服务重启后，上次中断的处理任务已丢失（JobStore 为内存存储）；
    # 把非终态的录音标记为 failed，用户可在界面点击“继续分析”续跑。
    try:
        interrupted = recover_interrupted_recordings(Database(config["db_path"]))
        if interrupted:
            logger.warning("已将 %d 条中断录音标记为 failed: %s", len(interrupted), interrupted)
    except Exception as exc:  # pragma: no cover - 启动容错
        logger.warning("恢复中断录音状态时出错: %s", exc)

    # 允许浏览器跨域访问，方便单独开发前端
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    static_dir = Path(__file__).with_name("static")
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
    app.include_router(api_router, prefix="/api")

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(static_dir / "index.html")

    # 浏览器会自动请求站点图标；返回空响应，避免日志出现 404 噪音
    @app.get("/favicon.ico", include_in_schema=False)
    def favicon() -> Response:
        return Response(status_code=204)

    return app
