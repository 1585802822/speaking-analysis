"""统一的 Model API Gateway 客户端.

本期负责 ASR 与声纹嵌入; 情感和正音接口已预留.

约定的 Gateway 响应格式:

- ASR (POST /asr):
    {
      "segments": [
        {
          "text": "你好世界",
          "start": 0.0,
          "end": 1.5,
          "words": [
            {"text": "你好", "start": 0.0, "end": 0.8, "confidence": 0.95},
            {"text": "世界", "start": 0.8, "end": 1.5, "confidence": 0.92}
          ]
        }
      ]
    }

- Embedding (POST /embed):
    {
      "embedding": [0.1, 0.2, ...]
    }
"""

from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path
from typing import Any

import numpy as np

from .iflytek_asr_client import iFlytekLongASRClient, iFlytekStreamASRClient
from .types import Utterance, Word

logger = logging.getLogger(__name__)


class ModelAPIClient:
    """调用统一的 Model API Gateway.

    当配置未启用或请求失败时抛出异常, 由调用方决定是否回退到本地逻辑.
    """

    def __init__(self, config: dict[str, Any]) -> None:
        api_cfg = (config or {}).get("api", {})
        self.enabled = bool(api_cfg.get("enabled", False))
        self.base_url = str(api_cfg.get("base_url", "")).rstrip("/")
        self.api_key = self._load_key(api_cfg.get("api_key_env"))
        self.timeout = int(api_cfg.get("timeout", 60))
        endpoints = api_cfg.get("endpoints", {}) or {}
        self.asr_endpoint = str(endpoints.get("asr", "")).lstrip("/")
        self.embed_endpoint = str(endpoints.get("embed", "")).lstrip("/")
        self.provider = str(api_cfg.get("provider", "gateway")).strip().lower()
        self.iflytek_client: iFlytekLongASRClient | iFlytekStreamASRClient | None = None
        if self.provider == "iflytek":
            iflytek_cfg = api_cfg.get("iflytek", {}) or {}
            mode = str(iflytek_cfg.get("mode", "long")).strip().lower()
            app_id = self._resolve_secret(
                iflytek_cfg.get("app_id", ""), iflytek_cfg.get("app_id_env")
            )
            api_key = self._resolve_secret(
                iflytek_cfg.get("api_key", ""), iflytek_cfg.get("api_key_env")
            )
            api_secret = self._resolve_secret(
                iflytek_cfg.get("api_secret", ""), iflytek_cfg.get("api_secret_env")
            )
            if mode == "stream":
                self.iflytek_client = iFlytekStreamASRClient(
                    app_id=app_id,
                    api_key=api_key,
                    api_secret=api_secret,
                    language=str(iflytek_cfg.get("language", "zh_cn")),
                    timeout=self.timeout,
                )
            else:
                self.iflytek_client = iFlytekLongASRClient(
                    app_id=app_id,
                    api_secret=api_secret,
                    language=str(iflytek_cfg.get("language", "cn")),
                    timeout=self.timeout,
                )

    @staticmethod
    def _resolve_secret(value: Any, env_name: str | None) -> str:
        """优先使用配置值, 为空时回退到环境变量."""
        if value:
            return str(value)
        if env_name:
            return os.environ.get(env_name, "")
        return ""

    @staticmethod
    def _load_key(env_name: str | None) -> str | None:
        if not env_name:
            return None
        return os.environ.get(env_name)

    @property
    def asr_available(self) -> bool:
        if not self.enabled:
            return False
        if self.provider == "iflytek":
            return self.iflytek_client is not None and self.iflytek_client.configured
        return bool(self.base_url) and bool(self.asr_endpoint)

    @property
    def embed_available(self) -> bool:
        return self.enabled and bool(self.base_url) and bool(self.embed_endpoint)

    def transcribe(self, audio_path: str | Path, language: str | None = None) -> list[Utterance]:
        """调用 ASR 服务, 返回带时间戳的句子列表."""
        if not self.asr_available:
            raise RuntimeError("ASR API 未启用或未配置 endpoint")

        if self.provider == "iflytek" and self.iflytek_client is not None:
            return self.iflytek_client.transcribe(audio_path, language=language)

        response = self._post_file(
            self.asr_endpoint,
            audio_path,
            extra_data={"language": language} if language else None,
        )
        return self._parse_asr_response(response)

    def embed(self, audio_path: str | Path) -> np.ndarray:
        """调用 Gateway Embedding 端点, 返回声纹嵌入向量."""
        if not self.embed_available:
            raise RuntimeError("Embedding API 未启用或未配置 endpoint")

        response = self._post_file(self.embed_endpoint, audio_path)
        return self._parse_embed_response(response)

    def emotion(self, *args: Any, **kwargs: Any) -> Any:
        """预留接口."""
        raise NotImplementedError("Emotion API 尚未实现")

    def pronunciation(self, *args: Any, **kwargs: Any) -> Any:
        """预留接口."""
        raise NotImplementedError("Pronunciation API 尚未实现")

    def _post_file(
        self,
        endpoint: str,
        audio_path: str | Path,
        extra_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        import requests

        url = f"{self.base_url}/{endpoint}"
        headers: dict[str, str] = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        wav_path = self._ensure_wav(audio_path)
        try:
            with open(wav_path, "rb") as f:
                files = {"audio": f}
                data = extra_data or {}
                resp = requests.post(
                    url, files=files, data=data, headers=headers, timeout=self.timeout
                )
            resp.raise_for_status()
            return resp.json()
        finally:
            if wav_path != Path(audio_path):
                try:
                    wav_path.unlink()
                except OSError:
                    pass

    def _ensure_wav(self, audio_path: str | Path) -> Path:
        """将输入音频转换为 16kHz 单声道 WAV, 返回临时文件路径."""
        import librosa
        import soundfile as sf

        audio_path = Path(audio_path)
        y, sr = librosa.load(str(audio_path), sr=16000, mono=True)
        fd, tmp_path = tempfile.mkstemp(suffix=".wav")
        os.close(fd)
        out_path = Path(tmp_path)
        sf.write(str(out_path), y, 16000)
        return out_path

    @staticmethod
    def _parse_asr_response(response: dict[str, Any]) -> list[Utterance]:
        segments = response.get("segments", [])
        if not isinstance(segments, list):
            raise ValueError("ASR 响应中 segments 不是列表")

        utterances: list[Utterance] = []
        for seg in segments:
            text = str(seg.get("text", "")).strip()
            if not text:
                continue
            start = float(seg.get("start", 0.0))
            end = float(seg.get("end", 0.0))
            words: list[Word] = []
            for w in seg.get("words", []) or []:
                word_text = str(w.get("text", w.get("word", ""))).strip()
                if not word_text:
                    continue
                words.append(
                    Word(
                        text=word_text,
                        start=float(w.get("start", start)),
                        end=float(w.get("end", end)),
                        confidence=float(w["confidence"]) if "confidence" in w else None,
                    )
                )
            if not words:
                words.append(Word(text=text, start=start, end=end, confidence=None))
            utterances.append(Utterance(text=text, start=start, end=end, words=words))
        return utterances

    @staticmethod
    def _parse_embed_response(response: dict[str, Any]) -> np.ndarray:
        embedding = response.get("embedding")
        if not isinstance(embedding, list):
            raise ValueError("Embedding 响应中 embedding 不是列表")
        return np.asarray(embedding, dtype=np.float32)


def maybe_model_api_client(config: dict[str, Any]) -> ModelAPIClient | None:
    """根据配置返回可用的 ModelAPIClient, 未启用时返回 None."""
    client = ModelAPIClient(config)
    if not client.enabled:
        return None
    return client
