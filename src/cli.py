"""命令行入口."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

import click

from .config import ensure_dirs, load_config
from .embeddings import crop_audio_segment
from .enrollment import EnrollmentManager
from .pipeline import Pipeline
from .watcher import Watcher


@click.group()
@click.option("--config", "config_path", default="config.yaml", help="配置文件路径")
@click.pass_context
def cli(ctx: click.Context, config_path: str) -> None:
    """日常录音分析工具 CLI."""
    ctx.ensure_object(dict)
    config = load_config(config_path)
    ensure_dirs(config)
    ctx.obj["config"] = config


@cli.command()
@click.argument("audio_path", type=click.Path(exists=True))
@click.pass_context
def register(ctx: click.Context, audio_path: str) -> None:
    """注册用户声纹."""
    config = ctx.obj["config"]
    manager = EnrollmentManager(config)
    manager.enroll(audio_path)
    click.echo("声纹注册完成。")


@cli.command()
@click.pass_context
def watch(ctx: click.Context) -> None:
    """启动文件夹监控."""
    config = ctx.obj["config"]
    pipeline = Pipeline(config)
    watcher = Watcher(config, pipeline)
    click.echo(f"开始监控: {config['input_dir']}")
    watcher.start()


@cli.command()
@click.argument("audio_path", type=click.Path(exists=True))
@click.pass_context
def analyze(ctx: click.Context, audio_path: str) -> None:
    """单次分析指定录音."""
    config = ctx.obj["config"]
    pipeline = Pipeline(config)
    result = pipeline.process(audio_path)
    click.echo(f"分析完成，报告已保存到: {config['output_dir']}")
    click.echo(f"用户语音时长: {result.user_speech_sec:.1f}s / {result.duration_sec:.1f}s")


@cli.command()
@click.argument("audio_path", type=click.Path(exists=True))
@click.option(
    "--confirm",
    multiple=True,
    help="确认是用户本人的时段, 格式: start,end(秒), 可多次指定",
)
@click.option(
    "--deny",
    multiple=True,
    help="否认是用户本人的时段, 格式: start,end(秒), 可多次指定",
)
@click.pass_context
def correct(
    ctx: click.Context, audio_path: str, confirm: tuple[str, ...], deny: tuple[str, ...]
) -> None:
    """根据人工反馈增量更新声纹模型.

    示例:
        speaking-analysis correct audio.wav --confirm 1.2,3.4 --deny 5.6,7.8
    """
    config = ctx.obj["config"]
    manager = EnrollmentManager(config)

    positive_segments = _parse_time_segments(confirm)
    negative_segments = _parse_time_segments(deny)

    if not positive_segments and not negative_segments:
        click.echo("请至少提供一个 --confirm 或 --deny 时段。", err=True)
        raise click.Abort()

    with tempfile.TemporaryDirectory() as tmpdir:
        positive_paths = _crop_segments(audio_path, positive_segments, tmpdir, "pos")
        negative_paths = _crop_segments(audio_path, negative_segments, tmpdir, "neg")
        manager.update_voiceprint(positive_paths, negative_paths)

    click.echo(
        f"声纹已增量更新: 确认 {len(positive_paths)} 段, 否认 {len(negative_paths)} 段。"
    )


def _parse_time_segments(raw_segments: tuple[str, ...]) -> list[tuple[float, float]]:
    """解析 start,end 字符串为元组列表."""
    parsed: list[tuple[float, float]] = []
    for raw in raw_segments:
        parts = raw.split(",")
        if len(parts) != 2:
            raise click.BadParameter(f"时段格式错误: {raw}, 应为 start,end")
        try:
            start = float(parts[0])
            end = float(parts[1])
        except ValueError as exc:
            raise click.BadParameter(f"时段必须是数字: {raw}") from exc
        if end <= start:
            raise click.BadParameter(f"时段结束必须大于开始: {raw}")
        parsed.append((start, end))
    return parsed


def _crop_segments(
    audio_path: str,
    segments: list[tuple[float, float]],
    tmpdir: str,
    prefix: str,
) -> list[str]:
    """将时段裁剪为临时音频文件并返回路径列表."""
    paths: list[str] = []
    for idx, (start, end) in enumerate(segments):
        output_path = Path(tmpdir) / f"{prefix}_{idx:04d}_{start:.3f}_{end:.3f}.wav"
        crop_audio_segment(audio_path, start, end, output_path)
        paths.append(str(output_path))
    return paths


if __name__ == "__main__":
    cli()
