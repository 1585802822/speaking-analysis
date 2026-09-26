#!/usr/bin/env python3
"""一键实测发音分析模块（讯飞 Ifasr_llm 转写 -> 讯飞 ISE 发音评测）.

对 data/output/02_separated/ 下已分离好的用户语音片段, 真连讯飞开放平台 API:
先用 ASR 把片段转写为参考文本, 再调用 ISE 语音评测输出准确度/流利度/完整度分数,
用于验证 HMAC-SHA256 鉴权、WebSocket 建连与真实响应解析是否可用
（单元测试均 mock 掉了 WebSocket, 这条真实链路尚未验证过）.

用法:
    uv run python scripts/test_ise_live.py
    uv run python scripts/test_ise_live.py --audio <某个 wav 路径>   # 可多次指定
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

# 确保从项目根目录导入 src 包
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.config import load_config  # noqa: E402
from src.iflytek_asr_client import build_llm_asr_client, iFlytekLlmASRClient  # noqa: E402
from src.iflytek_evaluation_client import build_evaluation_client  # noqa: E402

DEFAULT_GLOB = "data/output/02_separated/*/*/user_all.wav"


def configure_stdout() -> None:
    """把标准输出重配为 UTF-8，避免 Windows GBK 控制台编码中文/特殊符号报错."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def load_env(env_path: Path | None = None) -> None:
    """把 .env 载入 os.environ（项目无 python-dotenv，手写最小解析）."""
    path = env_path or (PROJECT_ROOT / ".env")
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        # 剥掉行内 # 注释（密钥本身不含 #）
        if "#" in line:
            line = line.split("#", 1)[0].strip()
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if key:
            # 已存在的环境变量优先，避免覆盖 shell 中显式设置的值
            os.environ.setdefault(key, value)


def detect_language(text: str) -> str:
    """粗判评测语言，语义与 PronunciationAnalyzer._detect_language 一致."""
    if any("一" <= ch <= "鿿" for ch in text):
        return "cn"
    if re.fullmatch(r"[A-Za-z\s\-',.!?]+", text):
        return "en"
    return "cn"


def discover_audio(args: argparse.Namespace) -> list[Path]:
    """确定要评测的片段列表：--audio 优先，否则按默认 glob 匹配 user_all.wav."""
    if args.audio:
        return [Path(p) for p in args.audio]
    return sorted(PROJECT_ROOT.glob(DEFAULT_GLOB))


def transcribe_text(asr_client: iFlytekLlmASRClient, audio_path: Path) -> str:
    """转写片段，返回拼接后的参考文本（去空白）。"""
    utterances = asr_client.transcribe(audio_path)
    return "".join(u.text for u in utterances).strip()


def evaluate_one(
    audio_path: Path,
    asr_client: iFlytekLlmASRClient,
    ise_client,
    standard_threshold: float,
) -> dict:
    """对单个片段跑 ASR -> ISE，返回结果 dict（含 error 字段表示失败原因）."""
    result: dict = {"audio": str(audio_path)}
    try:
        text = transcribe_text(asr_client, audio_path)
        if not text:
            result["error"] = "ASR 未转写出文本"
            return result
        result["text"] = text
        lang = detect_language(text)
        result["language"] = lang
        scores = ise_client.evaluate(audio_path, text, language=lang)
        result["overall"] = scores.get("overall_score")
        result["accuracy"] = scores.get("accuracy_score")
        result["fluency"] = scores.get("fluency_score")
        result["integrity"] = scores.get("integrity_score")
        overall = result["overall"]
        result["standard"] = (
            "标准" if overall is not None and overall >= standard_threshold else "不标准"
        )
    except Exception as exc:  # 单段失败不中断，对齐流水线容错语义
        result["error"] = str(exc)
    return result


def fmt_score(value) -> str:
    """分数格式化为定点字符串，None 显示为占位符."""
    return "  -  " if value is None else f"{value:5.1f}"


def main() -> int:
    parser = argparse.ArgumentParser(description="实测发音分析模块（ASR -> ISE）")
    parser.add_argument(
        "--audio",
        action="append",
        default=None,
        help="指定单个/多个音频片段路径，缺省时用默认 glob 匹配 user_all.wav",
    )
    args = parser.parse_args()

    configure_stdout()
    load_env()
    config = load_config(PROJECT_ROOT / "config.yaml")

    asr_client = build_llm_asr_client(config)
    if asr_client is None:
        print("错误：ASR 未配置（缺讯飞 app_id/api_key/api_secret），请检查 .env 或 config.yaml")
        return 1

    ise_client = build_evaluation_client(config)
    if ise_client is None:
        print("错误：ISE 未配置（缺 app_id/api_key/api_secret），请检查 .env 或 config.yaml")
        return 1

    audio_paths = discover_audio(args)
    if not audio_paths:
        print(f"未找到待评测片段（默认匹配 {DEFAULT_GLOB}），可用 --audio 指定")
        return 1

    standard_threshold = float(
        config.get("analysis", {}).get("pronunciation", {}).get("standard_threshold", 80)
    )

    print("=" * 76)
    print("发音分析模块实测（讯飞 ASR 转写 -> 讯飞 ISE 评测）")
    print(f"待评测片段：{len(audio_paths)} 个")
    print("=" * 76)

    results = []
    for i, audio_path in enumerate(audio_paths, 1):
        print(f"\n[{i}/{len(audio_paths)}] {audio_path.name}")
        print(f"    文件：{audio_path}")
        res = evaluate_one(audio_path, asr_client, ise_client, standard_threshold)
        if res.get("error"):
            print(f"    [FAIL] 失败：{res['error']}")
        else:
            print(f"    ASR 文本：{res['text']}  （语言 {res['language']}）")
            print(
                f"    总分 {fmt_score(res['overall'])} | 准确度 {fmt_score(res['accuracy'])}"
                f" | 流利度 {fmt_score(res['fluency'])} | 完整度 {fmt_score(res['integrity'])}"
                f"  -> {res['standard']}"
            )
        results.append(res)

    # 汇总
    print("\n" + "-" * 76)
    print("汇总：")
    ok = [r for r in results if not r.get("error")]
    failed = [r for r in results if r.get("error")]
    print(f"  成功 {len(ok)} 段 / 失败 {len(failed)} 段")
    if ok:
        print(f"\n  {'片段':<38} {'总分':>6} {'准确度':>6} {'流利度':>6} {'完整度':>6}  判定")
        for r in ok:
            name = Path(r["audio"]).name
            print(
                f"  {name:<38} {fmt_score(r['overall']):>6} {fmt_score(r['accuracy']):>6}"
                f" {fmt_score(r['fluency']):>6} {fmt_score(r['integrity']):>6}  {r['standard']}"
            )
    print("=" * 76)

    # 至少一段完整跑通即视为链路可用（部分片段因题型/文本长度被讯飞拒绝属预期）
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
