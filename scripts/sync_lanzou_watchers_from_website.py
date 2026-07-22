from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, urlopen

SOURCE_REPO = "xianyumht-cmd/website"
SOURCE_BRANCH = "source"
SOURCE_COMMIT = "8ce0d301f77e9f9183f129dc57c5738ba4da3881"

# title, url, password. Generated from the final Chinese nav data after nav-patches.js.
NAV_WATCHERS = [
    ("4件套+DX修复+工具盒子", "https://avgorange.lanzoub.com/b0dppnjpg", ""),
    ("影子卫士", "https://pan-su.lanzoum.com/ih8H00xoy2ze", ""),
    ("EZ", "https://wwme.lanzouq.com/b00oco2z0j", "123"),
    ("ezpro", "https://wwme.lanzouq.com/s/ezpro", "123"),
    ("ezs", "https://wwme.lanzouq.com/s/ezs6", "123"),
    ("OS", "https://wwayq.lanzouq.com/s/outis", ""),
    ("Space", "https://wwayq.lanzouq.com/b00odtjzsf", ""),
    ("蓝鲸", "https://wwbpx.lanzoum.com/b00mqcafbi", ""),
    ("FY", "https://wwbls.lanzouq.com/b0rb4uivc", ""),
    ("如意", "https://wwbpx.lanzoum.com/b00mqcagdg", ""),
    ("Strat", "https://www.lanwp.com/b019vxf7mf", ""),
    ("DJ", "https://wwaym.lanzoub.com/s/DJYYDS", "123"),
    ("FE", "https://wwarw.lanzn.com/b00l2sy5re", "bp03"),
    ("鲨鱼", "https://wwbuq.lanzouu.com/b00jezzfej", ""),
    ("传奇", "https://wwamk.lanzouu.com/b01d70ikvc", "efbk"),
    ("yun", "https://wwus.lanzouu.com/s/yunnb", "yun"),
    ("GUF", "https://wwme.lanzoui.com/b00od4rd1e", ""),
    ("LTY", "https://wwauv.lanzout.com/b00yb1z1od", "f4sv"),
    ("LO", "https://wwash.lanzouw.com/b019vvm2ve", "123"),
    ("万艾可", "https://wwbku.lanzoub.com/b0pndjqmj", "123"),
    ("黎明", "https://wwbpx.lanzoum.com/b00mqeda6d", ""),
    ("时光", "https://wwarw.lanzn.com/b00l2sy5gd", "btqo"),
    ("海豹", "https://wwbuq.lanzouu.com/b00jezzfoj", ""),
    ("FJ", "https://wwaym.lanzoub.com/s/QiHang", "123"),
    ("樱桃", "https://wwbgz.lanzouu.com/b019vx8h5g", "123"),
    ("灵影", "https://wwus.lanzouu.com/b0zkvz7la", "0ying"),
    ("TAB", "https://wwus.lanzouu.com/s/TAB1", "tab11"),
    ("星辰", "https://wwbgz.lanzouu.com/b019w076jg", "123"),
    ("无心", "https://wud.lanzoul.com/b00hq90ire", "hhwn"),
    ("鸡你太美", "https://wwaoj.lanzoul.com/s/ydjntm4", "888"),
    ("无名", "https://wwzd.lanzouu.com/b016kd079i", ""),
    ("熊猫特权", "https://wwv.lanzouh.com/b00mone1bc", ""),
    ("键盘侠", "https://mybb.lanzn.com/illyB3p72wgb", ""),
    ("GTA", "https://wud.lanzoul.com/b00hrkm3pg", "666"),
    ("KT", "https://wwazv.lanzout.com/b0he1s4te", "6666"),
    ("战神", "https://yituoshi.lanzouw.com/b023nn2x3g", ""),
    ("绝影", "https://wwas.lanzouj.com/b00xq0uaf", ""),
    ("轮回", "https://wwas.lanzouj.com/b00xziv7a", ""),
    ("RK大瓦国", "https://wwaly.lanzouq.com/b011m5h4gd", "0000"),
    ("谪仙红名生化", "https://daguo6.lanzouw.com/b0mbewswf", "6666"),
    ("天命", "https://daguo6.lanzouw.com/b0mbewtqf", "6666"),
    ("北帝", "https://daguo6.lanzouw.com/b0mbewu8d", "6666"),
    ("JZ", "https://daguo6.lanzouw.com/b0mbewvlc", "6666"),
    ("BX", "https://daguo6.lanzouw.com/b0mbewvta", "6666"),
    ("BB", "https://daguo6.lanzouw.com/b0mbewuwh", "6666"),
    ("凤溪", "https://daguo6.lanzouw.com/b0mcn84vg", "6666"),
    ("MC", "https://wwbjv.lanzout.com/b00yb6nuwd", "123"),
    ("涂鸦躲猫猫", "https://wwbhv.lanzoum.com/b01d713yof", "6666"),
    ("达芬奇", "https://wwbhv.lanzoum.com/b01d71e9kh", "6666"),
    ("奥特曼租号", "https://wwyq.lanzoui.com/b0zjywmud", "6666"),
    ("方寸租号", "https://wwi.lanzoue.com/b0a6jcuyh", ""),
    ("东鹏", "https://wwwj.lanzouw.com/b00ro37qdc", "6666"),
    ("小天", "https://jbh.lanzouu.com/s/WeGame", ""),
]


def normalized_url(value: str) -> str:
    parts = urlsplit(value.strip())
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/") or "/", parts.query, ""))


def stable_id(url: str, used: set[str]) -> str:
    digest = hashlib.sha1(normalized_url(url).encode("utf-8")).hexdigest()
    for size in range(10, len(digest) + 1):
        candidate = f"nav-{digest[:size]}"
        if candidate not in used:
            return candidate
    raise RuntimeError("Cannot generate a unique watcher ID")


def read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8-sig") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError("config.json root must be an object")
    return data


def build_watchers(raw_watchers: Any) -> tuple[list[dict[str, Any]], dict[str, int]]:
    old = [item for item in raw_watchers if isinstance(item, dict)] if isinstance(raw_watchers, list) else []
    by_url = {
        normalized_url(str(item.get("url") or "")): item
        for item in old
        if str(item.get("url") or "").strip()
    }
    used = {str(item.get("id") or "").strip() for item in old if str(item.get("id") or "").strip()}
    targets = {normalized_url(url) for _title, url, _password in NAV_WATCHERS}
    result: list[dict[str, Any]] = []
    added = updated = 0

    for title, url, password in NAV_WATCHERS:
        previous = by_url.get(normalized_url(url))
        if previous is None:
            watcher_id = stable_id(url, used)
            used.add(watcher_id)
            enabled, max_pages = True, 20
            added += 1
        else:
            watcher_id = str(previous.get("id") or "").strip() or stable_id(url, used)
            used.add(watcher_id)
            enabled = previous.get("enabled") is not False
            try:
                max_pages = max(1, min(100, int(previous.get("max_pages") or 20)))
            except (TypeError, ValueError):
                max_pages = 20
            if any(
                str(previous.get(key) or "") != expected
                for key, expected in (("title", title), ("url", url), ("password", password))
            ):
                updated += 1
        result.append(
            {
                "id": watcher_id,
                "title": title,
                "url": url,
                "password": password,
                "enabled": enabled,
                "max_pages": max_pages,
            }
        )

    removed = sum(
        normalized_url(str(item.get("url") or "")) not in targets
        for item in old
        if str(item.get("url") or "").strip()
    )
    return result, {"before": len(old), "after": len(result), "added": added, "removed": removed, "updated": updated}


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


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    env = local_env(root)
    path = config_path(root, env)

    print("==================================================")
    print("Lanzou watcher sync")
    print("==================================================")
    print(f"Source repository: {SOURCE_REPO}")
    print(f"Source branch    : {SOURCE_BRANCH}")
    print(f"Source commit    : {SOURCE_COMMIT}")
    print(f"Target count     : {len(NAV_WATCHERS)}")
    print(f"Config path      : {path}")
    print()

    if not path.exists():
        print("ERROR: Local config.json was not found.")
        print("No file was created because existing notification settings must be preserved.")
        return 2

    try:
        config = read_json(path)
        watchers, stats = build_watchers(config.get("watchers"))
    except Exception as exc:
        print(f"ERROR: Cannot prepare watcher update: {exc}")
        return 3

    for label in ("before", "after", "added", "removed", "updated"):
        print(f"{label.capitalize():17}: {stats[label]}")
    print()

    try:
        port = int(config.get("port") or env.get("LANZOU_MONITOR_PORT") or 6178)
        response = runtime_update(port, watchers, env.get("WEBUI_ADMIN_TOKEN", "").strip())
        print("Update method    : Runtime API")
        if response.get("backup_path"):
            print(f"Backup           : {response['backup_path']}")
        print(f"Runtime count    : {len(response.get('config', {}).get('watchers', []))}")
        print("Result           : SUCCESS")
        return 0
    except (HTTPError, URLError, TimeoutError, OSError, ValueError, RuntimeError) as exc:
        print(f"Runtime API      : unavailable ({exc})")

    try:
        backup = direct_update(path, config, watchers)
    except Exception as exc:
        print(f"ERROR: Direct config update failed: {exc}")
        return 4

    print("Update method    : Direct config file")
    print(f"Backup           : {backup}")
    if restart_service():
        print("Service restart  : SUCCESS")
        print("Result           : SUCCESS")
    else:
        print("Service restart  : NOT COMPLETED")
        print("Config is updated, but the service must be restarted manually.")
        print("Run as Administrator: Restart-Service LOLDataSystem")
        print("Result           : CONFIG UPDATED")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("Cancelled.")
        raise SystemExit(130)
