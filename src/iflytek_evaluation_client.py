"""讯飞语音评测（ISE）客户端.

对一段用户朗读音频与参考文本做发音评测, 返回准确度/流利度/完整度分数,
用于判断普通话/英语发音是否标准.

鉴权方式（讯飞 WebAPI 通用规则）:
- X-Param   = base64(业务参数 JSON)
- X-CheckSum = md5(apiKey + curTime + base64Param), 32 位小写

注意: 当前封装的是讯飞语音评测 HTTP 普通版接口。讯飞官方提示普通版已下线,
后续可迁移到流式版（WebSocket, HMAC-SHA256 鉴权, 见 iFlytekStreamASRClient 的
鉴权思路）。普通版接口与鉴权字段可复用于流式版, 仅传输层不同。
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import time
from pathlib import Path
from typing import Any

import requests

logger = logging.getLogger(__name__)


class iFlytekEvaluationClient:
    """讯飞语音评测（ISE）客户端."""

    ISE_URL = "https://api.xfyun.cn/v1/service/v1/ise"

    def __init__(
        self,
        app_id: str,
        api_key: str,
        category: str = "read_sentence",
        language: str = "cn",
        timeout: int = 60,
    ) -> None:
        self.app_id = app_id
        self.api_key = api_key
        self.category = category
        self.language = language
        self.timeout = timeout

    @property
    def configured(self) -> bool:
        return bool(self.app_id) and bool(self.api_key)

    def evaluate(
        self,
        audio_path: str | Path,
        text: str,
        category: str | None = None,
        language: str | None = None,
    ) -> dict[str, Any]:
        """评测一段音频的发音, 返回归一化分数.

        Returns
        -------
        {
            "overall_score": float | None,
            "accuracy_score": float | None,
            "fluency_score": float | None,
            "integrity_score": float | None,
            "raw_response": dict,
        }
        """
        text = (text or "").strip()
        if not text:
            raise ValueError("ISE 评测需要非空参考文本")
        if not self.configured:
            raise RuntimeError("ISE 语音评测未配置（缺少 app_id / api_key）")

        audio_b64 = self._read_audio_base64(audio_path)
        lang = self._normalize_language(language or self.language)
        cat = category or self.category

        param_str = json.dumps(
            {
                "aue": "raw",  # 原生 PCM
                "result_level": "complete",
                "language": lang,
                "category": cat,
                "extra_ability": "multi_dimension",  # 多维度评分
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
        base64_param = base64.b64encode(param_str.encode("utf-8")).decode("ascii")
        cur_time = str(int(time.time()))
        check_sum = hashlib.md5(
            (self.api_key + cur_time + base64_param).encode("utf-8")
        ).hexdigest()

        headers = {
            "X-Appid": self.app_id,
            "X-CurTime": cur_time,
            "X-Param": base64_param,
            "X-CheckSum": check_sum,
            "Content-Type": "application/x-www-form-urlencoded; charset=utf-8",
        }
        data = {"text": text, "audio": audio_b64}

        resp = requests.post(self.ISE_URL, headers=headers, data=data, timeout=self.timeout)
        resp.raise_for_status()
        payload = resp.json()
        return self._normalize_result(payload)

    @staticmethod
    def _read_audio_base64(audio_path: str | Path) -> str:
        """将音频加载为 16kHz 单声道 PCM 并返回 base64."""
        import numpy as np

        y, _sr = _load_mono_16k(audio_path)
        pcm = (np.clip(y, -1.0, 1.0) * 32767).astype(np.int16).tobytes()
        return base64.b64encode(pcm).decode("ascii")

    @staticmethod
    def _normalize_language(language: str) -> str:
        """把中文/英文别名统一为讯飞 ISE 使用的语言码."""
        normalized = str(language).lower().replace("-", "").replace("_", "")
        if normalized in ("cn", "zh", "zhcn", "chinese", "mandarin"):
            return "zh_cn"
        if normalized in ("en", "enus", "english"):
            return "en_us"
        return str(language)

    def _normalize_result(self, payload: dict[str, Any]) -> dict[str, Any]:
        """解析 ISE 响应并归一化分数."""
        code = str(payload.get("code", "0"))
        if code not in ("0", ""):
            desc = payload.get("desc") or payload.get("message") or "未知错误"
            raise RuntimeError(f"讯飞 ISE 评测失败：{desc} (code={code})")

        data = payload.get("data") or {}
        scores = self._collect_scores(data)

        return {
            "overall_score": scores.get("total_score"),
            "accuracy_score": (
                scores.get("accuracy_score")
                or scores.get("phone_score")
                or scores.get("word_score")
            ),
            "fluency_score": scores.get("fluency_score"),
            "integrity_score": scores.get("integrity_score"),
            "raw_response": payload,
        }

    @staticmethod
    def _collect_scores(data: Any) -> dict[str, Any]:
        """递归遍历响应, 收集第一次出现的评测分数键."""
        found: dict[str, Any] = {}
        targets = {
            "total_score",
            "accuracy_score",
            "phone_score",
            "tone_score",
            "word_score",
            "stress_score",
            "fluency_score",
            "integrity_score",
        }

        def _walk(node: Any) -> None:
            if isinstance(node, dict):
                for key, value in node.items():
                    if key in targets and key not in found:
                        if isinstance(value, (int, float)):
                            found[key] = float(value)
                    else:
                        _walk(value)
            elif isinstance(node, list):
                for item in node:
                    _walk(item)

        _walk(data)
        return found


def _load_mono_16k(audio_path: str | Path):
    """加载音频为 16kHz 单声道数组（复用项目依赖 librosa）."""
    import librosa

    y, _sr = librosa.load(str(audio_path), sr=16000, mono=True)
    return y, 16000


def build_evaluation_client(config: dict[str, Any]) -> iFlytekEvaluationClient | None:
    """根据配置构建 ISE 客户端, 未启用或未配置时返回 None.

    密钥优先从环境变量读取（app_id_env / api_key_env）, 其次用配置里的明文值.
    """
    api_cfg = config.get("api", {}) or {}
    if not api_cfg.get("enabled"):
        return None
    eval_cfg = (api_cfg.get("iflytek", {}) or {}).get("evaluation", {}) or {}

    def _resolve(value: Any, env_name: str | None) -> str:
        if value:
            return str(value)
        if env_name:
            return os.environ.get(env_name, "")
        return ""

    client = iFlytekEvaluationClient(
        app_id=_resolve(eval_cfg.get("app_id"), eval_cfg.get("app_id_env")),
        api_key=_resolve(eval_cfg.get("api_key"), eval_cfg.get("api_key_env")),
        category=str(eval_cfg.get("category", "read_sentence")),
        language=str(eval_cfg.get("language", "cn")),
        timeout=int(api_cfg.get("timeout", 60)),
    )
    return client if client.configured else None
