#!/usr/bin/env python3
"""Configuration-driven Jenkins build, deployment, rollback, and status helper."""

from __future__ import annotations

import argparse
import base64
import http.cookiejar
import json
import os
import re
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any


class DeployError(Exception):
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
            raise DeployError(f"配置文件不存在：{path}")
        return path
    configured = os.environ.get("AGENT_SKILLS_CONFIG")
    if configured:
        path = Path(configured).expanduser().resolve()
        if not path.is_file():
            raise DeployError(f"AGENT_SKILLS_CONFIG 指向的文件不存在：{path}")
        return path
    for directory in (Path.cwd(), *Path.cwd().parents):
        path = directory / ".agent-skills.json"
        if path.is_file():
            return path.resolve()
    raise DeployError("找不到 .agent-skills.json；在项目根目录创建配置，或传入 --config")


def load_profile(config_path: Path, profile_name: str | None) -> tuple[dict[str, Any], Path]:
    data = json.loads(config_path.read_text(encoding="utf-8-sig"))
    section = data.get("jenkins")
    if not isinstance(section, dict):
        raise DeployError("配置缺少 jenkins 章节")
    profiles = section.get("profiles")
    if not isinstance(profiles, dict) or not profiles:
        raise DeployError("配置缺少 jenkins.profiles")
    name = profile_name or section.get("defaultProfile")
    if not name:
        raise DeployError("未传 --profile，且配置没有 jenkins.defaultProfile")
    profile = profiles.get(name)
    if not isinstance(profile, dict):
        raise DeployError(f"找不到 Jenkins profile：{name}")
    components = profile.get("components")
    if not isinstance(components, dict) or not components:
        raise DeployError(f"Jenkins profile {name} 缺少 components")
    return profile, config_path.parent.resolve()


def env_or_value(profile: dict[str, Any], value_key: str, env_key: str) -> str:
    env_name = profile.get(env_key)
    if env_name:
        return str(os.environ.get(env_name, "")).strip()
    return str(profile.get(value_key, "")).strip()


class Jenkins:
    def __init__(self, profile: dict[str, Any]):
        url = env_or_value(profile, "url", "urlEnv")
        user = env_or_value(profile, "username", "usernameEnv")
        token = env_or_value(profile, "token", "tokenEnv")
        if not (url and user and token):
            raise DeployError(
                "Jenkins 认证配置不完整；请检查 profile 中的 urlEnv、usernameEnv、tokenEnv "
                "以及对应环境变量"
            )
        self.base = url.rstrip("/") + "/"
        encoded = base64.b64encode(f"{user}:{token}".encode()).decode()
        self.headers = {"Authorization": "Basic " + encoded}
        handlers: list[Any] = [urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())]
        use_proxy = os.environ.get("JENKINS_USE_PROXY") == "1" or profile.get("useProxy") is True
        if not use_proxy:
            handlers.append(urllib.request.ProxyHandler({}))
        if os.environ.get("JENKINS_INSECURE") == "1" or profile.get("insecure") is True:
            handlers.append(urllib.request.HTTPSHandler(context=ssl._create_unverified_context()))
        self.opener = urllib.request.build_opener(*handlers)
        self.crumb: dict[str, str] | None = None

    def url(self, path_or_url: str) -> str:
        if path_or_url.startswith(("http://", "https://")):
            incoming = urllib.parse.urlsplit(path_or_url)
            base = urllib.parse.urlsplit(self.base)
            return urllib.parse.urlunsplit((base.scheme, base.netloc, incoming.path, incoming.query, ""))
        return urllib.parse.urljoin(self.base, path_or_url.lstrip("/"))

    def request(
        self,
        method: str,
        path: str,
        data: dict[str, Any] | None = None,
        ok: tuple[int, ...] = (200,),
    ) -> tuple[int, Any, bytes]:
        body = urllib.parse.urlencode(data).encode() if data is not None else None
        status = 0
        headers: Any = None
        content = b""
        for attempt in range(2):
            request_headers = dict(self.headers)
            if self.crumb:
                request_headers.update(self.crumb)
            request = urllib.request.Request(self.url(path), data=body, method=method, headers=request_headers)
            try:
                with self.opener.open(request, timeout=30) as response:
                    status, headers, content = response.status, response.headers, response.read()
            except urllib.error.HTTPError as error:
                status, headers, content = error.code, error.headers, error.read()
            except urllib.error.URLError as error:
                if method == "GET" and attempt == 0:
                    time.sleep(2)
                    continue
                raise DeployError(f"连不上 Jenkins：{error.reason}") from error
            if method == "POST" and status == 403 and b"crumb" in content.lower() and attempt == 0:
                self.crumb = self.fetch_crumb()
                continue
            break
        if status == 401:
            raise DeployError("Jenkins 认证失败（401）；检查用户名和 API Token")
        if status not in ok:
            detail = content[:400].decode("utf-8", "replace")
            raise DeployError(f"{method} {path} 返回 {status}：{detail}")
        return status, headers, content

    def fetch_crumb(self) -> dict[str, str]:
        _, _, content = self.request("GET", "crumbIssuer/api/json")
        data = json.loads(content)
        return {data["crumbRequestField"]: data["crumb"]}

    def json(self, path: str) -> dict[str, Any]:
        return json.loads(self.request("GET", path)[2] or b"{}")

    def text(self, path: str, missing_ok: bool = False) -> str | None:
        status, _, content = self.request("GET", path, ok=(200, 404) if missing_ok else (200,))
        return None if status == 404 else content.decode("utf-8", "replace")


def folder_path(folder: str) -> str:
    parts = [part for part in str(folder or "").split("/") if part]
    return "".join(f"job/{urllib.parse.quote(part, safe='')}/" for part in parts)


def job_path(profile: dict[str, Any], component: str) -> str:
    config = profile["components"][component]
    raw = str(config.get("job", "")).strip()
    if not raw:
        raise DeployError(f"组件 {component} 未配置 job")
    if raw.startswith(("http://", "https://", "/")):
        path = urllib.parse.urlsplit(raw).path if raw.startswith(("http://", "https://")) else raw
        return path.rstrip("/") + "/"
    return folder_path(profile.get("folder", "")) + f"job/{urllib.parse.quote(raw, safe='')}/"


def component_order(profile: dict[str, Any], selected: list[str] | None = None) -> list[str]:
    components = profile["components"]
    order = [name for name in profile.get("deploymentOrder", []) if name in components]
    order.extend(name for name in components if name not in order)
    if selected is None:
        return order
    unknown = sorted(set(selected) - set(components))
    if unknown:
        raise DeployError("未知组件：" + "、".join(unknown))
    return [name for name in order if name in selected]


def recent_builds(jenkins: Jenkins, job: str, limit: int = 30) -> list[dict[str, Any]]:
    tree = f"builds[number,result,building,timestamp,actions[parameters[name,value]]]{{0,{limit}}}"
    payload = jenkins.json(job + "api/json?tree=" + urllib.parse.quote(tree, safe="[],{}"))
    builds = payload.get("builds", [])
    for build in builds:
        params: dict[str, Any] = {}
        for action in build.get("actions") or []:
            for parameter in (action or {}).get("parameters", []) or []:
                params[parameter.get("name")] = parameter.get("value")
        build["params"] = params
    return builds


def build_info(jenkins: Jenkins, profile: dict[str, Any], component: str, number: int) -> dict[str, str]:
    artifact = str(profile.get("artifactPath", "")).strip()
    if not artifact:
        return {}
    artifact = artifact.format(component=component, build=number)
    text = jenkins.text(f"{job_path(profile, component)}{number}/{artifact}", missing_ok=True) or ""
    return dict(line.split("=", 1) for line in text.splitlines() if "=" in line)

def release_number(release: str) -> int | None:
    match = re.search(r"-(\d+)-", release)
    return int(match.group(1)) if match else None


def deployed_version(jenkins: Jenkins, profile: dict[str, Any], component: str) -> dict[str, Any]:
    params = profile.get("parameters", {})
    deployments = {str(params.get("deploy", "DEPLOY")), "DEPLOY"}
    rollbacks = {str(params.get("rollback", "ROLLBACK")), "ROLLBACK"}
    builds = [item for item in recent_builds(jenkins, job_path(profile, component), 50) if not item.get("building")]
    for index, build in enumerate(builds):
        if build.get("result") != "SUCCESS":
            continue
        action = str(build.get("params", {}).get(str(params.get("action", "ACTION")), ""))
        if action not in deployments | rollbacks:
            continue
        if action in deployments:
            info = build_info(jenkins, profile, component, int(build["number"]))
            return {
                "build": build["number"],
                "commit": info.get("commit") or info.get("COMMIT"),
                "release": info.get("release") or info.get("RELEASE"),
                "timestamp": build.get("timestamp"),
            }
        release = str(build.get("params", {}).get(str(params.get("rollbackRelease", "ROLLBACK_RELEASE")), ""))
        rolled = release_number(release)
        if rolled is None:
            continue
        for older in builds[index + 1 :]:
            if int(older.get("number", 0)) >= rolled or older.get("result") != "SUCCESS":
                continue
            older_action = str(older.get("params", {}).get(str(params.get("action", "ACTION")), ""))
            if older_action in deployments:
                info = build_info(jenkins, profile, component, int(older["number"]))
                return {
                    "build": older["number"],
                    "commit": info.get("commit") or info.get("COMMIT"),
                    "release": info.get("release") or info.get("RELEASE"),
                    "timestamp": older.get("timestamp"),
                }
    return {"build": None, "commit": None, "release": None, "timestamp": None}


def git(repo_root: Path, *args: str, check: bool = True) -> str:
    environment = dict(os.environ)
    for key in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY"):
        environment.pop(key, None)
    process = subprocess.run(
        ["git", *args],
        cwd=repo_root,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        env=environment,
    )
    if check and process.returncode != 0:
        raise DeployError(f"git {' '.join(args)} 失败：{process.stderr.strip()[:400]}")
    return process.stdout.strip()


def remote_head(repo_root: Path, remote: str, branch: str) -> str:
    output = git(repo_root, "ls-remote", remote, f"refs/heads/{branch}")
    if not output:
        raise DeployError(f"远端 {remote} 没有分支 {branch}")
    sha = output.split()[0]
    git(repo_root, "fetch", "-q", remote, branch)
    return sha


def commit_exists(repo_root: Path, sha: str | None) -> bool:
    if not sha:
        return False
    process = subprocess.run(
        ["git", "cat-file", "-e", f"{sha}^{{commit}}"],
        cwd=repo_root,
        capture_output=True,
    )
    return process.returncode == 0


def changed_files(repo_root: Path, old: str | None, new: str) -> list[str] | None:
    if not old or not commit_exists(repo_root, old):
        return None
    output = git(repo_root, "diff", "--name-only", f"{old}..{new}", check=False)
    return [line for line in output.splitlines() if line]


def path_matches(path: str, rules: list[str]) -> bool:
    for rule in rules:
        if any(character in rule for character in ".*[({+?$^|"):
            if re.search(rule, path):
                return True
        elif path.startswith(rule):
            return True
    return False


def pending_migrations(
    repo_root: Path,
    profile: dict[str, Any],
    components: list[str],
    old_commits: list[str | None],
    target: str,
) -> list[str]:
    found: set[str] = set()
    for component in components:
        config = profile["components"][component]
        paths = [str(path) for path in config.get("migrationPaths", [])]
        record_path = config.get("migrationRecord")
        if not paths or not record_path:
            continue
        record = git(repo_root, "show", f"{target}:{record_path}", check=False)
        for base in old_commits:
            if not base:
                continue
            output = git(
                repo_root,
                "diff",
                "--name-only",
                "--diff-filter=A",
                f"{base}..{target}",
                "--",
                *paths,
                check=False,
            )
            for line in output.splitlines():
                if line.endswith(".sql") and Path(line).name not in record:
                    found.add(line)
    return sorted(found)


def format_time(milliseconds: Any) -> str:
    if not milliseconds:
        return ""
    return datetime.fromtimestamp(int(milliseconds) / 1000).strftime("%Y-%m-%d %H:%M")


def short(sha: Any) -> str:
    return str(sha or "")[:10] or "未知"


def make_plan(
    jenkins: Jenkins, profile: dict[str, Any], repo_root: Path, ref: str
) -> tuple[str, list[dict[str, Any]], list[str], list[str]]:
    target = remote_head(repo_root, str(profile.get("remote", "origin")), ref)
    rows: list[dict[str, Any]] = []
    for component in component_order(profile):
        version = deployed_version(jenkins, profile, component)
        files = changed_files(repo_root, version.get("commit"), target)
        rules = [str(item) for item in profile["components"][component].get("changePaths", [])]
        if version.get("commit") == target:
            need, reason = False, "已是目标版本"
        elif files is None:
            need, reason = True, "线上提交未知，保守建议发布"
        elif not rules:
            hits = files
            need, reason = bool(hits), f"{len(hits)} 个文件有变化"
        else:
            hits = [path for path in files if path_matches(path, rules)]
            need, reason = bool(hits), f"{len(hits)} 个相关文件有变化"
        rows.append({"component": component, "version": version, "need": need, "reason": reason})
    selected = [row["component"] for row in rows if row["need"]]
    old_commits = [row["version"].get("commit") for row in rows if row["need"]]
    migrations = pending_migrations(repo_root, profile, selected, old_commits, target)
    migration_components = [
        component
        for component in selected
        if profile["components"][component].get("migrationPaths")
    ]
    unknown_bases = [
        component
        for component in migration_components
        if not next(row["version"].get("commit") for row in rows if row["component"] == component)
    ]
    return target, rows, migrations, unknown_bases

def trigger(jenkins: Jenkins, profile: dict[str, Any], component: str, parameters: dict[str, str]) -> int:
    job = job_path(profile, component)
    before = jenkins.json(job + "api/json?tree=nextBuildNumber").get("nextBuildNumber", 0)
    _, headers, _ = jenkins.request("POST", job + "buildWithParameters", data=parameters, ok=(200, 201))
    queue_url = headers.get("Location")
    deadline = time.time() + int(profile.get("queueTimeoutSec", 600))
    while time.time() < deadline:
        if queue_url:
            item = jenkins.json(jenkins.url(queue_url).rstrip("/") + "/api/json")
            if item.get("cancelled"):
                raise DeployError("排队中的构建被取消")
            if item.get("executable"):
                return int(item["executable"]["number"])
            reason = item.get("why") or "等待执行器"
        else:
            builds = recent_builds(jenkins, job, 5)
            candidates = [item for item in builds if int(item.get("number", 0)) >= int(before)]
            if candidates:
                return int(candidates[-1]["number"])
            reason = "等待开始"
        print(f"  排队中：{reason}", flush=True)
        time.sleep(5)
    raise DeployError("Jenkins 排队超时")


def follow_console(
    jenkins: Jenkins,
    profile: dict[str, Any],
    component: str,
    number: int,
    log_path: Path,
    verbose: bool,
) -> str:
    job = job_path(profile, component)
    start = 0
    began = time.monotonic()
    timeout = int(profile.get("buildTimeoutSec", 3600))
    log_path.parent.mkdir(parents=True, exist_ok=True)
    interesting = re.compile(r"(?i)(stage|deploy|rollback|error|warning|success|fail|exception|阶段)")
    with log_path.open("w", encoding="utf-8") as log:
        while True:
            _, headers, content = jenkins.request(
                "GET", f"{job}{number}/logText/progressiveText?start={start}"
            )
            text = content.decode("utf-8", "replace")
            log.write(text)
            log.flush()
            for line in text.splitlines():
                if verbose or interesting.search(line):
                    print("  │ " + line[:500], flush=True)
            start = int(headers.get("X-Text-Size") or start)
            if headers.get("X-More-Data") != "true":
                break
            if time.monotonic() - began > timeout:
                raise DeployError(f"构建超过 {timeout} 秒，脚本停止等待；Jenkins 构建可能仍在运行")
            time.sleep(3)
    for _ in range(20):
        build = jenkins.json(f"{job}{number}/api/json?tree=result,building,url")
        if not build.get("building") and build.get("result"):
            return str(build["result"])
        time.sleep(3)
    raise DeployError("日志已结束但构建状态仍未更新")


def dotted_value(data: Any, path: str) -> Any:
    value = data
    for part in path.split("."):
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    return value


def health_check(profile: dict[str, Any], component: str) -> str:
    config = profile["components"][component].get("health")
    if not isinstance(config, dict) or not config:
        return "跳过（未配置）"
    url = env_or_value(config, "url", "urlEnv")
    if not url:
        return f"跳过（{config.get('urlEnv', 'health url')} 未设置）"
    timeout = int(config.get("timeoutSec", 180))
    expect_status = int(config.get("expectStatus", 200))
    expect_json = config.get("expectJson") or {}
    headers = {str(key): str(value) for key, value in (config.get("headers") or {}).items()}
    use_proxy = os.environ.get("JENKINS_USE_PROXY") == "1" or profile.get("useProxy") is True
    handlers: list[Any] = []
    if not use_proxy:
        handlers.append(urllib.request.ProxyHandler({}))
    if os.environ.get("JENKINS_INSECURE") == "1" or profile.get("insecure") is True:
        handlers.append(urllib.request.HTTPSHandler(context=ssl._create_unverified_context()))
    opener = urllib.request.build_opener(*handlers)
    deadline = time.time() + timeout
    last_error = ""
    while time.time() < deadline:
        try:
            request = urllib.request.Request(url, headers=headers)
            with opener.open(request, timeout=15) as response:
                body = response.read()
                if response.status != expect_status:
                    last_error = f"状态 {response.status}，预期 {expect_status}"
                elif expect_json:
                    payload = json.loads(body)
                    mismatch = {
                        key: (dotted_value(payload, key), value)
                        for key, value in expect_json.items()
                        if dotted_value(payload, key) != value
                    }
                    if not mismatch:
                        return f"通过（{url}）"
                    last_error = f"JSON 不匹配：{mismatch}"
                else:
                    return f"通过（{url}）"
        except Exception as error:  # noqa: BLE001 - service restarts normally fail briefly
            last_error = str(error)
        time.sleep(5)
    raise DeployError(f"健康检查 {timeout} 秒未通过：{url}；最后错误：{last_error}")


def parameter_map(profile: dict[str, Any]) -> dict[str, str]:
    configured = profile.get("parameters") or {}
    return {
        "action": str(configured.get("action", "ACTION")),
        "ref": str(configured.get("ref", "REF")),
        "deploy": str(configured.get("deploy", "DEPLOY")),
        "buildOnly": str(configured.get("buildOnly", "BUILD_ONLY")),
        "rollback": str(configured.get("rollback", "ROLLBACK")),
        "rollbackRelease": str(configured.get("rollbackRelease", "ROLLBACK_RELEASE")),
    }


def run_job(
    jenkins: Jenkins,
    profile: dict[str, Any],
    component: str,
    action: str,
    ref: str | None,
    expected_commit: str | None = None,
    rollback_release: str | None = None,
    verbose: bool = False,
) -> dict[str, Any]:
    parameters_map = parameter_map(profile)
    parameters = {parameters_map["action"]: action}
    if ref and parameters_map["ref"]:
        parameters[parameters_map["ref"]] = ref
    if rollback_release:
        parameters[parameters_map["rollbackRelease"]] = rollback_release
    print(f"\n== {component}: {action}", flush=True)
    number = trigger(jenkins, profile, component, parameters)
    console_url = jenkins.url(f"{job_path(profile, component)}{number}/console")
    print(f"  构建 #{number}：{console_url}", flush=True)
    log_dir = Path(profile.get("logDir", "~/.agent-skills/logs")).expanduser()
    log_path = log_dir / f"{datetime.now():%Y%m%d-%H%M%S}-{component}-{number}.log"
    result = follow_console(jenkins, profile, component, number, log_path, verbose)
    info = build_info(jenkins, profile, component, number)
    actual_commit = info.get("commit") or info.get("COMMIT")
    outcome: dict[str, Any] = {
        "component": component,
        "build": number,
        "result": result,
        "commit": actual_commit,
        "log": str(log_path),
        "console": console_url,
    }
    problems: list[str] = []
    if result != "SUCCESS":
        problems.append(f"构建结果为 {result}")
    if expected_commit and actual_commit and not str(actual_commit).startswith(expected_commit):
        problems.append(f"构建提交 {short(actual_commit)} 与预期 {short(expected_commit)} 不一致")
    if not problems and action != parameters_map["buildOnly"]:
        outcome["health"] = health_check(profile, component)
    else:
        outcome["health"] = "跳过（构建失败或只构建）"
    if problems:
        outcome["problems"] = problems
    return outcome


def report_outcome(outcome: dict[str, Any]) -> None:
    if outcome.get("problems"):
        print(f"\n✗ {outcome['component']} #{outcome['build']} 未通过：")
        for problem in outcome["problems"]:
            print(f"  - {problem}")
        print(f"  Console：{outcome['console']}\n  日志：{outcome['log']}")
    else:
        print(f"  ✓ #{outcome['build']} 提交 {short(outcome.get('commit'))}；健康检查：{outcome.get('health')}")

def cmd_check(jenkins: Jenkins, profile: dict[str, Any], repo_root: Path, args: argparse.Namespace) -> int:
    me = jenkins.json("me/api/json?tree=id,fullName")
    print(f"已连接 {jenkins.base}，身份：{me.get('fullName')}（{me.get('id')}）")
    for component in component_order(profile):
        version = deployed_version(jenkins, profile, component)
        builds = recent_builds(jenkins, job_path(profile, component), 3)
        state = "无记录"
        if builds:
            last = builds[0]
            state = f"#{last['number']} {last.get('result') or 'BUILDING'} {format_time(last.get('timestamp'))}"
        print(
            f"- {component}: 线上构建 #{version.get('build') or '未知'} "
            f"提交 {short(version.get('commit'))}；最近 {state}"
        )
    return 0


def cmd_plan(jenkins: Jenkins, profile: dict[str, Any], repo_root: Path, args: argparse.Namespace) -> int:
    target, rows, migrations, unknown_bases = make_plan(jenkins, profile, repo_root, args.ref)
    print(f"目标分支：{args.ref}")
    print(f"目标提交：{target} {git(repo_root, 'log', '-1', '--format=%h %s', target, check=False)}")
    for row in rows:
        mark = "发布" if row["need"] else "跳过"
        print(
            f"- {row['component']:<16} {mark}  {row['reason']}；"
            f"线上 {short(row['version'].get('commit'))}"
        )
    if migrations:
        print("新增迁移（需先在生产执行并登记）：")
        for item in migrations:
            print(f"  - {item}")
    if unknown_bases:
        print("迁移基线未知，无法自动判断；发布前必须人工检查：" + "、".join(unknown_bases))
    selected = [row["component"] for row in rows if row["need"]]
    if selected:
        migration_flag = " --migrations-done" if migrations or unknown_bases else ""
        print(
            f"建议：python {Path(__file__).as_posix()} deploy {' '.join(selected)} "
            f"--commit {target}{migration_flag} --yes"
        )
    else:
        print("没有组件需要发布。")
    return 0


def cmd_deploy(jenkins: Jenkins, profile: dict[str, Any], repo_root: Path, args: argparse.Namespace) -> int:
    components = component_order(profile, args.components)
    target = remote_head(repo_root, str(profile.get("remote", "origin")), args.ref)
    if not target.startswith(args.commit):
        raise DeployError(f"{args.ref} 最新提交是 {short(target)}，不是 --commit {args.commit}；先重新 plan")
    old_commits = [deployed_version(jenkins, profile, component).get("commit") for component in components]
    migrations = pending_migrations(repo_root, profile, components, old_commits, target)
    migration_components = [
        component
        for component in components
        if profile["components"][component].get("migrationPaths")
    ]
    unknown_bases = [
        component
        for component, commit in zip(components, old_commits)
        if component in migration_components and not commit
    ]
    if unknown_bases and not args.migrations_done:
        raise DeployError(
            "迁移基线未知：" + "、".join(unknown_bases) + "；人工检查后加 --migrations-done"
        )
    if migrations and not args.migrations_done:
        raise DeployError(
            "存在未登记执行的迁移：" + "、".join(migrations) + "；确认后加 --migrations-done"
        )
    print(f"将发布：{', '.join(components)}")
    print(f"目标提交：{target} {git(repo_root, 'log', '-1', '--format=%h %s', target, check=False)}")
    if not args.yes:
        print("（预览）确认无误后加 --yes 真正发布。")
        return 2
    for component in components:
        running = [item for item in recent_builds(jenkins, job_path(profile, component), 3) if item.get("building")]
        if running:
            raise DeployError(f"{component} 的 #{running[0]['number']} 仍在构建")
    outcomes = []
    for component in components:
        outcome = run_job(
            jenkins,
            profile,
            component,
            parameter_map(profile)["deploy"],
            args.ref,
            expected_commit=target,
            verbose=args.verbose,
        )
        outcomes.append(outcome)
        report_outcome(outcome)
        if outcome.get("problems"):
            return 1
    print("\n发布完成：")
    for outcome in outcomes:
        report_outcome(outcome)
    return 0


def cmd_build(jenkins: Jenkins, profile: dict[str, Any], repo_root: Path, args: argparse.Namespace) -> int:
    components = component_order(profile, args.components)
    target = remote_head(repo_root, str(profile.get("remote", "origin")), args.ref)
    for component in components:
        outcome = run_job(
            jenkins,
            profile,
            component,
            parameter_map(profile)["buildOnly"],
            args.ref,
            expected_commit=target,
            verbose=args.verbose,
        )
        report_outcome(outcome)
        if outcome.get("problems"):
            return 1
    return 0


def cmd_rollback(jenkins: Jenkins, profile: dict[str, Any], repo_root: Path, args: argparse.Namespace) -> int:
    config = profile["components"][args.component]
    pattern = str(config.get("releaseIdPattern", "")).replace("{component}", re.escape(args.component))
    if pattern and not re.fullmatch(pattern, args.release):
        raise DeployError(f"发布 ID 不符合组件配置的格式：{args.release}")
    print(f"将回滚 {args.component}：撤销发布 {args.release} 之后的版本")
    if not args.yes:
        print("（预览）确认无误后加 --yes 真正回滚。")
        return 2
    outcome = run_job(
        jenkins,
        profile,
        args.component,
        parameter_map(profile)["rollback"],
        None,
        rollback_release=args.release,
        verbose=args.verbose,
    )
    report_outcome(outcome)
    return 1 if outcome.get("problems") else 0


def cmd_status(jenkins: Jenkins, profile: dict[str, Any], repo_root: Path, args: argparse.Namespace) -> int:
    job = job_path(profile, args.component)
    if args.build:
        build = jenkins.json(f"{job}{args.build}/api/json?tree=number,result,building,timestamp,description")
        state = "BUILDING" if build.get("building") else build.get("result")
        print(f"#{build.get('number')} {state} {format_time(build.get('timestamp'))} {build.get('description') or ''}")
        info = build_info(jenkins, profile, args.component, args.build)
        if info:
            print("BUILD_INFO：" + json.dumps(info, ensure_ascii=False))
        console = jenkins.text(f"{job}{args.build}/consoleText", missing_ok=True) or ""
        print("\n".join(console.splitlines()[-args.tail :]))
        return 0
    for build in recent_builds(jenkins, job, 10):
        state = "BUILDING" if build.get("building") else build.get("result")
        print(f"#{build['number']:<5} {state:<10} {format_time(build.get('timestamp'))}")
    return 0


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--config", help=".agent-skills.json 路径")
    result.add_argument("--profile", help="Jenkins profile；默认读取 jenkins.defaultProfile")
    sub = result.add_subparsers(dest="command", required=True)
    sub.add_parser("check", help="检查连接、组件 Job 和线上版本")
    plan = sub.add_parser("plan", help="计算目标提交和需要发布的组件")
    plan.add_argument("--ref", help="目标分支；默认读取 profile.branch")
    deploy = sub.add_parser("deploy", help="按顺序发布组件")
    deploy.add_argument("components", nargs="+")
    deploy.add_argument("--commit", required=True, help="plan 给出的完整目标提交")
    deploy.add_argument("--ref")
    deploy.add_argument("--migrations-done", action="store_true")
    deploy.add_argument("--yes", action="store_true", help="真正执行；不加仅预览")
    deploy.add_argument("--verbose", action="store_true")
    build = sub.add_parser("build", help="只构建，不发布")
    build.add_argument("components", nargs="+")
    build.add_argument("--ref")
    build.add_argument("--verbose", action="store_true")
    rollback = sub.add_parser("rollback", help="回滚某次发布")
    rollback.add_argument("component")
    rollback.add_argument("--release", required=True)
    rollback.add_argument("--yes", action="store_true")
    rollback.add_argument("--verbose", action="store_true")
    status = sub.add_parser("status", help="查看最近构建或指定构建")
    status.add_argument("component")
    status.add_argument("--build", type=int)
    status.add_argument("--tail", type=int, default=80)
    return result


def main(argv: list[str] | None = None) -> int:
    configure_stdio()
    args = parser().parse_args(argv)
    try:
        config_path = find_config(args.config)
        profile, repo_root = load_profile(config_path, args.profile)
        if hasattr(args, "ref") and args.ref is None:
            args.ref = str(profile.get("branch", "main"))
        jenkins = Jenkins(profile)
        handlers = {
            "check": cmd_check,
            "plan": cmd_plan,
            "deploy": cmd_deploy,
            "build": cmd_build,
            "rollback": cmd_rollback,
            "status": cmd_status,
        }
        return int(handlers[args.command](jenkins, profile, repo_root, args))
    except (DeployError, OSError, ValueError, json.JSONDecodeError) as error:
        print(f"错误：{error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
