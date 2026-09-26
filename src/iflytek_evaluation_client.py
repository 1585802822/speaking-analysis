"""讯飞语音评测（ISE）客户端（流式版）.

对一段用户朗读音频与参考文本做发音评测, 返回准确度/流利度/完整度分数,
用于判断普通话/英语发音是否标准.

采用讯飞「语音评测（流式版）」WebSocket 接口（HTTP 普通版已下线）:
- 接口地址: wss://ise-api.xfyun.cn/v2/open-ise
- 鉴权: HMAC-SHA256, 与语音听写（流式版）一致（见 iFlytekStreamASRClient）
- 业务参数: sub=ise, ent=cn_vip(中文)/en_vip(英文), category=题型
- 流程: ssb(参数+文本) -> auw(音频帧) -> status=2 结束, 服务端返回评测结果

评测结果可能以嵌套 JSON 或 base64(XML) 返回, 本模块统一提取
total_score / accuracy_score / phone_score / fluency_score / integrity_score 等分数.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import re
import time
import xml.etree.ElementTree as ET
from email.utils import formatdate
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlencode

import requests

logger = logging.getLogger(__name__)

# 评测结果里可能出现的分数键
_SCORE_KEYS = frozenset(
    {
        "total_score",
        "accuracy_score",
        "phone_score",
        "tone_score",
        "word_score",
        "stress_score",
        "fluency_score",
        "integrity_score",
    }
)


class iFlytekEvaluationClient:
    """讯飞语音评测（ISE）客户端（流式版）."""

    WS_URL = "wss://ise-api.xfyun.cn/v2/open-ise"
    WS_HOST = "ise-api.xfyun.cn"
    FRAME_SIZE = 1280  # 每帧 PCM 字节数（40ms @16kHz 16bit mono）

    def __init__(
        self,
        app_id: str,
        api_key: str,
        api_secret: str = "",
        category: str = "read_sentence",
        language: str = "cn",
        timeout: int = 60,
    ) -> None:
        self.app_id = app_id
        self.api_key = api_key
        self.api_secret = api_secret
        self.category = category
        self.language = language
        self.timeout = timeout

    @property
    def configured(self) -> bool:
        return bool(self.app_id) and bool(self.api_key) and bool(self.api_secret)

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
            raise RuntimeError("ISE 语音评测未配置（缺少 app_id / api_key / api_secret）")

        lang = self._normalize_language(language or self.language)
        ent = self._entity_for(lang)
        cat = category or self.category
        pcm = self._read_pcm(audio_path)

        import websocket

        try:
            ws = websocket.create_connection(self._build_url(), timeout=self.timeout)
        except Exception as exc:
            raise RuntimeError(f"讯飞 ISE 评测连接失败：{exc}")

        try:
            self._send_frames(ws, text, ent, cat, pcm)
            result = self._recv_result(ws)
        finally:
            try:
                ws.close()
            except Exception:
                pass

        return self._normalize_result({"code": "0", "data": result})

    def _build_url(self) -> str:
        """按讯飞 WebAPI 通用规则生成带鉴权参数的 WebSocket URL（HMAC-SHA256 签名）."""
        date = formatdate(timeval=None, localtime=False, usegmt=True)
        signature_origin = f"host: {self.WS_HOST}\ndate: {date}\nGET /v2/open-ise HTTP/1.1"
        signature_sha = hmac.new(
            self.api_secret.encode("utf-8"),
            signature_origin.encode("utf-8"),
            hashlib.sha256,
        ).digest()
        signature = base64.b64encode(signature_sha).decode("utf-8")
        authorization_origin = (
            f'api_key="{self.api_key}", algorithm="hmac-sha256", '
            f'headers="host date request-line", signature="{signature}"'
        )
        authorization = base64.b64encode(authorization_origin.encode("utf-8")).decode("utf-8")
        params = {
            "authorization": authorization,
            "date": date,
            "host": self.WS_HOST,
        }
        return f"{self.WS_URL}?{urlencode(params)}"

    def _send_frames(self, ws: Any, text: str, ent: str, category: str, pcm: bytes) -> None:
        """发送评测帧: ssb(参数+文本) -> auw(音频) -> status=2 结束."""
        auf = "audio/L16;rate=16000"
        # 第一帧: 参数与参考文本（文本需带 UTF-8 BOM 头）
        ws.send(
            json.dumps(
                {
                    "common": {"app_id": self.app_id},
                    "business": {
                        "sub": "ise",
                        "ent": ent,
                        "category": category,
                        "cmd": "ssb",
                        "text": "﻿" + text,
                        "tte": "utf-8",
                        "ttp_skip": True,
                        "aue": "raw",
                        "auf": auf,
                        "extra_ability": "multi_dimension",
                        "rstcd": "utf8",
                        "group": "adult",
                    },
                    "data": {"status": 0},
                },
                ensure_ascii=False,
            )
        )
        # 音频帧（每帧 40ms）
        first = True
        for pos in range(0, len(pcm), self.FRAME_SIZE):
            chunk = pcm[pos : pos + self.FRAME_SIZE]
            ws.send(
                json.dumps(
                    {
                        "business": {
                            "cmd": "auw",
                            "aus": 1 if first else 2,
                            "aue": "raw",
                            "auf": auf,
                        },
                        "data": {
                            "status": 1,
                            "data": base64.b64encode(chunk).decode("ascii"),
                        },
                    }
                )
            )
            first = False
        # 结束帧
        ws.send(
            json.dumps(
                {
                    "business": {"cmd": "auw", "aus": 4, "aue": "raw", "auf": auf},
                    "data": {"status": 2, "data": ""},
                }
            )
        )

    def _recv_result(self, ws: Any) -> dict[str, Any]:
        """接收结果帧, 直到 status=2, 返回评测结果数据."""
        for _ in range(1000):
            try:
                raw = ws.recv()
            except Exception as exc:
                raise RuntimeError(f"讯飞 ISE 评测接收结果失败：{exc}")
            try:
                resp = json.loads(raw)
            except (TypeError, json.JSONDecodeError) as exc:
                raise RuntimeError(f"讯飞 ISE 评测响应解析失败：{exc}")

            code = resp.get("code", 0)
            if code != 0:
                message = resp.get("message") or resp.get("desc") or "未知错误"
                raise RuntimeError(f"讯飞 ISE 评测失败：{message} (code={code})")

            data = resp.get("data") or {}
            if data.get("status") == 2:
                result = data.get("result")
                if result is None:
                    result = data.get("data")
                return self._parse_result_field(result)
        raise RuntimeError("讯飞 ISE 评测未收到最终结果")

    def _parse_result_field(self, field: Any) -> dict[str, Any]:
        """把最终结果字段解析为可供 _collect_scores 提取的 dict.

        支持三种形态: 结构化 JSON dict / base64(JSON) / base64(XML).
        """
        if isinstance(field, dict):
            return field
        if isinstance(field, str):
            decoded = self._maybe_b64decode(field)
            try:
                obj = json.loads(decoded)
                if isinstance(obj, dict):
                    return obj
            except (json.JSONDecodeError, ValueError):
                pass
            return self._extract_scores_from_xml(decoded)
        return {}

    @staticmethod
    def _maybe_b64decode(value: str) -> str:
        """尝试 base64 解码, 失败则原样返回."""
        try:
            return base64.b64decode(value).decode("utf-8")
        except Exception:
            return value

    @staticmethod
    def _extract_scores_from_xml(xml_text: str) -> dict[str, Any]:
        """从评测结果 XML 中提取分数属性为扁平 dict."""
        found: dict[str, Any] = {}
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError:
            return found
        for elem in root.iter():
            for key, value in elem.attrib.items():
                if key in _SCORE_KEYS and key not in found:
                    try:
                        found[key] = float(value)
                    except ValueError:
                        pass
        return found

    @staticmethod
    def _entity_for(language: str) -> str:
        """语言码 -> 讯飞 ISE 的 ent 参数."""
        return "en_vip" if str(language).lower().startswith("en") else "cn_vip"

    @staticmethod
    def _read_pcm(audio_path: str | Path) -> bytes:
        """将音频加载为 16kHz 单声道 int16 PCM 字节流."""
        import numpy as np

        y, _sr = _load_mono_16k(audio_path)
        return (np.clip(y, -1.0, 1.0) * 32767).astype(np.int16).tobytes()

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
        """解析评测结果并归一化分数."""
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
        """递归遍历结果, 收集第一次出现的评测分数键."""
        found: dict[str, Any] = {}

        def _walk(node: Any) -> None:
            if isinstance(node, dict):
                for key, value in node.items():
                    if key in _SCORE_KEYS and key not in found:
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


class iFlytekVoiceInsightClient:
    """讯飞 Spark VAA 语音分析客户端.

    对音频做大模型分析（发音评测等）, 通过自定义 prompt 让模型输出 JSON 分数.

    流程: POST /api/v1/voice-insight/create 创建任务获取 task_id ->
    轮询 GET /api/v1/voice-insight/tasks/{task_id} 直到 Finish/Error ->
    解析 sub_task_results[].result 中的分数.

    鉴权（HMAC-SHA256）: 与讯飞 WebAPI 一致, host/date/authorization 通过 URL
    查询参数传递. 注意: 本接口鉴权只需 api_key + api_secret（不使用 app_id）.

    限制: 接口只接收音频外链 audioFileURL, 本地文件需先转换为公网可访问的 URL.

    文档: https://www.xfyun.cn/doc/spark/spark_asr/spark_VAA.html
    """

    BASE_URL = "http://spark-openapi.cn-huabei-1.xf-yun.com"
    HOST = "spark-openapi.cn-huabei-1.xf-yun.com"
    CREATE_PATH = "/api/v1/voice-insight/create"

    # 发音评测 prompt: {text} 为参考文本, ${chat_content} 为服务端替换的转写内容
    PRONUNCIATION_PROMPT = (
        "请对以下语音内容的发音质量进行评测。参考文本为：{text}。"
        "语音转写内容为：${chat_content}。"
        "请从发音准确度(accuracy)、流利度(fluency)、完整度(integrity)、"
        "总体表现(overall)四个维度各打一个 0-100 的整数分，"
        "只返回一个 JSON 对象，不要输出任何其它文字，格式示例："
        '{"overall": 85, "accuracy": 82, "fluency": 80, "integrity": 90}'
    )

    def __init__(
        self,
        api_key: str,
        api_secret: str = "",
        model_code: str = "xdeepseekv31",
        timeout: int = 120,
        audio_url_resolver: Callable[[Path], str] | None = None,
    ) -> None:
        self.api_key = api_key
        self.api_secret = api_secret
        self.model_code = model_code
        self.timeout = timeout
        self.audio_url_resolver = audio_url_resolver

    @property
    def configured(self) -> bool:
        return bool(self.api_key) and bool(self.api_secret)

    def evaluate(
        self,
        audio_path: str | Path,
        text: str,
        category: str | None = None,
        language: str | None = None,
    ) -> dict[str, Any]:
        """分析一段音频的发音, 返回归一化分数.

        audio_path 可以是公网可访问的音频 URL, 或本地文件路径（需配置
        audio_url_resolver 将其转换为外链）.
        """
        text = (text or "").strip()
        if not text:
            raise ValueError("语音分析需要非空参考文本")
        if not self.configured:
            raise RuntimeError("语音分析未配置（缺少 api_key / api_secret）")

        audio_file_url = self._resolve_audio_url(audio_path)
        prompt = self.PRONUNCIATION_PROMPT.replace("{text}", text)
        task_id = self._create_task(audio_file_url, prompt)
        data = self._poll_result(task_id)
        return self._normalize_result(data)

    def _resolve_audio_url(self, audio_path: str | Path) -> str:
        """把本地文件转换为公网音频外链."""
        raw = str(audio_path)
        if raw.startswith(("http://", "https://")):
            return raw
        if self.audio_url_resolver is not None:
            return self.audio_url_resolver(Path(raw))
        raise RuntimeError(
            "Spark VAA 需要音频外链 audioFileURL，但收到本地文件且未配置外链解析器；"
            "请传入公网可访问的音频 URL 或注入 audio_url_resolver"
        )

    def _build_url(self, method: str, path: str) -> str:
        """生成带鉴权参数的 URL（HMAC-SHA256, host/date/authorization 查询参数）."""
        date = formatdate(timeval=None, localtime=False, usegmt=True)
        signature_origin = f"host: {self.HOST}\ndate: {date}\n{method} {path} HTTP/1.1"
        signature_sha = hmac.new(
            self.api_secret.encode("utf-8"),
            signature_origin.encode("utf-8"),
            hashlib.sha256,
        ).digest()
        signature = base64.b64encode(signature_sha).decode("utf-8")
        authorization_origin = (
            f'api_key="{self.api_key}", algorithm="hmac-sha256", '
            f'headers="host date request-line", signature="{signature}"'
        )
        authorization = base64.b64encode(authorization_origin.encode("utf-8")).decode("utf-8")
        params = {"authorization": authorization, "date": date, "host": self.HOST}
        return f"{self.BASE_URL}{path}?{urlencode(params)}"

    def _create_task(self, audio_file_url: str, prompt: str) -> str:
        """创建语音分析任务, 返回 task_id."""
        body = {
            "taskType": "audioFile",
            "audioFileURL": audio_file_url,
            "audioParams": {},
            "modelCode": self.model_code,
            "llmParams": {"enableThinking": False, "enableJsonResponse": True},
            "subTasks": [
                {
                    "is_customize": True,
                    "name": "发音评测",
                    "customize_prompt": prompt,
                }
            ],
            "callBackUrl": "",
        }
        url = self._build_url("POST", self.CREATE_PATH)
        resp = requests.post(url, json=body, timeout=self.timeout)
        resp.raise_for_status()
        payload = resp.json()
        code = payload.get("code")
        if code != 0:
            message = payload.get("message") or "未知错误"
            raise RuntimeError(f"讯飞语音分析创建任务失败：{message} (code={code})")
        task_id = (payload.get("data") or {}).get("task_id")
        if not task_id:
            raise RuntimeError("讯飞语音分析创建任务失败：响应中未返回 task_id")
        return str(task_id)

    def _poll_result(self, task_id: str) -> dict[str, Any]:
        """轮询任务结果, 直到 Finish 或 Error."""
        deadline = time.time() + self.timeout
        while time.time() < deadline:
            url = self._build_url("GET", f"/api/v1/voice-insight/tasks/{task_id}")
            resp = requests.get(url, timeout=self.timeout)
            resp.raise_for_status()
            payload = resp.json()
            code = payload.get("code")
            if code != 0:
                message = payload.get("message") or "未知错误"
                raise RuntimeError(f"讯飞语音分析查询失败：{message} (code={code})")
            data = payload.get("data") or {}
            status = str(data.get("status", "")).lower()
            if status == "finish":
                return data
            if status == "error":
                detail = (
                    data.get("error_message")
                    or data.get("errorMsg")
                    or data.get("message")
                    or data.get("error")
                    or data.get("failReason")
                    or str(data)[:500]
                )
                raise RuntimeError(f"讯飞语音分析任务失败：{detail}")
            logger.debug("讯飞语音分析处理中, task_id=%s, status=%s", task_id, status)
            time.sleep(3.0)
        raise RuntimeError("讯飞语音分析查询超时")

    def _normalize_result(self, data: dict[str, Any]) -> dict[str, Any]:
        """解析子任务结果并归一化为统一分数."""
        scores = self._collect_scores(self._extract_result_payload(data))
        return {
            "overall_score": scores.get("overall") or scores.get("total_score"),
            "accuracy_score": (
                scores.get("accuracy")
                or scores.get("accuracy_score")
                or scores.get("phone_score")
                or scores.get("word_score")
            ),
            "fluency_score": scores.get("fluency") or scores.get("fluency_score"),
            "integrity_score": scores.get("integrity") or scores.get("integrity_score"),
            "raw_response": data,
        }

    @staticmethod
    def _extract_result_payload(data: dict[str, Any]) -> Any:
        """从查询结果中提取第一个子任务的 result 字段."""
        for item in data.get("sub_task_results") or []:
            result = item.get("result")
            if result:
                return result
        return None

    @staticmethod
    def _collect_scores(result: Any) -> dict[str, Any]:
        """从子任务 result（dict/list/str）中递归收集分数."""
        if result is None:
            return {}
        if isinstance(result, str):
            result = iFlytekVoiceInsightClient._parse_json_like(result)

        score_keys = {
            "overall",
            "accuracy",
            "fluency",
            "integrity",
            "total_score",
            "accuracy_score",
            "phone_score",
            "word_score",
            "fluency_score",
            "integrity_score",
        }
        found: dict[str, Any] = {}

        def _walk(node: Any) -> None:
            if isinstance(node, dict):
                for key, value in node.items():
                    if key in score_keys and key not in found:
                        if isinstance(value, (int, float)):
                            found[key] = float(value)
                    else:
                        _walk(value)
            elif isinstance(node, list):
                for item in node:
                    _walk(item)

        _walk(result)
        return found

    @staticmethod
    def _parse_json_like(text: str) -> Any:
        """从文本中提取 JSON 对象/列表, 支持 markdown 代码块与前后赘述."""
        text = (text or "").strip()
        if text.startswith("```"):
            text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
            text = re.sub(r"\s*```$", "", text)
        try:
            return json.loads(text)
        except (json.JSONDecodeError, TypeError):
            pass
        for open_ch, close_ch in (("{", "}"), ("[", "]")):
            start = text.find(open_ch)
            end = text.rfind(close_ch)
            if start != -1 and end != -1 and end > start:
                try:
                    return json.loads(text[start : end + 1])
                except (json.JSONDecodeError, TypeError):
                    pass
        return None


def build_evaluation_client(
    config: dict[str, Any],
) -> iFlytekEvaluationClient | iFlytekVoiceInsightClient | None:
    """根据配置构建发音评测客户端, 未启用或未配置时返回 None.

    密钥优先从环境变量读取（app_id_env / api_key_env / api_secret_env）,
    其次用配置里的明文值. evaluation.mode 决定使用哪种实现:
    - ise（默认）: 讯飞语音评测流式版（WebSocket + HMAC-SHA256）
    - voice_insight: 讯飞 Spark VAA 语音分析接口（HTTP + HMAC-SHA256）
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

    mode = str(eval_cfg.get("mode", "ise")).strip().lower()
    if mode == "voice_insight":
        client = iFlytekVoiceInsightClient(
            api_key=_resolve(eval_cfg.get("api_key"), eval_cfg.get("api_key_env")),
            api_secret=_resolve(eval_cfg.get("api_secret"), eval_cfg.get("api_secret_env")),
            model_code=str(eval_cfg.get("model_code", "xdeepseekv31")),
            timeout=int(api_cfg.get("timeout", 120)),
        )
        return client if client.configured else None

    client = iFlytekEvaluationClient(
        app_id=_resolve(eval_cfg.get("app_id"), eval_cfg.get("app_id_env")),
        api_key=_resolve(eval_cfg.get("api_key"), eval_cfg.get("api_key_env")),
        api_secret=_resolve(eval_cfg.get("api_secret"), eval_cfg.get("api_secret_env")),
        category=str(eval_cfg.get("category", "read_sentence")),
        language=str(eval_cfg.get("language", "cn")),
        timeout=int(api_cfg.get("timeout", 60)),
    )
    return client if client.configured else None
