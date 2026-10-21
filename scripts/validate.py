#!/usr/bin/env python3
"""Validate skill metadata, Python helpers, and repository hygiene."""

from __future__ import annotations

import argparse
import json
import py_compile
import re
import subprocess
import sys
import tempfile
from pathlib import Path

NAME_RX = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
FRONTMATTER_RX = re.compile(r"\A---\s*\r?\n(?P<body>.*?)\r?\n---\s*(?:\r?\n|\Z)", re.S)
SECRET_ASSIGNMENT_RX = re.compile(
    r"^[\t ]*(?:export[\t ]+)?[A-Z0-9_]*(?:PASSWORD|SECRET|TOKEN|API_KEY)[A-Z0-9_]*[\t ]*[:=][\t ]*(?P<value>[^\r\n#]*?)[\t ]*$",
    re.IGNORECASE | re.MULTILINE,
)
PRIVATE_KEY_RX = re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")


def frontmatter(path: Path) -> dict[str, str]:
    match = FRONTMATTER_RX.match(path.read_text(encoding="utf-8-sig"))
    if not match:
        raise ValueError("缺少 YAML frontmatter")
    result: dict[str, str] = {}
    for line in match.group("body").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        key, separator, value = line.partition(":")
        if separator:
            result[key.strip()] = value.strip().strip('"\'')
    return result


def validate_skills(root: Path) -> list[str]:
    errors: list[str] = []
    skills_root = root / "skills"
    skill_dirs = sorted(path for path in skills_root.iterdir() if path.is_dir())
    if not skill_dirs:
        return ["skills/ 下没有技能"]
    for skill in skill_dirs:
        entry = skill / "SKILL.md"
        if not entry.is_file():
            errors.append(f"{skill.name}: 缺少 SKILL.md")
            continue
        try:
            meta = frontmatter(entry)
        except ValueError as error:
            errors.append(f"{skill.name}: {error}")
            continue
        name = meta.get("name", "")
        description = meta.get("description", "")
        if not NAME_RX.fullmatch(name):
            errors.append(f"{skill.name}: name 不合法：{name!r}")
        if name != skill.name:
            errors.append(f"{skill.name}: frontmatter name 必须与目录名一致")
        if len(description) < 20:
            errors.append(f"{skill.name}: description 过短或缺失")
        text = entry.read_text(encoding="utf-8")
        for rel in re.findall(r"\[[^]]+\]\((?P<path>(?:references|scripts|assets)/[^)#]+)(?:#[^)]+)?\)", text):
            if not (skill / rel).exists():
                errors.append(f"{skill.name}: 链接目标不存在：{rel}")
    return errors


def validate_python(root: Path) -> list[str]:
    errors: list[str] = []
    scripts = sorted(root.rglob("*.py"))
    with tempfile.TemporaryDirectory(prefix="agent-skills-bytecode-") as temporary:
        for source in scripts:
            target = Path(temporary) / (source.relative_to(root).as_posix().replace("/", "__") + "c")
            try:
                py_compile.compile(str(source), cfile=str(target), doraise=True)
            except py_compile.PyCompileError as error:
                errors.append(f"{source.relative_to(root)}: {error.msg}")
                continue
            if source.name in {"jenkins_deploy.py", "mobile_pack.py", "shot.py"}:
                process = subprocess.run(
                    [sys.executable, str(source), "--help"],
                    cwd=root,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    capture_output=True,
                    timeout=20,
                )
                if process.returncode != 0:
                    errors.append(
                        f"{source.relative_to(root)} --help 失败：{(process.stderr or process.stdout).strip()[:300]}"
                    )
    return errors


def scan_files(root: Path) -> list[str]:
    errors: list[str] = []
    forbidden_terms = [
        "hf" + "zh",
        "fd" + "sure",
        "106." + "15.153.80",
        "172." + "16.0.",
        "c4bd" + "21ee-53fd-4122-8083-800e40204155",
        "78Db" + "HkvGCb64MMHt",
        "9Lvh" + "59ms9UvJessG",
        "CBdM" + "9HgZKrN87L8j",
    ]
    ignored_suffixes = {".pyc"}
    for path in root.rglob("*"):
        if not path.is_file() or ".git" in path.parts or path.suffix in ignored_suffixes:
            continue
        if path.name == "validate.py":
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            errors.append(f"{path.relative_to(root)}: 非 UTF-8 文本文件")
            continue
        lower = text.lower()
        for term in forbidden_terms:
            if term.lower() in lower:
                errors.append(f"{path.relative_to(root)}: 含项目绑定或敏感值：{term[:4]}…")
        if PRIVATE_KEY_RX.search(text):
            errors.append(f"{path.relative_to(root)}: 含私钥内容")
        for match in SECRET_ASSIGNMENT_RX.finditer(text):
            value = match.group("value").strip()
            if (
                not value
                or value.startswith(("$", "<", "{", "your-", "example-"))
                or value in {"''", '""'}
                or "YOUR_" in value.upper()
            ):
                continue
            if len(value) >= 16 and re.fullmatch(r"[A-Za-z0-9_+/=.-]+", value):
                errors.append(f"{path.relative_to(root)}: 疑似硬编码凭据")
                break
    return errors


def validate_example_config(root: Path) -> list[str]:
    try:
        data = json.loads((root / "config" / "agent-skills.example.json").read_text(encoding="utf-8"))
    except Exception as error:  # noqa: BLE001 - report malformed sample directly
        return [f"配置示例不是合法 JSON：{error}"]
    sections = {"jenkins", "mobilePack", "pingcode", "shot"}
    missing = sorted(sections - set(data))
    return [f"配置示例缺少章节：{name}" for name in missing]


def configure_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass


def main() -> int:
    configure_stdio()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=str(Path(__file__).resolve().parents[1]))
    args = parser.parse_args()
    root = Path(args.root).resolve()
    errors = []
    errors.extend(validate_skills(root))
    errors.extend(validate_python(root))
    errors.extend(scan_files(root))
    errors.extend(validate_example_config(root))
    if errors:
        print("校验失败：", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print(f"校验通过：{root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
