from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, urlopen

# Use the same authenticated catalog reader as the 6178 WebUI.
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lanzou_update_push_api_server.website_watch_sync import (
    CATALOG as WEBSITE_CATALOG,
    fetch_manifest,
    plan_sync,
)

SOURCE_REPO = "xianyumht-cmd/website"
SOURCE_BRANCH = "source"
ENTRY_PATH = "src/pages/nav/entry.js"
BASE_DATA_PATH = "src/assets/data/nav-data.json"
NAV_DIR = "src/pages/nav"
RAW_BASE = "https://raw.githubusercontent.com"
API_BASE = "https://api.github.com"
MONITOR_HOST_ALIASES = {"b-bu.cn"}
MIN_TARGET_COUNT = 10

_JS_STRING = r'(?:"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\')'
_MAKE_ITEM_RE = re.compile(
    rf"makeItem\(\s*({_JS_STRING})\s*,\s*({_JS_STRING})\s*,\s*({_JS_STRING})\s*,\s*({_JS_STRING})(?:\s*,\s*({_JS_STRING}))?\s*\)",
    re.S,
)


def _http_text(url: str, timeout: float = 20.0) -> str:
    request = Request(
        url,
        headers={
            "Accept": "application/json,text/plain;q=0.9,*/*;q=0.8",
            "User-Agent": "lolapisevers-website-watcher-sync/2",
        },
    )
    with urlopen(request, timeout=timeout) as response:
        raw = response.read(4 * 1024 * 1024 + 1)
    if len(raw) > 4 * 1024 * 1024:
        raise RuntimeError("website source response too large")
    return raw.decode("utf-8")


def _http_json(url: str) -> dict[str, Any]:
    data = json.loads(_http_text(url))
    if not isinstance(data, dict):
        raise RuntimeError("website source returned invalid JSON")
    return data


def _source_commit() -> str:
    branch = _http_json(f"{API_BASE}/repos/{SOURCE_REPO}/branches/{SOURCE_BRANCH}")
    sha = str(((branch.get("commit") or {}).get("sha") or "")).strip()
    if not re.fullmatch(r"[0-9a-fA-F]{40}", sha):
        raise RuntimeError("cannot resolve website source commit")
    return sha


def _raw_url(commit: str, path: str) -> str:
    return f"{RAW_BASE}/{SOURCE_REPO}/{commit}/{path}"


def _decode_js_string(token: str) -> str:
    text = str(token or "").strip()
    if len(text) < 2:
        return text
    quote = text[0]
    body = text[1:-1]

    def uni(match: re.Match[str]) -> str:
        return chr(int(match.group(1), 16))

    body = re.sub(r"\\u([0-9a-fA-F]{4})", uni, body)
    body = re.sub(r"\\x([0-9a-fA-F]{2})", uni, body)
    body = body.replace("\\n", "\n").replace("\\r", "\r").replace("\\t", "\t")
    body = body.replace("\\\\", "\\")
    if quote == '"':
        body = body.replace('\\"', '"')
    else:
        body = body.replace("\\'", "'")
    return body


def _resolve_import(base_path: str, relative_path: str) -> str:
    if not relative_path.startswith("."):
        return ""
    return str((PurePosixPath(base_path).parent / relative_path).as_posix())


def _normalize_posix(path: str) -> str:
    parts: list[str] = []
    for part in path.split("/"):
        if part in {"", "."}:
            continue
        if part == "..":
            if parts:
                parts.pop()
            continue
        parts.append(part)
    return "/".join(parts)


def _extract_imports(entry_source: str) -> list[str]:
    result: list[str] = []
    pattern = re.compile(r"import\s+(?:[^'\";]+?\s+from\s+)?['\"]([^'\"]+)['\"];?")
    for match in pattern.finditer(entry_source):
        resolved = _normalize_posix(_resolve_import(ENTRY_PATH, match.group(1)))
        if resolved.startswith(f"{NAV_DIR}/") and resolved.endswith(".js") and resolved not in result:
            result.append(resolved)
    return result


def _matching_bracket(source: str, open_index: int, open_char: str = "[", close_char: str = "]") -> int:
    depth = 0
    quote = ""
    escaped = False
    for index in range(open_index, len(source)):
        char = source[index]
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = ""
            continue
        if char in {"'", '"'}:
            quote = char
            continue
        if char == open_char:
            depth += 1
        elif char == close_char:
            depth -= 1
            if depth == 0:
                return index
    return -1


def _parse_make_items(source: str) -> list[dict[str, Any]]:
    result = []
    for match in _MAKE_ITEM_RE.finditer(source):
        title = _decode_js_string(match.group(1))
        result.append(
            {
                "title": title,
                "description": _decode_js_string(match.group(2)),
                "url": _decode_js_string(match.group(3)),
                "avatar": _decode_js_string(match.group(4)),
                "tooltip": _decode_js_string(match.group(5)) if match.group(5) else title,
            }
        )
    return result


def _parse_object_items(source: str) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for object_match in re.finditer(r"\{([^{}]*)\}", source, re.S):
        body = object_match.group(1)

        def field(name: str) -> str:
            match = re.search(rf"{re.escape(name)}\s*:\s*({_JS_STRING})", body, re.S)
            return _decode_js_string(match.group(1)) if match else ""

        title = field("title")
        url = field("url")
        if not title or not url:
            continue
        result.append(
            {
                "title": title,
                "description": field("description"),
                "url": url,
                "avatar": field("avatar") or title[:1],
                "tooltip": field("tooltip") or title,
            }
        )
    return result


def _parse_array_by_variable(source: str, variable_name: str) -> list[dict[str, Any]]:
    match = re.search(rf"(?:const|let|var)\s+{re.escape(variable_name)}\s*=\s*\[", source)
    if not match:
        return []
    open_index = source.find("[", match.start())
    close_index = _matching_bracket(source, open_index)
    if close_index < 0:
        return []
    body = source[open_index + 1 : close_index]
    items = _parse_make_items(body)
    return items or _parse_object_items(body)


def _find_section(sections: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
    for section in sections:
        if section.get("id") == name or section.get("title") == name:
            return section
    return None


def _upsert_section(
    sections: list[dict[str, Any]],
    section_id: str,
    title: str,
    icon: str,
    items: list[dict[str, Any]],
) -> None:
    section = _find_section(sections, section_id) or _find_section(sections, title)
    if section is None:
        section = {"id": section_id, "title": title, "icon": icon, "items": []}
        sections.append(section)
    section["id"] = section_id
    section["title"] = title
    section["icon"] = icon
    section["items"] = [dict(item) for item in items]


def _parse_upsert_sections(source: str, sections: list[dict[str, Any]]) -> None:
    prefix = re.compile(
        rf"upsertSection\(\s*sections\s*,\s*({_JS_STRING})\s*,\s*({_JS_STRING})\s*,\s*({_JS_STRING})\s*,\s*\[",
        re.S,
    )
    position = 0
    while True:
        match = prefix.search(source, position)
        if not match:
            break
        open_index = source.find("[", match.start())
        close_index = _matching_bracket(source, open_index)
        if close_index < 0:
            raise RuntimeError("cannot parse website upsertSection array")
        _upsert_section(
            sections,
            _decode_js_string(match.group(1)),
            _decode_js_string(match.group(2)),
            _decode_js_string(match.group(3)),
            _parse_make_items(source[open_index + 1 : close_index]),
        )
        position = close_index + 1

    hide_prefix = re.compile(
        rf"upsertHideAndSeekSection\(\s*sections\s*,\s*({_JS_STRING})\s*,\s*\[",
        re.S,
    )
    position = 0
    while True:
        match = hide_prefix.search(source, position)
        if not match:
            break
        open_index = source.find("[", match.start())
        close_index = _matching_bracket(source, open_index)
        if close_index < 0:
            raise RuntimeError("cannot parse website hide-and-seek array")
        _upsert_section(
            sections,
            "躲猫猫专区",
            _decode_js_string(match.group(1)),
            "fa fa-puzzle-piece",
            _parse_make_items(source[open_index + 1 : close_index]),
        )
        position = close_index + 1


def _apply_gs_patch(source: str, sections: list[dict[str, Any]]) -> None:
    if "gsSection" not in source:
        return
    section = _find_section(sections, "GS专区") or _find_section(sections, "GS Zone") or _find_section(sections, "足本专区")
    if section is None:
        return
    id_match = re.search(rf"gsSection\.id\s*=\s*({_JS_STRING})", source)
    title_match = re.search(rf"gsSection\.title\s*=\s*({_JS_STRING})", source)
    if id_match:
        section["id"] = _decode_js_string(id_match.group(1))
    if title_match:
        section["title"] = _decode_js_string(title_match.group(1))
    push_index = source.find("gsSection.items.push(makeItem(")
    if push_index >= 0:
        end = source.find("));", push_index)
        items = _parse_make_items(source[push_index : end + 2 if end > push_index else None])
        existing = section.setdefault("items", [])
        for item in items:
            if not any(current.get("title") == item["title"] for current in existing if isinstance(current, dict)):
                existing.append(item)


def _candidate_section_names(source: str) -> list[str]:
    result: list[str] = []
    pattern = re.compile(rf"(?:section|candidate)\.(?:id|title)\s*===\s*({_JS_STRING})")
    for match in pattern.finditer(source):
        value = _decode_js_string(match.group(1))
        if re.search(r"[\u3400-\u9fff]", value) and value not in result:
            result.append(value)
    return result


def _apply_replacement_patch(source: str, sections: list[dict[str, Any]]) -> bool:
    if "translations.zh" not in source or not re.search(r"\.items\s*=", source):
        return False
    section_names = _candidate_section_names(source)
    if not section_names:
        return False
    variable_names = re.findall(r"(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*\[", source)
    variable_names = sorted(variable_names, key=lambda name: 0 if name == "zhItems" else 1 if name == "weeklyItems" else 2)
    for name in variable_names:
        items = _parse_array_by_variable(source, name)
        if not items:
            continue
        section = next((_find_section(sections, section_name) for section_name in section_names if _find_section(sections, section_name)), None)
        if section is None:
            return False
        section["items"] = [dict(item) for item in items]
        return True
    return False


def _apply_he_patch(source: str, sections: list[dict[str, Any]]) -> None:
    if "replacementUrl" not in source:
        return
    match = re.search(rf"replacementUrl\s*=\s*({_JS_STRING})", source)
    if not match:
        return
    replacement_url = _decode_js_string(match.group(1))
    for section in sections:
        for item in section.get("items", []) if isinstance(section.get("items"), list) else []:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or "").lower()
            tooltip = str(item.get("tooltip") or "").lower()
            if title == "ezs" or tooltip == "ezs" or item.get("url") == "https://wwme.lanzouq.com/s/ezs6":
                item.update({"title": "HE", "avatar": "HE", "url": replacement_url, "tooltip": "HE"})


def _apply_confirmed_fixes(source: str, sections: list[dict[str, Any]]) -> None:
    if "markSpiritAsDisplayOnly" not in source:
        return
    for section in sections:
        for item in section.get("items", []) if isinstance(section.get("items"), list) else []:
            if isinstance(item, dict) and str(item.get("title") or "").strip().lower() == "spirit":
                item["url"] = ""
                item["displayOnly"] = True


def _monitorable_url(value: str) -> bool:
    try:
        parsed = urlsplit(str(value or "").strip())
    except ValueError:
        return False
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        return False
    host = (parsed.hostname or "").lower()
    return (
        "lanzou" in host
        or host.endswith("lanzn.com")
        or host.endswith("lanwp.com")
        or host in MONITOR_HOST_ALIASES
    )


def _password_from_description(value: str) -> str:
    match = re.search(r"(?:密码|提取码)\s*[:：]?\s*([A-Za-z0-9._-]+)", str(value or ""), re.I)
    return match.group(1) if match else ""


def normalized_url(value: str) -> str:
    parts = urlsplit(value.strip())
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/") or "/", parts.query, ""))


def _final_targets(base_data: dict[str, Any], ordered_sources: list[tuple[str, str]]) -> list[dict[str, str]]:
    zh = base_data.get("zh") if isinstance(base_data, dict) else None
    sections = json.loads(json.dumps((zh or {}).get("sections") or [], ensure_ascii=False))
    if not isinstance(sections, list) or not sections:
        raise RuntimeError("website Chinese navigation data is empty")

    for path, source in ordered_sources:
        name = PurePosixPath(path).name
        if name == "nav-patches.js":
            _apply_gs_patch(source, sections)
            _parse_upsert_sections(source, sections)
        elif name == "he-patch.js":
            _apply_he_patch(source, sections)
        elif name == "nav-confirmed-fixes.js":
            _apply_confirmed_fixes(source, sections)
        else:
            _apply_replacement_patch(source, sections)
            _parse_upsert_sections(source, sections)

    by_url: dict[str, dict[str, str]] = {}
    for section in sections:
        if not isinstance(section, dict):
            continue
        for item in section.get("items", []) if isinstance(section.get("items"), list) else []:
            if not isinstance(item, dict) or item.get("displayOnly"):
                continue
            url = str(item.get("url") or "").strip()
            if not _monitorable_url(url):
                continue
            by_url[normalized_url(url)] = {
                "title": str(item.get("title") or "").strip() or "未命名监控",
                "url": url,
                "password": _password_from_description(str(item.get("description") or "")),
                "section": str(section.get("title") or section.get("id") or "").strip(),
            }
    targets = list(by_url.values())
    if len(targets) < MIN_TARGET_COUNT:
        raise RuntimeError(f"website parse produced only {len(targets)} monitor targets; refusing sync")
    return targets


def fetch_website_targets() -> tuple[str, list[str], list[dict[str, str]]]:
    manifest = fetch_manifest()
    return manifest["sha"], [WEBSITE_CATALOG], manifest["targets"]


def stable_id(url: str, used: set[str]) -> str:
    digest = hashlib.sha1(normalized_url(url).encode("utf-8")).hexdigest()
    for size in range(10, len(digest) + 1):
        candidate = f"nav-{digest[:size]}"
        if candidate not in used:
            return candidate
    raise RuntimeError("cannot generate a unique watcher ID")


def read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8-sig") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError("config.json root must be an object")
    return data


def build_watchers(raw_watchers: Any, targets: list[dict[str, str]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    old = [item for item in raw_watchers if isinstance(item, dict)] if isinstance(raw_watchers, list) else []
    plan = plan_sync(old, {"targets": targets})
    diff = plan["diff"]
    return plan["watchers"], {
        "before": diff["before"],
        "after": diff["after"],
        "added": [item["title"] for item in diff["added"]],
        "removed": [item["title"] for item in diff["removed"]],
        "updated": [item["title"] for item in diff["updated"]],
    }


def ps_value(raw: str) -> str:
    value = raw.strip()
    if len(value) >= 2 and value[0] == value[-1] == '"':
        return value[1:-1].replace('`"', '"').replace('``', '`')
    if len(value) >= 2 and value[0] == value[-1] == "'":
        return value[1:-1].replace("''", "'")
    return value


def local_env(root: Path) -> dict[str, str]:
    values = dict(os.environ)
    line_re = re.compile(r"^\s*\$env:([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$")
    for path in (root / "ops" / "app_env.local.ps1", root / "ops" / "app_env.ps1"):
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
            match = line_re.match(line)
            if match and match.group(1) not in values:
                values[match.group(1)] = ps_value(match.group(2))
    return values


def config_path(root: Path, env: dict[str, str]) -> Path:
    configured = env.get("LANZOU_MONITOR_CONFIG", "").strip()
    path = Path(configured) if configured else root / "lanzou_update_push_api_server" / "config.json"
    return (path if path.is_absolute() else root / path).resolve()


def runtime_update(port: int, watchers: list[dict[str, Any]], token: str) -> dict[str, Any]:
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if token:
        headers["x-admin-token"] = token
    request = Request(
        f"http://127.0.0.1:{port}/admin/lanzou-config",
        data=json.dumps({"watchers": watchers}, ensure_ascii=False).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    with urlopen(request, timeout=15) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict) or payload.get("ok") is not True:
        raise RuntimeError(f"Runtime API rejected the update: {payload}")
    return payload


def direct_update(path: Path, config: dict[str, Any], watchers: list[dict[str, Any]]) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = path.with_name(f"{path.name}.bak.{stamp}")
    shutil.copy2(path, backup)
    config["watchers"] = watchers
    text = json.dumps(config, ensure_ascii=False, indent=2) + "\n"
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)
    return backup


def restart_service() -> bool:
    if os.name != "nt":
        return False
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", "Restart-Service LOLDataSystem -ErrorAction Stop"],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    return result.returncode == 0


def _print_stats(commit: str, imports: list[str], stats: dict[str, Any]) -> None:
    print(f"Source repository : {SOURCE_REPO}")
    print(f"Source branch     : {SOURCE_BRANCH}")
    print(f"Source commit     : {commit}")
    print(f"Patch files       : {len(imports)}")
    print(f"Before            : {stats['before']}")
    print(f"After             : {stats['after']}")
    print(f"Added             : {len(stats['added'])}  {', '.join(stats['added'])}")
    print(f"Removed           : {len(stats['removed'])}  {', '.join(stats['removed'])}")
    print(f"Updated           : {len(stats['updated'])}  {', '.join(stats['updated'])}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Sync Lanzou watchers from the current website-main/source final navigation data.")
    parser.add_argument("--preview", action="store_true", help="Only show the diff; do not modify config.json.")
    args = parser.parse_args(argv)

    root = Path(__file__).resolve().parent.parent
    env = local_env(root)
    path = config_path(root, env)

    print("==================================================")
    print("Lanzou watcher sync from website-main")
    print("==================================================")
    print(f"Config path       : {path}")
    print()

    if not path.exists():
        print("ERROR: Local config.json was not found.")
        return 2

    try:
        commit, imports, targets = fetch_website_targets()
        config = read_json(path)
        watchers, stats = build_watchers(config.get("watchers"), targets)
    except Exception as exc:
        print(f"ERROR: Cannot prepare watcher update: {exc}")
        return 3

    _print_stats(commit, imports, stats)
    print()
    if args.preview:
        print("Preview only: no configuration was changed.")
        return 0

    try:
        port = int(config.get("port") or env.get("LANZOU_MONITOR_PORT") or 6178)
        response = runtime_update(port, watchers, env.get("WEBUI_ADMIN_TOKEN", "").strip())
        print("Update method     : Runtime API")
        if response.get("backup_path"):
            print(f"Backup            : {response['backup_path']}")
        print("Result            : SUCCESS")
        return 0
    except (HTTPError, URLError, TimeoutError, OSError, ValueError, RuntimeError) as exc:
        print(f"Runtime API       : unavailable ({exc})")

    try:
        backup = direct_update(path, config, watchers)
    except Exception as exc:
        print(f"ERROR: Direct config update failed: {exc}")
        return 4

    print("Update method     : Direct config file")
    print(f"Backup            : {backup}")
    restarted = restart_service()
    print(f"Service restart   : {'SUCCESS' if restarted else 'NOT AVAILABLE / NOT REQUIRED'}")
    print("Result            : SUCCESS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
