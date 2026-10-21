#!/usr/bin/env python3
"""Install reusable skills into a project's .agents/skills directory."""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path


def available_skills(repo_root: Path) -> list[str]:
    base = repo_root / "skills"
    return sorted(path.name for path in base.iterdir() if (path / "SKILL.md").is_file())


def resolve_target(value: str) -> Path:
    path = Path(value).expanduser().resolve()
    if not path.is_dir():
        raise SystemExit(f"目标项目不存在或不是目录：{path}")
    return path


def safe_replace(source: Path, destination: Path, skills_root: Path, force: bool) -> None:
    destination_resolved = destination.resolve()
    try:
        destination_resolved.relative_to(skills_root.resolve())
    except ValueError as error:
        raise SystemExit(f"拒绝写入技能目录以外的位置：{destination_resolved}") from error
    if destination.exists():
        if not force:
            raise SystemExit(f"目标技能已存在：{destination}\n需要更新时加 --force")
        if destination.is_dir():
            shutil.rmtree(destination)
        else:
            destination.unlink()
    shutil.copytree(
        source,
        destination,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store"),
    )


def copy_example(source: Path, destination: Path, force: bool) -> None:
    if destination.exists() and not force:
        print(f"保留已有配置示例：{destination}")
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    print(f"已写入配置示例：{destination}")


def configure_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass


def main() -> int:
    configure_stdio()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", required=True, help="目标项目根目录")
    parser.add_argument(
        "--skills",
        nargs="+",
        default=None,
        help="要安装的技能名；默认安装全部",
    )
    parser.add_argument("--force", action="store_true", help="覆盖目标中已存在的同名技能")
    parser.add_argument("--no-examples", action="store_true", help="不复制项目配置示例")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    names = available_skills(repo_root)
    selected = args.skills or names
    unknown = sorted(set(selected) - set(names))
    if unknown:
        raise SystemExit("未知技能：" + "、".join(unknown) + f"\n可用技能：{', '.join(names)}")

    target = resolve_target(args.target)
    skills_root = target / ".agents" / "skills"
    skills_root.mkdir(parents=True, exist_ok=True)
    for name in selected:
        source = repo_root / "skills" / name
        destination = skills_root / name
        safe_replace(source, destination, skills_root, args.force)
        print(f"已安装技能：{name} -> {destination}")

    if not args.no_examples:
        copy_example(
            repo_root / "config" / "agent-skills.example.json",
            target / ".agent-skills.example.json",
            args.force,
        )
        copy_example(
            repo_root / "config" / "credentials.env.example",
            target / ".agent-skills.env.example",
            args.force,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
