"""Pydantic 请求/响应模型."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ScanRequest(BaseModel):
    """扫描目录请求."""

    path: str = Field(..., description="要扫描的本地或网络挂载目录路径")


class AnalyzeRequest(BaseModel):
    """启动分析请求."""

    files: list[str] = Field(..., description="选中的音频文件绝对路径列表")
    force: bool = Field(False, description="true 时重置中间结果后从头重跑")


class SpeakerUpdateRequest(BaseModel):
    """更新说话人标签请求."""

    speaker_label: str = Field(..., description="user | other")


class TextUpdateRequest(BaseModel):
    """更新 ASR 文本请求."""

    text: str = Field(..., description="人工修正后的转写文本")


class JobResponse(BaseModel):
    """分析任务创建响应."""

    job_ids: list[str]


class EvaluationJobResponse(BaseModel):
    """评测任务创建响应."""

    job_id: str


class OKResponse(BaseModel):
    """通用成功响应."""

    ok: bool = True
