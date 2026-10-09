"""Authenticated, fail-closed import of the website's canonical NAV catalog."""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import requests
from . import management

REPOSITORY = "xianyumht-cmd/website"
BRANCH = "source"
CATALOG = "src/assets/data/nav-catalog.js"
API = "https://api.github.com"
MIN_TARGETS = 10
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
_CALL = re.compile(r"\b([is])\s*\(")
_STRING = re.compile(r'\s*("(?:\\.|[^"\\])*")\s*(?:,|$)', re.S)
_PASSWORD = re.compile(r"(?:密码|提取码)\s*[:：]?\s*([a-zA-Z0-9._-]+)", re.I)


class WebsiteSyncError(ValueError):
    """Safe administrative error without credentials or upstream response body."""


def configured_token() -> str:
    token = os.getenv("WEBSITE_GITHUB_TOKEN", "").strip()
    if token and token != "CHANGE_ME":
        return token
    try:
        text = management.APP_ENV_PATH.read_text(encoding="utf-8-sig")
        token = management._parse_env_values(text).get("WEBSITE_GITHUB_TOKEN", "").strip()
    except OSError:
        return ""
    return token if token != "CHANGE_ME" else ""


def _get_json(path: str, token: str) -> dict[str, Any]:
    headers = {
        "accept": "application/vnd.github+json",
        "authorization": f"Bearer {token}",
        "x-github-api-version": "2022-11-28",
        "user-agent": "lolapisevers-watch-sync",
    }
    try:
        with requests.get(f"{API}{path}", headers=headers, timeout=(5, 20), stream=True) as response:
            if response.status_code in (401, 403, 404):
                raise WebsiteSyncError(
                    "无法读取 website 私有仓库：请保存具有该仓库 Contents 只读权限的 GitHub Token。"
                )
            response.raise_for_status()
            if int(response.headers.get("content-length") or 0) > MAX_RESPONSE_BYTES:
                raise WebsiteSyncError("GitHub 响应超过安全大小限制")
            chunks = bytearray()
            for chunk in response.iter_content(chunk_size=65536):
                chunks.extend(chunk)
                if len(chunks) > MAX_RESPONSE_BYTES:
                    raise WebsiteSyncError("GitHub 响应超过安全大小限制")
    except requests.RequestException as exc:
        raise WebsiteSyncError(f"读取 GitHub 失败：{type(exc).__name__}") from exc
    try:
        data = json.loads(chunks)
    except ValueError as exc:
        raise WebsiteSyncError("GitHub 返回了无效的 JSON") from exc
    if not isinstance(data, dict):
        raise WebsiteSyncError("GitHub 返回的数据类型不正确")
    return data


def _balanced(source: str, opening: int) -> str:
    """Read a call without evaluating JavaScript or treating strings as syntax."""
    if opening >= len(source) or source[opening] != "(":
        raise WebsiteSyncError("导航目录参数结构不符合预期")
    depth = 0
    quote = ""
    escaped = False
    for pos in range(opening, len(source)):
        char = source[pos]
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = ""
        elif char in ("'", '"'):
            quote = char
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return source[opening + 1:pos]
    raise WebsiteSyncError("导航目录存在未闭合的函数调用")


def _strings_prefix(arguments: str, count: int) -> tuple[list[str], str]:
    values: list[str] = []
    position = 0
    for _ in range(count):
        match = _STRING.match(arguments, position)
        if not match:
            raise WebsiteSyncError("导航条目已更换数据格式，拒绝同步")
        try:
            values.append(json.loads(match.group(1)))
        except ValueError as exc:
            raise WebsiteSyncError("导航条目包含无效字符串") from exc
        position = match.end()
    return values, arguments[position:]


def _normalize(url: str) -> str:
    parts = urlsplit(url.strip())
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/") or "/", parts.query, ""))


def _is_lanzou(url: str) -> bool:
    parts = urlsplit(url)
    if parts.scheme.lower() not in ("http", "https") or not parts.hostname:
        return False
    host = parts.hostname.lower()
    return "lanzou" in host or host.endswith(("lanzn.com", "lanwp.com")) or host == "b-bu.cn"


def parse_catalog(source: str) -> list[dict[str, str]]:
    if len(source) > MAX_RESPONSE_BYTES:
        raise WebsiteSyncError("导航目录过大")
    zh = re.search(r"\bzh\s*:\s*\{", source)
    en = re.search(r"\ben\s*:\s*\{", source)
    if not zh or not en or en.start() <= zh.end():
        raise WebsiteSyncError("无法定位中文导航目录")
    chinese = source[zh.end():en.start()]
    if "sections:" not in chinese:
        raise WebsiteSyncError("中文导航目录缺少 sections")
    result: dict[str, dict[str, str]] = {}
    section = ""
    count = 0
    for match in _CALL.finditer(chinese):
        arguments = _balanced(chinese, match.end() - 1)
        if match.group(1) == "s":
            names, _tail = _strings_prefix(arguments, 3)
            section = names[1] or names[0]
        else:
            if not section:
                raise WebsiteSyncError("导航条目没有所属专区")
            values, extra = _strings_prefix(arguments, 4)
            count += 1
            title, description, url, _avatar = values
            if re.search(r"\bdisplayOnly\s*:\s*true\b", extra) or not _is_lanzou(url):
                continue
            match_password = _PASSWORD.search(description)
            result[_normalize(url)] = {
                "title": title.strip() or "未命名监控",
                "url": url.strip(),
                "password": match_password.group(1) if match_password else "",
                "section": section,
            }
    if not count or len(result) < MIN_TARGETS:
        raise WebsiteSyncError(f"中文导航只解析到 {len(result)} 个蓝奏目标，低于安全阈值 {MIN_TARGETS}，拒绝同步")
    return list(result.values())


def fetch_manifest() -> dict[str, Any]:
    token = configured_token()
    if not token:
        raise WebsiteSyncError("尚未配置 website 私有仓库访问凭据。请在此窗口保存 GitHub 只读 Token 后重新检查。")
    branch = _get_json(f"/repos/{REPOSITORY}/branches/{BRANCH}", token)
    sha = str((branch.get("commit") or {}).get("sha") or "")
    if not re.fullmatch(r"[0-9a-f]{40}", sha, re.I):
        raise WebsiteSyncError("GitHub source 分支提交号不正确")
    content = _get_json(f"/repos/{REPOSITORY}/contents/{CATALOG}?ref={sha}", token)
    if content.get("encoding") != "base64" or not isinstance(content.get("content"), str):
        raise WebsiteSyncError("GitHub 未返回完整的导航目录文件")
    try:
        source = base64.b64decode(content["content"]).decode("utf-8")
    except (ValueError, UnicodeDecodeError) as exc:
        raise WebsiteSyncError("导航文件编码错误") from exc
    return {"sha": sha, "targets": parse_catalog(source)}


def revision(watchers: list[dict[str, Any]]) -> str:
    raw = json.dumps(watchers, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def plan_sync(old: list[dict[str, Any]], manifest: dict[str, Any]) -> dict[str, Any]:
    by_url = {
        _normalize(str(item.get("url") or "")): item
        for item in old if isinstance(item, dict) and item.get("url")
    }
    target_urls = {_normalize(item["url"]) for item in manifest["targets"]}
    used_ids = {str(item.get("id") or "") for item in old if isinstance(item, dict)}
    new: list[dict[str, Any]] = []
    added: list[dict[str, str]] = []
    updated: list[dict[str, str]] = []
    for target in manifest["targets"]:
        previous = by_url.get(_normalize(target["url"]))
        if previous:
            watcher_id = str(previous["id"])
            enabled = previous.get("enabled", True)
            max_pages = previous.get("max_pages", 20)
            # An absent upstream password must never clear an existing secret.
            password = target["password"] or str(previous.get("password") or "")
            if (str(previous.get("title") or "") != target["title"]
                    or str(previous.get("url") or "") != target["url"]
                    or str(previous.get("password") or "") != password):
                updated.append({"title": target["title"], "url": target["url"]})
        else:
            digest = hashlib.sha1(_normalize(target["url"]).encode("utf-8")).hexdigest()
            watcher_id = ""
            for length in range(10, 41):
                candidate = f"nav-{digest[:length]}"
                if candidate not in used_ids:
                    watcher_id = candidate
                    break
            if not watcher_id:
                raise WebsiteSyncError("无法生成唯一监控 ID")
            enabled, max_pages, password = True, 20, target["password"]
            added.append({"title": target["title"], "url": target["url"]})
        used_ids.add(watcher_id)
        new.append({
            "id": watcher_id, "title": target["title"], "url": target["url"],
            "password": password, "enabled": enabled, "max_pages": max_pages,
        })
    removed = [
        {"title": str(item.get("title") or item.get("id") or ""), "url": str(item.get("url") or "")}
        for item in old if isinstance(item, dict) and item.get("url")
        and _normalize(str(item["url"])) not in target_urls
    ]
    return {
        "watchers": new,
        "diff": {"before": len(old), "after": len(new), "added": added, "updated": updated, "removed": removed},
        "revision": revision(old),
    }
