"""讯飞开放平台语音转写客户端.

- iFlytekLongASRClient: 录音文件转写（标准版）, 上传 -> 轮询 -> 解析.
- iFlytekStreamASRClient: 语音听写（流式版）, WebSocket 流式听写, 长音频自动切片.
两者均输出项目统一的 Utterance/Word 类型.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import time
from email.utils import formatdate
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import requests

from .types import Utterance, Word

logger = logging.getLogger(__name__)


class iFlytekLongASRClient:
    """讯飞长音频转写客户端.

    文档: https://www.xfyun.cn/doc/asr/long_audio_transcription/API.html
    """

    UPLOAD_URL = "https://raasr.xfyun.cn/v2/api/upload"
    RESULT_URL = "https://raasr.xfyun.cn/v2/api/getResult"

    def __init__(
        self,
        app_id: str,
        api_secret: str,
        language: str = "cn",
        timeout: int = 120,
    ) -> None:
        self.app_id = app_id
        self.api_secret = api_secret
        self.language = language
        self.timeout = timeout

    @property
    def configured(self) -> bool:
        return bool(self.app_id) and bool(self.api_secret)

    def transcribe(
        self, audio_path: str | Path, language: str | None = None
    ) -> list[Utterance]:
        """转写音频文件, 返回带词级时间戳的句子列表."""
        audio_path = Path(audio_path)
        lang = self._resolve_language(language or self.language)
        order_id = self._upload(audio_path, lang)
        payload = self._poll_result(order_id)
        return self._parse_result(payload)

    @staticmethod
    def _resolve_language(language: str | None) -> str:
        if not language:
            return "cn"
        normalized = str(language).lower().replace("-", "").replace("_", "")
        mapping = {
            "zh": "cn",
            "zhcn": "cn",
            "zh_cn": "cn",
            "chinese": "cn",
            "en": "en",
            "english": "en",
        }
        return mapping.get(normalized, str(language))

    def _make_signa(self, ts: str) -> str:
        """生成讯飞接口签名.

        signa = base64(HmacSHA1(MD5(appid + ts).hexdigest(), api_secret))
        """
        base = f"{self.app_id}{ts}"
        md5_hex = hashlib.md5(base.encode("utf-8")).hexdigest()
        signa = base64.b64encode(
            hmac.new(
                self.api_secret.encode("utf-8"),
                md5_hex.encode("utf-8"),
                hashlib.sha1,
            ).digest()
        ).decode("utf-8")
        return signa

    def _upload(self, audio_path: Path, language: str) -> str:
        """上传音频文件, 返回 orderId."""
        ts = str(int(time.time()))
        file_size = audio_path.stat().st_size
        # duration 传毫秒, 服务端当前未强校验
        duration_ms = int(self._audio_duration_ms(audio_path))
        params = {
            "appid": self.app_id,
            "ts": ts,
            "signa": self._make_signa(ts),
            "language": language,
            "fileName": audio_path.name,
            "fileSize": file_size,
            "duration": duration_ms,
            "audioMode": "fileStream",
        }
        with open(audio_path, "rb") as f:
            audio_bytes = f.read()

        resp = requests.post(
            self.UPLOAD_URL,
            params=params,
            data=audio_bytes,
            headers={"Content-Type": "application/octet-stream"},
            timeout=self.timeout,
        )
        resp.raise_for_status()
        data = self._parse_response(resp.json())
        order_id = data.get("orderId")
        if not order_id:
            raise RuntimeError("讯飞 ASR 上传失败：响应中未返回 orderId")
        return str(order_id)

    @staticmethod
    def _audio_duration_ms(audio_path: Path) -> float:
        """通过文件头估算音频时长（失败时返回 0）."""
        try:
            import soundfile as sf

            info = sf.info(str(audio_path))
            return info.duration * 1000
        except Exception:
            return 0.0

    def _poll_result(self, order_id: str) -> dict[str, Any]:
        """轮询转写结果, 直到完成或超时."""
        deadline = time.time() + self.timeout
        while time.time() < deadline:
            ts = str(int(time.time()))
            params = {
                "appid": self.app_id,
                "ts": ts,
                "signa": self._make_signa(ts),
                "orderId": order_id,
            }
            resp = requests.post(
                self.RESULT_URL,
                params=params,
                timeout=self.timeout,
            )
            resp.raise_for_status()
            payload = self._parse_response(resp.json())

            status = payload.get("status")
            if status in (4, "4"):
                return payload
            if status in (-1, "-1"):
                raise RuntimeError("讯飞 ASR 转写失败：服务端返回转写失败状态")

            logger.debug("讯飞 ASR 转写中, orderId=%s, status=%s", order_id, status)
            time.sleep(1.0)

        raise RuntimeError("讯飞 ASR 转写超时")

    def _parse_response(self, response: dict[str, Any]) -> dict[str, Any]:
        """解析接口外层响应, 处理 data 为 JSON 字符串的情况."""
        ok = response.get("ok")
        code = response.get("code")
        if ok is not None and ok not in (0, "0"):
            failed = response.get("failed") or response.get("err_msg") or "未知错误"
            raise RuntimeError(f"讯飞 ASR 接口错误：{failed}")
        if code is not None and code not in (0, "0"):
            failed = response.get("message") or response.get("err_msg") or "未知错误"
            raise RuntimeError(f"讯飞 ASR 接口错误：{failed}")

        data = response.get("data") or response.get("content")
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except json.JSONDecodeError as exc:
                raise RuntimeError(f"讯飞 ASR 响应数据解析失败：{exc}")
        if not isinstance(data, dict):
            raise RuntimeError("讯飞 ASR 响应数据格式错误")
        return data

    def _parse_result(self, payload: dict[str, Any]) -> list[Utterance]:
        """解析 orderResult/lattice/json_1best/st/rt/ws/cw 结构."""
        order_result_raw = payload.get("orderResult")
        if not order_result_raw:
            return []
        if isinstance(order_result_raw, dict):
            order_result = order_result_raw
        else:
            order_result = json.loads(order_result_raw)

        utterances: list[Utterance] = []
        for item in order_result.get("lattice", []):
            json_1best_raw = item.get("json_1best")
            if not json_1best_raw:
                continue
            if isinstance(json_1best_raw, dict):
                json_1best = json_1best_raw
            else:
                json_1best = json.loads(json_1best_raw)

            st = json_1best.get("st", {})
            sentence_start = int(st.get("bg", 0)) / 1000.0
            sentence_end = int(st.get("ed", 0)) / 1000.0

            rt_list = st.get("rt", [])
            if not rt_list:
                continue

            text_parts: list[str] = []
            words: list[Word] = []
            for ws in rt_list[0].get("ws", []):
                wb = int(ws.get("wb", 0))
                we = int(ws.get("we", 0))
                word_start = sentence_start + wb / 100.0
                word_end = sentence_start + we / 100.0

                for cw in ws.get("cw", []):
                    w_text = str(cw.get("w", ""))
                    if not w_text:
                        continue
                    text_parts.append(w_text)
                    if cw.get("wp") != "p":
                        words.append(
                            Word(
                                text=w_text,
                                start=word_start,
                                end=word_end,
                                confidence=None,
                            )
                        )

            text = "".join(text_parts)
            if text:
                utterances.append(
                    Utterance(
                        text=text,
                        start=sentence_start,
                        end=sentence_end,
                        words=words,
                    )
                )

        return utterances


class iFlytekStreamASRClient:
    """讯飞语音听写（流式版）WebSocket 客户端.

    单会话最长 60s, 长音频内部切成 <=55s 的块依次识别,
    并按块偏移修正时间戳后合并结果.

    文档: https://www.xfyun.cn/doc/asr/voicedictation/API.html
    """

    WS_URL = "wss://iat-api.xfyun.cn/v2/iat"
    WS_HOST = "iat-api.xfyun.cn"
    CHUNK_SECONDS = 55
    FRAME_SIZE = 1280  # 每帧 PCM 字节数（40ms @16kHz 16bit mono）

    def __init__(
        self,
        app_id: str,
        api_key: str,
        api_secret: str,
        language: str = "zh_cn",
        sample_rate: int = 16000,
        timeout: int = 120,
    ) -> None:
        self.app_id = app_id
        self.api_key = api_key
        self.api_secret = api_secret
        self.language = language
        self.sample_rate = sample_rate
        self.timeout = timeout
        # 发送帧间隔（秒）, 测试时可置 0
        self.frame_interval = 0.04

    @property
    def configured(self) -> bool:
        return bool(self.app_id) and bool(self.api_key) and bool(self.api_secret)

    def transcribe(
        self, audio_path: str | Path, language: str | None = None
    ) -> list[Utterance]:
        """转写音频文件, 长音频自动切块, 返回带词级时间戳的句子列表."""
        import librosa
        import numpy as np

        audio_path = Path(audio_path)
        y, _ = librosa.load(str(audio_path), sr=self.sample_rate, mono=True)
        pcm = (np.clip(y, -1.0, 1.0) * 32767).astype(np.int16).tobytes()

        chunk_bytes = self.CHUNK_SECONDS * self.sample_rate * 2
        lang = language or self.language
        utterances: list[Utterance] = []
        for start in range(0, len(pcm), chunk_bytes):
            chunk = pcm[start : start + chunk_bytes]
            offset = start / 2.0 / self.sample_rate
            utterances.extend(self._transcribe_chunk(chunk, offset, lang))
        return utterances

    def _build_url(self) -> str:
        """按文档生成带鉴权参数的 WebSocket URL（HMAC-SHA256 签名）."""
        date = formatdate(timeval=None, localtime=False, usegmt=True)
        signature_origin = (
            f"host: {self.WS_HOST}\ndate: {date}\nGET /v2/iat HTTP/1.1"
        )
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
        authorization = base64.b64encode(
            authorization_origin.encode("utf-8")
        ).decode("utf-8")
        params = {
            "authorization": authorization,
            "date": date,
            "host": self.WS_HOST,
        }
        return f"{self.WS_URL}?{urlencode(params)}"

    def _transcribe_chunk(
        self, pcm: bytes, offset: float, language: str
    ) -> list[Utterance]:
        """对单块 PCM 音频建立一次 WebSocket 会话并返回识别结果."""
        import websocket

        try:
            ws = websocket.create_connection(self._build_url(), timeout=self.timeout)
        except Exception as exc:
            raise RuntimeError(f"讯飞流式听写连接失败：{exc}")

        try:
            fmt = f"audio/L16;rate={self.sample_rate}"
            first = True
            for pos in range(0, len(pcm), self.FRAME_SIZE):
                frame = pcm[pos : pos + self.FRAME_SIZE]
                payload: dict[str, Any] = {
                    "data": {
                        "status": 0 if first else 1,
                        "format": fmt,
                        "encoding": "raw",
                        "audio": base64.b64encode(frame).decode("utf-8"),
                    }
                }
                if first:
                    payload["common"] = {"app_id": self.app_id}
                    payload["business"] = {
                        "language": language,
                        "domain": "iat",
                        "accent": "mandarin",
                    }
                ws.send(json.dumps(payload))
                first = False
                if self.frame_interval:
                    time.sleep(self.frame_interval)
            # 发送结束标识
            ws.send(
                json.dumps(
                    {"data": {"status": 2, "format": fmt, "encoding": "raw", "audio": ""}}
                )
            )
            results = self._recv_results(ws)
        finally:
            try:
                ws.close()
            except Exception:
                pass

        return self._parse_results(results, offset)

    @staticmethod
    def _recv_results(ws: Any) -> list[dict[str, Any]]:
        """接收识别结果, 直到服务端返回结束标识."""
        results: list[dict[str, Any]] = []
        while True:
            try:
                raw = ws.recv()
            except Exception as exc:
                raise RuntimeError(f"讯飞流式听写接收结果失败：{exc}")
            try:
                resp = json.loads(raw)
            except (TypeError, json.JSONDecodeError) as exc:
                raise RuntimeError(f"讯飞流式听写响应解析失败：{exc}")

            code = resp.get("code")
            if code != 0:
                message = resp.get("message") or "未知错误"
                raise RuntimeError(f"讯飞流式听写错误：{message} (code={code})")

            data = resp.get("data") or {}
            result = data.get("result")
            if result:
                results.append(result)
            if data.get("status") == 2:
                break
        return results

    @staticmethod
    def _parse_results(
        results: list[dict[str, Any]], offset: float
    ) -> list[Utterance]:
        """解析 ws/cw 结果为 Utterance, 支持动态修正的 apd/rpl 语义."""
        # 按 sn 去重/替换, 兼容开启动态修正（dwa=wpgs）时的结果修正
        segments: dict[int, dict[str, Any]] = {}
        for res in results:
            sn = int(res.get("sn", len(segments) + 1))
            if res.get("pgs") == "rpl":
                rg = res.get("rg") or [sn, sn]
                for old_sn in range(int(rg[0]), int(rg[1]) + 1):
                    segments.pop(old_sn, None)
            segments[sn] = res

        utterances: list[Utterance] = []
        for sn in sorted(segments):
            ws_list = segments[sn].get("ws") or []
            text_parts: list[str] = []
            words: list[Word] = []
            seg_start: float | None = None
            seg_end: float | None = None
            for ws in ws_list:
                # ws.bg/ws.ed 为 10ms 帧偏移, 从音频（块）起始算起
                word_start = offset + int(ws.get("bg", 0)) * 0.01
                word_end = offset + int(ws.get("ed", 0)) * 0.01
                ws_text = ""
                for cw in ws.get("cw", []):
                    w_text = str(cw.get("w", ""))
                    if not w_text:
                        continue
                    ws_text += w_text
                    if cw.get("wp") != "p":
                        words.append(
                            Word(
                                text=w_text,
                                start=word_start,
                                end=word_end,
                                confidence=None,
                            )
                        )
                if not ws_text:
                    continue
                text_parts.append(ws_text)
                # bg=0 的标点/空结果无参考意义, 不参与句子边界计算
                if int(ws.get("bg", 0)) > 0 or seg_start is None:
                    if seg_start is None or word_start < seg_start:
                        seg_start = word_start
                if seg_end is None or word_end > seg_end:
                    seg_end = word_end

            text = "".join(text_parts)
            if text and seg_start is not None and seg_end is not None:
                utterances.append(
                    Utterance(
                        text=text,
                        start=seg_start,
                        end=seg_end,
                        words=words,
                    )
                )
        return utterances
