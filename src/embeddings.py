"""声纹/音频嵌入提取.

优先尝试重型模型(speechbrain/pyannote), 不可用时回退到本地 librosa MFCC 统计特征.
所有依赖均在函数内部懒加载, 避免未安装模型时导入失败.
"""

from __future__ import annotations

import sys
import tempfile
import warnings
from pathlib import Path
from typing import Any

import librosa
import numpy as np

from .model_api_client import ModelAPIClient


TARGET_DIM = 192

# ECAPA 分类器模块级惰性单例: (source, savedir) -> classifier
_ECAPA_CLASSIFIER: dict[tuple[str, str], Any] = {}


def _cleanup_broken_speechbrain_imports() -> None:
    """清除 speechbrain 导入失败后残留在 sys.modules 中的损坏懒加载模块.

    speechbrain 1.0+ 在 sys.modules 中注册 DeprecatedModuleRedirect 代理,
    其 __getattr__ 会触发 ensure_module → 尝试加载 k2_fsa 等未安装依赖.
    这会污染 inspect.getmodule() 的遍历路径, 导致后续所有 lazy_loader.load()
    (包括 librosa 内部的) 均触发 ImportError.  移除这些代理即可恢复.
    """
    import sys

    to_remove = [
        k
        for k, mod in list(sys.modules.items())
        if "speechbrain" in k
        and type(mod).__name__ in ("DeprecatedModuleRedirect", "LazyModule")
    ]
    for k in to_remove:
        del sys.modules[k]


def _get_ecapa_classifier(config: dict[str, Any] | None = None) -> Any:
    """获取(并缓存) speechbrain ECAPA 说话人分类器单例.

    speechbrain 1.0+ 弃用了 speechbrain.pretrained 导入路径(其懒加载代理会触发
    未安装的 k2_fsa 依赖), 因此优先从 speechbrain.inference.speaker 导入;
    Windows 无特权时默认的 SYMLINK 本地化策略会失败, 改用 COPY.
    """
    speaker_cfg = (config or {}).get("speaker", {})
    source = speaker_cfg.get("embedding_model", "speechbrain/spkrec-ecapa-voxceleb")
    savedir = speaker_cfg.get(
        "embedding_model_cache", f"./tmp/{source.replace('/', '_')}"
    )
    key = (source, savedir)
    cached = _ECAPA_CLASSIFIER.get(key)
    if cached is not None:
        return cached

    try:
        from speechbrain.utils.fetching import LocalStrategy
    except Exception:
        LocalStrategy = None

    try:
        try:
            from speechbrain.inference.speaker import EncoderClassifier
        except ImportError:
            # 旧版本 speechbrain (<1.0) 只有 pretrained 命名空间
            from speechbrain.pretrained import EncoderClassifier
    except Exception:
        _cleanup_broken_speechbrain_imports()
        raise

    kwargs: dict[str, Any] = {}
    if LocalStrategy is not None:
        kwargs["local_strategy"] = LocalStrategy.COPY
    classifier = EncoderClassifier.from_hparams(source=source, savedir=savedir, **kwargs)
    _cleanup_broken_speechbrain_imports()
    _ECAPA_CLASSIFIER[key] = classifier
    return classifier


def _ecapa_embed_array(y: np.ndarray, sr: int, config: dict[str, Any] | None = None) -> np.ndarray:
    """用 ECAPA 对单声道 16kHz 音频数组提取说话人嵌入."""
    import torch

    classifier = _get_ecapa_classifier(config)
    signal = torch.from_numpy(np.asarray(y, dtype=np.float32)).unsqueeze(0)
    emb = classifier.encode_batch(signal).squeeze().detach().cpu().numpy()
    if emb.ndim == 0:
        emb = np.array([emb.item()])
    return _normalize(emb)


def _mfcc_stats(y: np.ndarray, sr: int, target_dim: int = TARGET_DIM) -> np.ndarray:
    """基于 MFCC 均值/方差的轻量级嵌入(本地回退)."""
    mfcc = librosa.feature.mfcc(y=y, sr=sr, n_mfcc=20)
    mean = np.mean(mfcc, axis=1)
    std = np.std(mfcc, axis=1)
    emb = np.concatenate([mean, std])
    if len(emb) < target_dim:
        emb = np.pad(emb, (0, target_dim - len(emb)))
    else:
        emb = emb[:target_dim]
    norm = np.linalg.norm(emb) + 1e-8
    return (emb / norm).astype(np.float32)


def extract_embedding_from_array(
    y: np.ndarray, sr: int, config: dict[str, Any] | None = None
) -> np.ndarray:
    """从音频数组提取嵌入: 优先 ECAPA(单例), 失败回退本地 MFCC."""
    try:
        return _ecapa_embed_array(y, sr, config)
    except Exception:
        pass
    try:
        return _mfcc_stats(y, sr)
    except Exception as exc:  # pragma: no cover - 保护性兜底
        warnings.warn(f"本地 MFCC 嵌入提取失败, 返回零向量: {exc}")
        return np.zeros(TARGET_DIM, dtype=np.float32)


def extract_embedding(
    audio_path: str | Path, config: dict[str, Any] | None = None
) -> np.ndarray:
    """从音频文件路径提取嵌入, 优先重型模型, 回退本地 MFCC.

    TODO: 当前 emotion/pronunciation 任务不需要声纹嵌入, 但 correction loop 依赖它.
          真实部署时应替换为 speechbrain EncoderClassifier 或 pyannote 预训练模型.
    """
    audio_path = Path(audio_path)
    if not audio_path.exists():
        raise FileNotFoundError(f"音频不存在: {audio_path}")

    # 0) 优先 Model API Gateway
    if config:
        client = ModelAPIClient(config)
        if client.embed_available:
            try:
                emb = client.embed(str(audio_path))
                return _normalize(emb)
            except Exception as exc:
                warnings.warn(f"Embedding API 调用失败, 回退本地模型: {exc}")

    # 1) 尝试 speechbrain ECAPA-TDNN 说话人嵌入
    #    注意: torchaudio.load 在 torchcodec DLL 损坏时不可用, 统一用 librosa 加载.
    try:
        y, sr = librosa.load(str(audio_path), sr=16000, mono=True)
        return _ecapa_embed_array(y, sr, config)
    except Exception:
        # speechbrain 导入或推理失败 — 清理 sys.modules 中的损坏懒加载代理,
        # 否则后续 librosa 的 lazy_loader 会触发 speechbrain __getattr__ → ImportError
        _cleanup_broken_speechbrain_imports()

    # 2) 尝试 pyannote.audio 说话人嵌入
    try:
        from pyannote.audio import Inference, Model

        speaker_cfg = config.get("speaker", {}) if config else {}
        model_name = speaker_cfg.get("pyannote_embedding_model", "pyannote/embedding")
        model = Model.from_pretrained(model_name)
        inference = Inference(model, window="whole")
        emb = inference(str(audio_path))
        return _normalize(np.asarray(emb).flatten())
    except Exception:
        pass

    # 3) 本地回退: librosa MFCC
    try:
        y, sr = librosa.load(str(audio_path), sr=16000, mono=True)
        return _mfcc_stats(y, sr)
    except Exception as exc:
        warnings.warn(f"嵌入提取全部失败, 返回零向量: {exc}")
        return np.zeros(TARGET_DIM, dtype=np.float32)


def _normalize(emb: np.ndarray, target_dim: int = TARGET_DIM) -> np.ndarray:
    """归一化并截断/填充到目标维度."""
    emb = np.asarray(emb, dtype=np.float32).flatten()
    if len(emb) < target_dim:
        emb = np.pad(emb, (0, target_dim - len(emb)))
    else:
        emb = emb[:target_dim]
    norm = np.linalg.norm(emb) + 1e-8
    return (emb / norm).astype(np.float32)


def _energy_vad_mask(y: np.ndarray, sr: int, frame_sec: float, energy_db: float) -> np.ndarray:
    """按帧能量计算有效语音掩码.

    帧 RMS 低于 (全局峰值 dB - energy_db) 的帧判为静音.
    """
    frame_len = max(1, int(frame_sec * sr))
    n_frames = int(np.ceil(len(y) / frame_len))
    if n_frames == 0:
        return np.zeros(0, dtype=bool)
    padded = np.pad(y, (0, n_frames * frame_len - len(y)))
    frames = padded.reshape(n_frames, frame_len)
    rms = np.sqrt(np.mean(frames**2, axis=1) + 1e-12)
    peak_db = 20 * np.log10(np.max(rms) + 1e-12)
    threshold_db = peak_db - max(1.0, energy_db)
    frame_db = 20 * np.log10(rms + 1e-12)
    return frame_db >= threshold_db


def extract_speaker_center(
    audio_paths: list[str | Path],
    config: dict[str, Any] | None = None,
) -> tuple[np.ndarray, int]:
    """从多个注册音频提取声纹中心.

    每个音频先按能量 VAD 跳过静音段(避免开头/尾部静音污染嵌入),
    再按 enroll_chunk_sec 切块取嵌入, 全部块的嵌入均值经 L2 归一化后返回.

    Returns
    -------
    (center, chunk_count) : 声纹中心向量与参与平均的有效块数.
    """
    speaker_cfg = (config or {}).get("speaker", {})
    chunk_sec = float(speaker_cfg.get("enroll_chunk_sec", 3.0))
    energy_db = float(speaker_cfg.get("enroll_vad_energy_db", 40.0))
    frame_sec = max(0.1, chunk_sec / 3.0)

    embs: list[np.ndarray] = []
    for path in audio_paths:
        y, sr = librosa.load(str(path), sr=16000, mono=True)
        speech_mask = _energy_vad_mask(y, sr, frame_sec, energy_db)
        chunk_len = int(chunk_sec * sr)
        min_len = chunk_len // 2
        start = 0
        frame_len = int(frame_sec * sr)
        while start < len(y):
            end = min(start + chunk_len, len(y))
            if end - start < min_len:
                break
            # 以块内语音帧占比 >= 80% 判定有效语音块
            frame_idx_start = start // frame_len
            frame_idx_end = (end - 1) // frame_len + 1
            chunk_frames = speech_mask[frame_idx_start:frame_idx_end]
            if len(chunk_frames) > 0 and chunk_frames.mean() >= 0.8:
                try:
                    embs.append(_ecapa_embed_array(y[start:end], sr, config))
                except Exception:
                    embs.append(_mfcc_stats(y[start:end], sr))
            start = end

    if not embs:
        raise RuntimeError("注册音频中没有检测到有效语音块, 无法提取声纹中心")
    center = np.mean(np.stack(embs), axis=0)
    center = center / (np.linalg.norm(center) + 1e-8)
    return center.astype(np.float32), len(embs)


def crop_audio_segment(
    audio_path: str | Path,
    start_sec: float,
    end_sec: float,
    output_path: str | Path | None = None,
    target_sr: int = 16000,
) -> Path:
    """裁剪音频片段并保存为 WAV, 优先 pydub, 回退 librosa+soundfile."""
    audio_path = Path(audio_path)
    if output_path is None:
        output_path = Path(tempfile.gettempdir()) / f"seg_{start_sec:.3f}_{end_sec:.3f}.wav"
    output_path = Path(output_path)

    # 优先 pydub(支持更多格式)
    try:
        from pydub import AudioSegment

        audio = AudioSegment.from_file(str(audio_path))
        start_ms = int(max(0.0, start_sec) * 1000)
        end_ms = int(min(end_sec * 1000, len(audio)))
        if end_ms <= start_ms:
            raise ValueError(f"无效时段: {start_sec}-{end_sec}")
        segment = audio[start_ms:end_ms]
        segment.export(str(output_path), format="wav")
        return output_path
    except Exception:
        pass

    # 回退 librosa + soundfile
    try:
        import soundfile as sf

        y, sr = librosa.load(str(audio_path), sr=target_sr, mono=True)
        start_sample = int(max(0.0, start_sec) * sr)
        end_sample = int(min(end_sec * sr, len(y)))
        if end_sample <= start_sample:
            raise ValueError(f"无效时段: {start_sec}-{end_sec}")
        sf.write(str(output_path), y[start_sample:end_sample], sr)
        return output_path
    except Exception as exc:
        raise RuntimeError(f"无法裁剪音频片段 {start_sec}-{end_sec}: {exc}") from exc
