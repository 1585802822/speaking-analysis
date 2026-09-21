"""配置加载."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


DEFAULT_CONFIG_PATH = Path("config.yaml")


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    """加载 YAML 配置文件."""
    config_path = Path(path) if path else DEFAULT_CONFIG_PATH
    if not config_path.exists():
        raise FileNotFoundError(f"配置文件不存在: {config_path}")
    with config_path.open("r", encoding="utf-8") as f:
        config = yaml.safe_load(f) or {}
    return config


def ensure_dirs(config: dict[str, Any]) -> None:
    """确保输入/输出/声纹目录存在."""
    for key in ("input_dir", "output_dir", "voiceprint_dir"):
        Path(config[key]).mkdir(parents=True, exist_ok=True)
