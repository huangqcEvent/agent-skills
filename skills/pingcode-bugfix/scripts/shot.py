#!/usr/bin/env python3
"""Take reproducible PingCode evidence screenshots using project configuration."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

STAGES = {"before": "修改前", "after": "修改后", "修改前": "修改前", "修改后": "修改后"}


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
            raise RuntimeError(f"配置文件不存在：{path}")
        return path
    configured = os.environ.get("AGENT_SKILLS_CONFIG")
    if configured:
        path = Path(configured).expanduser().resolve()
        if not path.is_file():
            raise RuntimeError(f"AGENT_SKILLS_CONFIG 指向的文件不存在：{path}")
        return path
    for directory in (Path.cwd(), *Path.cwd().parents):
        path = directory / ".agent-skills.json"
        if path.is_file():
            return path.resolve()
    raise RuntimeError("找不到 .agent-skills.json；在项目根目录创建配置，或传入 --config")


def load_target(config_path: Path, name: str) -> tuple[dict[str, Any], dict[str, Any]]:
    data = json.loads(config_path.read_text(encoding="utf-8-sig"))
    shot = data.get("shot")
    if not isinstance(shot, dict):
        raise RuntimeError("配置缺少 shot 章节")
    targets = shot.get("targets")
    if not isinstance(targets, dict) or name not in targets:
        raise RuntimeError(f"shot.targets 中没有目标：{name}")
    target = targets[name]
    if not isinstance(target, dict):
        raise RuntimeError(f"shot.targets.{name} 必须是对象")
    if not str(target.get("baseUrl", "")).startswith(("http://", "https://")):
        raise RuntimeError(f"shot.targets.{name}.baseUrl 必须是 HTTP(S) 地址")
    return shot, target


def build_url(target: dict[str, Any], route: str) -> str:
    if route.startswith(("http://", "https://")):
        return route
    base = str(target["baseUrl"]).rstrip("/")
    prefix = str(target.get("routePrefix", "")).lstrip("/")
    route = route.lstrip("#/")
    if prefix:
        base += "/" + prefix
        if route and not base.endswith("/"):
            base += "/"
        return base + route
    return base + ("/" + route if route else "")


def evidence_path(shot: dict[str, Any], item: str, stage: str, name: str) -> Path:
    if stage not in STAGES:
        raise ValueError("stage 只能是 before / after / 修改前 / 修改后")
    configured = shot.get("evidenceDir") or "~/.pingcode-mcp/evidence"
    root = Path(str(configured)).expanduser()
    safe_item = re.sub(r'[\\/:*?"<>|\s]+', "-", item).strip("-") or "work-item"
    safe_name = re.sub(r'[\\/:*?"<>|\s]+', "-", name).strip("-") or "截图"
    return root / safe_item.upper() / f"{STAGES[stage]}-{safe_name}.png"


def parse_size(text: str) -> tuple[int, int]:
    match = re.fullmatch(r"(\d+)[xX*](\d+)", text)
    if not match:
        raise argparse.ArgumentTypeError("尺寸写成宽x高，例如 440x956")
    return int(match.group(1)), int(match.group(2))


def open_page(playwright: Any, shot: dict[str, Any], target: dict[str, Any], size: tuple[int, int]) -> tuple[Any, Any]:
    base = str(target["baseUrl"])
    host = re.sub(r"^https?://", "", base).split("/", 1)[0].split(":", 1)[0]
    arguments: list[str] = []
    if target.get("noProxy", True):
        arguments.append("--no-proxy-server")
    if target.get("blockExternal", True):
        exclusions = ", ".join(["127.0.0.1", "localhost", host])
        arguments.append(f"--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE {exclusions}")
    launch: dict[str, Any] = {"args": arguments}
    channel = shot.get("browserChannel") or os.environ.get("PLAYWRIGHT_CHANNEL")
    if channel:
        launch["channel"] = str(channel)
    browser = playwright.chromium.launch(**launch)
    options: dict[str, Any] = {
        "viewport": {"width": size[0], "height": size[1]},
        "device_scale_factor": float(target.get("deviceScaleFactor", 1)),
        "locale": str(target.get("locale", "zh-CN")),
    }
    if target.get("mobile"):
        options.update(is_mobile=True, has_touch=True)
    return browser, browser.new_context(**options).new_page()


def tap(page: Any, text: str, wait: int = 1200) -> None:
    matches = page.get_by_text(text, exact=True)
    if matches.count() == 0:
        raise RuntimeError(f"页面上找不到文字：{text}")
    visible = [matches.nth(index) for index in range(matches.count()) if matches.nth(index).is_visible()]
    if visible:
        visible[0].click(force=True)
    else:
        matches.first.dispatch_event("click")
    page.wait_for_timeout(wait)


def login_page(page: Any, target: dict[str, Any], account: str) -> None:
    if account == "none":
        return
    config = target.get("login")
    if not isinstance(config, dict):
        if account == "default":
            return
        raise RuntimeError("没有登录配置；使用 --login none 或补齐 target.login")
    path = str(config.get("path", "login"))
    page.goto(build_url(target, path))
    page.wait_for_timeout(int(config.get("loadWaitMs", 1200)))
    if account == "default":
        user = os.environ.get(str(config.get("userEnv", "")), "")
        password = os.environ.get(str(config.get("passwordEnv", "")), "")
    elif ":" in account:
        user, password = account.split(":", 1)
    else:
        raise RuntimeError("--login 只接受 none、default 或 user:password")
    if not user or not password:
        raise RuntimeError(
            f"缺少登录账号；设置 {config.get('userEnv')} 和 {config.get('passwordEnv')}"
        )
    user_selector = str(config.get("userSelector", "input[type=text]"))
    password_selector = str(config.get("passwordSelector", "input[type=password]"))
    page.locator(user_selector).first.fill(user)
    page.locator(password_selector).first.fill(password)
    if config.get("agreementText"):
        tap(page, str(config["agreementText"]), int(config.get("agreementWaitMs", 200)))
    elif config.get("agreementSelector"):
        page.locator(str(config["agreementSelector"])).first.click(force=True)
    submit = str(config.get("submitSelector", "button[type=submit]"))
    page.locator(submit).first.click(force=True)
    excludes = str(config.get("successUrlExcludes", "login"))
    try:
        page.wait_for_url(lambda url: excludes not in url, timeout=int(config.get("loginTimeoutMs", 15000)))
    except Exception as error:
        raise RuntimeError(f"登录未离开包含“{excludes}”的地址：{page.url}") from error
    page.wait_for_timeout(int(config.get("successWaitMs", 500)))

def toast_messages(page: Any, selectors: list[str]) -> list[str]:
    found: list[str] = []
    for selector in selectors:
        locator = page.locator(selector)
        for index in range(locator.count()):
            item = locator.nth(index)
            if item.is_visible():
                text = item.inner_text().strip()
                if text:
                    found.append(text)
    return found


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("target", help="shot.targets 中的目标名，例如 app 或 admin")
    result.add_argument("--config", help=".agent-skills.json 路径")
    result.add_argument("--route", required=True, help="目标内路由或完整 HTTP(S) 地址")
    result.add_argument("--login", default="default", help="none / default / user:password")
    result.add_argument("--tap", action="append", default=[], help="按顺序点击的可见文字，可重复")
    result.add_argument("--selector", help="截图前等待的 CSS 选择器")
    result.add_argument("--wait", type=int, default=1500, help="操作完成后的等待毫秒数")
    result.add_argument("--size", type=parse_size, help="视口宽x高，默认读取 target.viewport")
    result.add_argument("--full", action="store_true", help="整页截图")
    result.add_argument("--item", help="工作项编号")
    result.add_argument("--stage", help="before / after / 修改前 / 修改后")
    result.add_argument("--name", default="截图", help="场景名")
    result.add_argument("--out", help="输出路径；不用 --item/--stage 时必填")
    return result


def main(argv: list[str] | None = None) -> int:
    configure_stdio()
    args = parser().parse_args(argv)
    if args.out:
        output = Path(args.out).expanduser().resolve()
    elif args.item and args.stage:
        # Resolve after loading the project's evidence directory.
        output = Path()
    else:
        parser().error("需要 --out，或同时提供 --item 和 --stage")

    config_path = find_config(args.config)
    shot, target = load_target(config_path, args.target)
    if not args.out:
        output = evidence_path(shot, args.item, args.stage, args.name)
    viewport_value = target.get("viewport", [440, 956])
    size = args.size or (int(viewport_value[0]), int(viewport_value[1]))

    try:
        from playwright.sync_api import sync_playwright
    except ImportError as error:
        raise RuntimeError("缺少 Playwright；执行 pip install playwright") from error

    with sync_playwright() as playwright:
        browser, page = open_page(playwright, shot, target, size)
        try:
            login_page(page, target, args.login)
            page.goto(build_url(target, args.route))
            page.wait_for_timeout(int(target.get("routeLoadWaitMs", 2500)))
            if args.selector:
                page.wait_for_selector(args.selector, timeout=15000)
            for text in args.tap:
                tap(page, text)
            page.wait_for_timeout(args.wait)
            output.parent.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(output), full_page=args.full)
            print(f"saved {output}")
            messages = toast_messages(
                page,
                target.get("toastSelectors")
                or [".uni-toast", ".uni-sample-toast", ".el-message", ".ant-message-notice"],
            )
            if messages:
                print("提示：" + " | ".join(messages))
        finally:
            browser.close()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, ValueError, OSError) as error:
        print(f"截图失败：{error}", file=sys.stderr)
        raise SystemExit(1)
