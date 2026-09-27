"""一次性旧产物迁移脚本.

把 ``data/output/`` 下的旧流水线产物归档到 ``data/output/archive/legacy/``：

- ``01_preprocessed/``、``02_separated/``：早期预处理/分离脚本的产物
- 根级 ``{stem}_report.{json,md}``：早期报告（文件 stem 命名）

用法：
    uv run python scripts/migrate_legacy_output.py --dry-run   # 只看清单不移动
    uv run python scripts/migrate_legacy_output.py --yes       # 确认后执行归档
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

LEGACY_DIR_NAMES = ["01_preprocessed", "02_separated"]


def collect_targets(output_dir: Path) -> list[Path]:
    """收集需要归档的旧产物路径."""
    targets = [output_dir / name for name in LEGACY_DIR_NAMES if (output_dir / name).exists()]
    targets.extend(
        p
        for p in sorted(output_dir.iterdir())
        if p.is_file() and p.stem.endswith("_report") and p.suffix in (".json", ".md")
    )
    return targets


def main() -> None:
    parser = argparse.ArgumentParser(description="归档 data/output 下的旧产物")
    parser.add_argument("--dry-run", action="store_true", help="只打印将归档的清单，不执行")
    parser.add_argument("--yes", action="store_true", help="确认执行归档")
    args = parser.parse_args()

    output_dir = Path("data/output")
    if not output_dir.exists():
        print(f"目录不存在，无需处理: {output_dir}")
        return

    targets = collect_targets(output_dir)
    if not targets:
        print("没有发现需要归档的旧产物。")
        return

    legacy_root = output_dir / "archive" / "legacy"
    print(f"将归档 {len(targets)} 项旧产物到 {legacy_root}/：")
    for target in targets:
        size_mb = (
            sum(p.stat().st_size for p in target.rglob("*") if p.is_file()) / (1024 * 1024)
            if target.is_dir()
            else target.stat().st_size / (1024 * 1024)
        )
        print(f"  - {target} ({size_mb:.1f} MB)")

    if args.dry_run:
        print("（--dry-run 模式，未执行任何操作）")
        return
    if not args.yes:
        print("未带 --yes 参数，已取消。确认归档请加 --yes。")
        return

    legacy_root.mkdir(parents=True, exist_ok=True)
    for target in targets:
        dest = legacy_root / target.name
        if dest.exists():
            print(f"跳过（目标已存在）: {dest}")
            continue
        shutil.move(str(target), str(dest))
        print(f"已归档: {target} -> {dest}")

    print("旧产物归档完成。")


if __name__ == "__main__":
    main()
