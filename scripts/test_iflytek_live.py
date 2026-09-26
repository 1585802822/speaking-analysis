#!/usr/bin/env python3
"""一键实测讯飞新接口链路（Ifasr_llm 大模型转写 -> Spark VAA 语音分析）.

对 data/output/02_separated/ 下已分离好的用户语音片段, 真连讯飞开放平台 API:
1. ASR: 录音文件转写大模型版（Ifasr_llm）, 上传音频 -> 轮询 -> 解析 lattice 结果;
2. 评测: Spark VAA 语音分析接口, 用自定义 prompt 让大模型输出发音分数.

注意 VAA 只接收音频外链 audioFileURL, 不直接收文件. 本脚本默认启动一个本地 HTTP
服务把项目目录暴露出去, 供讯飞服务端拉取. 讯飞服务端在公网, 若本机没有公网 IP 或
端口映射, VAA 将无法访问本地地址（此时用 --skip-vaa 只验证 ASR 即可）.

用法:
    uv run python scripts/test_iflytek_live.py
    uv run python scripts/test_iflytek_live.py --audio <wav 路径>   # 可多次指定
    uv run python scripts/test_iflytek_live.py --skip-vaa           # 只测 ASR
    uv run python scripts/test_iflytek_live.py --audio-url <公网音频外链>  # 指定已上传的外链
"""

from __future__ import annotations

import argparse
import http.server
import os
import re
import socket
import socketserver
import sys
import threading
from functools import partial
from pathlib import Path

# 确保从项目根目录导入 src 包
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.config import load_config  # noqa: E402
from src.iflytek_asr_client import build_llm_asr_client  # noqa: E402
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
        if "#" in line:
            line = line.split("#", 1)[0].strip()
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if key:
            os.environ.setdefault(key, value)


def get_lan_ip() -> str:
    """探测本机局域网 IP（用于拼本地 HTTP 外链）."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


def start_local_server(root: Path) -> tuple[str, socketserver.TCPServer]:
    """启动本地 HTTP 服务, 返回 (base_url, httpd)."""
    handler = partial(http.server.SimpleHTTPRequestHandler, directory=str(root))
    httpd = socketserver.TCPServer(("0.0.0.0", 0), handler)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return f"http://{get_lan_ip()}:{port}", httpd


def make_resolver(root: Path, base_url: str):
    """生成把本地文件路径映射为公网外链的解析器."""
    root = root.resolve()

    def resolver(path: Path) -> str:
        rel = path.resolve().relative_to(root)
        return f"{base_url}/{rel.as_posix()}"

    return resolver


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


def fmt_score(value) -> str:
    """分数格式化为定点字符串，None 显示为占位符."""
    return "  -  " if value is None else f"{value:5.1f}"


def main() -> int:
    parser = argparse.ArgumentParser(description="实测讯飞 Ifasr_llm ASR + Spark VAA 语音分析")
    parser.add_argument(
        "--audio",
        action="append",
        default=None,
        help="指定单个/多个音频片段路径，缺省时用默认 glob 匹配 user_all.wav",
    )
    parser.add_argument(
        "--skip-vaa",
        action="store_true",
        help="只测 ASR 转写，跳过 VAA 语音分析（VAA 需要公网外链）",
    )
    parser.add_argument(
        "--audio-url",
        default=None,
        help="VAA 使用的公网音频外链（覆盖本地 HTTP 服务，需与 --audio 片段对应）",
    )
    args = parser.parse_args()

    configure_stdout()
    load_env()
    config = load_config(PROJECT_ROOT / "config.yaml")

    asr_client = build_llm_asr_client(config)
    if asr_client is None:
        print(
            "错误：Ifasr_llm ASR 未配置（缺 app_id/api_key/api_secret），请检查 .env 或 config.yaml"
        )
        return 1

    audio_paths = discover_audio(args)
    if not audio_paths:
        print(f"未找到待评测片段（默认匹配 {DEFAULT_GLOB}），可用 --audio 指定")
        return 1

    standard_threshold = float(
        config.get("analysis", {}).get("pronunciation", {}).get("standard_threshold", 80)
    )

    # VAA 客户端与外链解析
    vaa_client = None
    vaa_url = None
    if not args.skip_vaa:
        vaa_client = build_evaluation_client(config)
        if vaa_client is None:
            print("提示：Spark VAA 未配置，本次仅验证 ASR")
        elif args.audio_url:
            vaa_url = args.audio_url
        else:
            base_url, _httpd = start_local_server(PROJECT_ROOT)
            vaa_client.audio_url_resolver = make_resolver(PROJECT_ROOT, base_url)
            print(f"已启动本地 HTTP 服务：{base_url}/")
            print("注意：VAA 需要讯飞服务端能访问到该地址，普通内网机器通常不可达，失败属预期")

    print("=" * 76)
    print("讯飞新接口实测（Ifasr_llm 大模型转写 -> Spark VAA 语音分析）")
    print(f"待评测片段：{len(audio_paths)} 个")
    print("=" * 76)

    results = []
    for i, audio_path in enumerate(audio_paths, 1):
        print(f"\n[{i}/{len(audio_paths)}] {audio_path.name}")
        print(f"    文件：{audio_path}")
        res: dict = {"audio": str(audio_path)}
        try:
            utterances = asr_client.transcribe(audio_path)
            text = "".join(u.text for u in utterances).strip()
            if not text:
                res["error"] = "ASR 未转写出文本"
                print(f"    [FAIL] {res['error']}")
                results.append(res)
                continue
            res["text"] = text
            print(f"    ASR 文本：{text}")
        except Exception as exc:
            res["error"] = f"ASR 失败：{exc}"
            print(f"    [FAIL] {res['error']}")
            results.append(res)
            continue

        if vaa_client is None:
            results.append(res)
            continue

        try:
            if vaa_url:
                audio_path = vaa_url
            scores = vaa_client.evaluate(audio_path, text, language=detect_language(text))
            res["overall"] = scores.get("overall_score")
            res["accuracy"] = scores.get("accuracy_score")
            res["fluency"] = scores.get("fluency_score")
            res["integrity"] = scores.get("integrity_score")
            overall = res["overall"]
            res["standard"] = (
                "标准" if overall is not None and overall >= standard_threshold else "不标准"
            )
            print(
                f"    VAA 总分 {fmt_score(res['overall'])} | 准确度 {fmt_score(res['accuracy'])}"
                f" | 流利度 {fmt_score(res['fluency'])} | 完整度 {fmt_score(res['integrity'])}"
                f"  -> {res['standard']}"
            )
        except Exception as exc:
            res["error"] = f"VAA 失败：{exc}"
            print(f"    [FAIL] {res['error']}")
        results.append(res)

    # 汇总
    print("\n" + "-" * 76)
    ok = [r for r in results if not r.get("error")]
    failed = [r for r in results if r.get("error")]
    print(f"成功 {len(ok)} 段 / 失败 {len(failed)} 段")
    for r in ok:
        print(f"  {Path(r['audio']).name}: {r.get('text', '')[:40]}")
    print("=" * 76)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
