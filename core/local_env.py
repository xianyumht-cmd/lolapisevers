from __future__ import annotations

import os
import re
from pathlib import Path
from typing import MutableMapping


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_LOCAL_ENV_PATH = PROJECT_ROOT / "ops" / "app_env.local.ps1"
_ENV_LINE_RE = re.compile(
    r"^\s*\$env:(?P<key>[A-Za-z_][A-Za-z0-9_]*)\s*=\s*(?P<value>.*?)\s*$"
)


def _parse_powershell_literal(raw: str) -> str | None:
    value = raw.strip()
    if not value:
        return ""
    if len(value) >= 2 and value[0] == value[-1] == '"':
        body = value[1:-1]
        output: list[str] = []
        index = 0
        while index < len(body):
            char = body[index]
            if char == "`" and index + 1 < len(body):
                output.append(body[index + 1])
                index += 2
                continue
            output.append(char)
            index += 1
        return "".join(output)
    if len(value) >= 2 and value[0] == value[-1] == "'":
        return value[1:-1].replace("''", "'")
    if re.fullmatch(r"[^\s;|&(){}]+", value):
        return value
    return None


def read_local_powershell_env(path: Path = DEFAULT_LOCAL_ENV_PATH) -> dict[str, str]:
    try:
        text = path.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        return {}
    values: dict[str, str] = {}
    for line in text.splitlines():
        match = _ENV_LINE_RE.match(line)
        if not match:
            continue
        parsed = _parse_powershell_literal(match.group("value"))
        if parsed is None:
            continue
        values[match.group("key")] = parsed
    return values


def load_local_powershell_env(
    path: Path = DEFAULT_LOCAL_ENV_PATH,
    *,
    environ: MutableMapping[str, str] | None = None,
) -> tuple[str, ...]:
    target = os.environ if environ is None else environ
    loaded: list[str] = []
    for key, value in read_local_powershell_env(path).items():
        if str(target.get(key) or "").strip():
            continue
        target[key] = value
        loaded.append(key)
    return tuple(loaded)
