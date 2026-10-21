#!/usr/bin/env python3
"""Build an Android APK or iOS IPA with HBuilderX from project configuration."""

from __future__ import annotations

import argparse
import ctypes
import json
import os
from pathlib import Path
import queue
import re
import signal
import subprocess
import sys
import tempfile
import threading
import time
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Iterator
from urllib.request import urlopen


class PackError(Exception):
    pass


def configure_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass


def find_config(explicit: str | None) -> Path:
    if explicit:
        path = Path(explicit).expanduser().resolve()
        if not path.is_file():
            raise PackError(f"配置文件不存在：{path}")
        return path
    configured = os.environ.get("AGENT_SKILLS_CONFIG")
    if configured:
        path = Path(configured).expanduser().resolve()
        if not path.is_file():
            raise PackError(f"AGENT_SKILLS_CONFIG 指向的文件不存在：{path}")
        return path
    for directory in (Path.cwd(), *Path.cwd().parents):
        path = directory / ".agent-skills.json"
        if path.is_file():
            return path.resolve()
    raise PackError("找不到 .agent-skills.json；在项目根目录创建配置，或传入 --config")


def read_json(path: Path) -> dict[str, Any]:
    content = path.read_text(encoding="utf-8-sig")
    strings_or_comments = r'"(?:\\.|[^"\\])*"|//[^\r\n]*|/\*[\s\S]*?\*/'
    content = re.sub(
        strings_or_comments,
        lambda match: match.group(0) if match.group(0).startswith('"') else " ",
        content,
    )
    content = re.sub(
        r'"(?:\\.|[^"\\])*"|,\s*(?=[}\]])',
        lambda match: match.group(0) if match.group(0).startswith('"') else "",
        content,
    )
    value = json.loads(content)
    if not isinstance(value, dict):
        raise PackError(f"manifest 不是 JSON 对象：{path}")
    return value


def resolve_path(base: Path, value: str) -> Path:
    path = Path(value).expanduser()
    return path.resolve() if path.is_absolute() else (base / path).resolve()


def load_project(config_path: Path, project_override: str | None) -> tuple[dict[str, Any], Path]:
    data = json.loads(config_path.read_text(encoding="utf-8-sig"))
    section = data.get("mobilePack")
    if not isinstance(section, dict):
        raise PackError("配置缺少 mobilePack 章节")
    project = resolve_path(
        config_path.parent,
        project_override or str(section.get("project", ".")),
    )
    if not project.is_dir():
        raise PackError(f"项目目录不存在：{project}")
    return section, project


def required(config: dict[str, Any], key: str, label: str | None = None) -> str:
    value = str(config.get(key, "")).strip()
    if not value:
        raise PackError(f"mobilePack 缺少配置：{label or key}")
    return value


def resolve_file(project: Path, value: str, label: str, check: bool) -> Path:
    path = resolve_path(project, value)
    if check and not path.is_file():
        raise PackError(f"{label} 指向的文件不存在：{path}")
    return path


def resolve_secret(
    project: Path,
    config: dict[str, Any],
    env_key: str,
    file_key: str,
    label: str,
    check: bool,
    secrets: list[str],
) -> str:
    environment_name = str(config.get(env_key, "")).strip()
    value = os.environ.get(environment_name, "") if environment_name else ""
    if not value and config.get(file_key):
        path = resolve_path(project, str(config[file_key]))
        if path.is_file():
            value = path.read_text(encoding="utf-8").rstrip("\r\n")
        elif check:
            raise PackError(f"{label} 密码文件不存在：{path}")
    if check and not value:
        raise PackError(
            f"缺少 {label} 密码：设置环境变量 {environment_name or env_key} "
            f"或在配置中提供 {file_key}"
        )
    if value:
        secrets.append(value)
    return value


def make_pack_config(
    project: Path,
    section: dict[str, Any],
    platform: str,
    check: bool,
) -> tuple[dict[str, Any], list[str]]:
    secrets: list[str] = []
    options = {
        "project": str(project),
        "platform": platform,
        "iscustom": False,
        "safemode": False,
        "sourceMap": False,
        "isconfusion": False,
        "splashads": False,
        "rpads": False,
        "unimpads": False,
    }
    options.update(section.get("packOptions") or {})
    if platform == "android":
        config = section.get("android")
        if not isinstance(config, dict):
            raise PackError("配置缺少 mobilePack.android")
        cert_file = required(config, "certFile")
        key_password = resolve_secret(
            project,
            config,
            "certPasswordEnv",
            "certPasswordFile",
            "Android key",
            check,
            secrets,
        )
        store_password = resolve_secret(
            project,
            config,
            "storePasswordEnv",
            "storePasswordFile",
            "Android keystore",
            check,
            secrets,
        )
        options[platform] = {
            "packagename": required(config, "packageName"),
            "androidpacktype": str(config.get("androidPackType", "0")),
            "certalias": required(config, "certAlias"),
            "certfile": str(resolve_file(project, cert_file, "Android keystore", check)),
            "certpassword": key_password,
            "storePassword": store_password or key_password,
        }
    else:
        config = section.get("ios")
        if not isinstance(config, dict):
            raise PackError("配置缺少 mobilePack.ios")
        cert_password = resolve_secret(
            project,
            config,
            "certPasswordEnv",
            "certPasswordFile",
            "iOS certificate",
            check,
            secrets,
        )
        options[platform] = {
            "bundle": required(config, "bundleId"),
            "certfile": str(resolve_file(project, required(config, "certFile"), "iOS certificate", check)),
            "profile": str(resolve_file(project, required(config, "profile"), "iOS profile", check)),
            "certpassword": cert_password,
            "supporteddevice": str(config.get("supportedDevices", "iPhone")),
        }
        devices = str(options[platform]["supporteddevice"]).split(",")
        if any(device not in ("iPhone", "iPad") for device in devices):
            raise PackError("iOS supportedDevices 只能是 iPhone、iPad 或 iPhone,iPad")
    return options, secrets


def redact(text: str, secrets: list[str]) -> str:
    for secret in sorted(set(secrets), key=len, reverse=True):
        text = text.replace(secret, "[REDACTED]")
        text = text.replace(json.dumps(secret)[1:-1], "[REDACTED]")
    return re.sub(
        r'([?&](?:token|access_token|password|secret|key)=)[^&\s<>"\'）)]+',
        r"\1[REDACTED]",
        text,
        flags=re.IGNORECASE,
    )

def process_running(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(0x1000, False, pid)
        if handle:
            kernel32.CloseHandle(handle)
            return True
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


@contextmanager
def build_lock(path: Path) -> Iterator[None]:
    descriptor: int | None = None
    for _ in range(2):
        try:
            descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            break
        except FileExistsError:
            try:
                pid = int(path.read_text(encoding="ascii").strip())
            except (OSError, ValueError):
                pid = 0
            if process_running(pid):
                raise PackError(f"本项目已有打包脚本运行（PID {pid}）")
            path.unlink(missing_ok=True)
    if descriptor is None:
        raise PackError(f"无法创建打包锁：{path}")
    try:
        os.write(descriptor, str(os.getpid()).encode("ascii"))
        yield
    finally:
        os.close(descriptor)
        path.unlink(missing_ok=True)


def run_cli(
    cli: Path,
    arguments: list[str],
    secrets: list[str],
    log: Any,
    timeout: int,
) -> str:
    process = subprocess.Popen(
        [str(cli), *arguments],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    lines: queue.Queue[str | None] = queue.Queue()

    def collect() -> None:
        try:
            if process.stdout is not None:
                for line in process.stdout:
                    lines.put(line)
        finally:
            lines.put(None)

    reader = threading.Thread(target=collect, daemon=True)
    reader.start()
    started = time.monotonic()
    output: list[str] = []
    try:
        while True:
            remaining = timeout - (time.monotonic() - started)
            if remaining <= 0:
                raise PackError("等待 HBuilderX 超时；云端任务可能仍在运行，请先查询 pack status")
            try:
                line = lines.get(timeout=min(25, remaining))
            except queue.Empty:
                print(f"仍在等待 HBuilderX，已等待 {int(time.monotonic() - started)} 秒…", flush=True)
                continue
            if line is None:
                break
            output.append(line)
            safe = redact(line, secrets)
            log.write(safe)
            log.flush()
            if safe.strip():
                print(safe, end="", flush=True)
        code = process.wait(timeout=max(1, timeout - (time.monotonic() - started)))
        if code != 0:
            raise PackError(f"HBuilderX CLI 退出码为 {code}")
        return "".join(output)
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        reader.join(timeout=2)
        if process.stdout is not None:
            process.stdout.close()


def download(url: str, target: Path) -> int:
    partial = target.with_suffix(target.suffix + ".part")
    partial.unlink(missing_ok=True)
    try:
        with urlopen(url, timeout=60) as response, partial.open("xb") as output:
            first = response.read(4)
            if first != b"PK\x03\x04":
                raise PackError("下载内容不是 APK/IPA，可能返回了提示页")
            output.write(first)
            size = len(first)
            reported = time.monotonic()
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                output.write(chunk)
                size += len(chunk)
                if time.monotonic() - reported >= 20:
                    print(f"已下载 {size / 1024 / 1024:.1f} MB…", flush=True)
                    reported = time.monotonic()
            length = response.headers.get("Content-Length")
            if length and int(length) != size:
                raise PackError("安装包下载不完整")
        partial.replace(target)
        return size
    finally:
        partial.unlink(missing_ok=True)


def choose_platform() -> str:
    if not sys.stdin.isatty():
        raise PackError("请先选择平台，再传入 --platform android 或 --platform ios")
    print("选择打包平台：\n  1. Android（APK）\n  2. iOS（IPA）")
    while True:
        choice = input("请输入 1/2 或 android/ios：").strip().lower()
        if choice in ("1", "android"):
            return "android"
        if choice in ("2", "ios"):
            return "ios"
        print("请输入 Android 或 iOS")


def preview(config: dict[str, Any], platform: str, secrets: list[str]) -> dict[str, Any]:
    result = json.loads(json.dumps(config))
    for key in ("certpassword", "storePassword"):
        if key in result.get(platform, {}):
            result[platform][key] = "[REDACTED]" if result[platform][key] else "[MISSING]"
    return result


def main(argv: list[str] | None = None) -> int:
    configure_stdio()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", help=".agent-skills.json 路径")
    parser.add_argument("--platform", choices=("android", "ios"), help="不传时在终端选择")
    parser.add_argument("--project", help="覆盖配置中的项目目录")
    parser.add_argument("--timeout", type=int, help="覆盖配置中的云打包超时秒数")
    parser.add_argument("--dry-run", action="store_true", help="只输出脱敏配置")
    args = parser.parse_args(argv)

    config_path = find_config(args.config)
    section, project = load_project(config_path, args.project)
    platform = args.platform or choose_platform()
    check = not args.dry_run
    config, secrets = make_pack_config(project, section, platform, check)
    if args.dry_run:
        print(json.dumps(preview(config, platform, secrets), ensure_ascii=False, indent=2))
        return 0

    manifest_path = resolve_path(project, str(section.get("manifest", "src/manifest.json")))
    if not manifest_path.is_file():
        raise PackError(f"manifest 不存在：{manifest_path}")
    manifest = read_json(manifest_path)
    cli_name = str(section.get("cliEnv", "")).strip()
    cli_value = os.environ.get(cli_name, "") if cli_name else ""
    cli_value = cli_value or str(section.get("cli", "")).strip()
    if not cli_value:
        raise PackError(f"未配置 HBuilderX CLI；设置 {cli_name or 'cliEnv'} 或 mobilePack.cli")
    cli = Path(cli_value).expanduser().resolve()
    if not cli.is_file():
        raise PackError(f"HBuilderX CLI 不存在：{cli}")
    if section.get("requireNodeModules", True) and not (project / "node_modules").is_dir():
        raise PackError(f"项目缺少 node_modules：{project / 'node_modules'}")

    version = str(manifest.get("versionName", "unknown"))
    version_code = str(manifest.get("versionCode", "unknown"))
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    prefix = str(section.get("namePrefix", project.name))
    pattern = str(
        section.get(
            "artifactPattern",
            "{name}-{platform}-{version}-{versionCode}-{timestamp}",
        )
    )
    name = pattern.format(
        name=prefix,
        platform=platform,
        version=version,
        versionCode=version_code,
        timestamp=stamp,
    )
    name = re.sub(r"[^A-Za-z0-9._-]", "_", name)
    output_dir = resolve_path(project, str(section.get("outputDir", "unpackage/release")))
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / (name + (".apk" if platform == "android" else ".ipa"))
    log_path = output_dir / (name + ".log")
    timeout = int(args.timeout or section.get("timeoutSec", 2700))
    if timeout <= 0:
        raise PackError("--timeout 必须大于 0")

    with build_lock(output_dir / ".mobile-pack.lock"):
        print(f"开始打包 {platform}，版本 {version} ({version_code})\n日志：{log_path}", flush=True)
        with log_path.open("x", encoding="utf-8") as log:
            run_cli(cli, ["open"], secrets, log, 60)
            run_cli(cli, ["project", "open", "--path", str(project)], secrets, log, 60)
            descriptor, temporary_name = tempfile.mkstemp(prefix="mobile-pack-", suffix=".json")
            temporary = Path(temporary_name)
            try:
                with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                    json.dump(config, handle, ensure_ascii=False)
                output = run_cli(cli, ["pack", "--config", str(temporary)], secrets, log, timeout)
            finally:
                temporary.unlink(missing_ok=True)
            links = re.findall(r'下载地址\s*[:：]\s*(https://[^\s<>"\'）)]+)', output)
            if not re.search(r"打包成功\s*[:：]", output) or not links:
                raise PackError("CLI 未返回打包成功和下载地址；先查看日志或查询 pack status")
            print("云端打包成功，正在下载安装包…", flush=True)
            try:
                size = download(links[-1], target)
            except Exception as error:
                raise PackError(
                    "云端打包成功但下载失败；使用日志中的地址重试，不要重新打包。\n"
                    + redact(str(error), secrets)
                ) from error
            message = f"安装包已保存：{target}\n大小：{size / 1024 / 1024:.1f} MB\n"
            print(message, end="")
            log.write(message)
    return 0


def interrupted(signum: int, frame: Any) -> None:
    raise KeyboardInterrupt


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, interrupted)
    try:
        raise SystemExit(main())
    except (KeyboardInterrupt, EOFError):
        print("已停止本地脚本；若已提交云端，请先查询 pack status", file=sys.stderr)
        raise SystemExit(130)
    except (PackError, OSError, ValueError, subprocess.SubprocessError) as error:
        print(f"打包未完成：{error}", file=sys.stderr)
        raise SystemExit(1)
