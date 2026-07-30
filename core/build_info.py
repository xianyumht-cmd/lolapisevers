import json
import os
import re
from pathlib import Path
from typing import Any, Mapping, Optional


_FULL_COMMIT_SHA = re.compile(r"^[0-9a-fA-F]{40}$")
_DEFAULT_BUILD_INFO_PATH = Path(__file__).resolve().parents[1] / "build-info.json"
_UNKNOWN = "unknown"


def _read_build_file(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _first_text(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return _UNKNOWN


def _commit_sha(*values: Any) -> str:
    candidate = _first_text(*values)
    if not _FULL_COMMIT_SHA.fullmatch(candidate):
        return _UNKNOWN
    return candidate.lower()


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def load_build_info(
    *,
    environ: Optional[Mapping[str, str]] = None,
    path: Optional[Path] = None,
) -> dict[str, Any]:
    """Load public build metadata without consulting Git at request time.

    Environment variables override ``build-info.json``. A short or malformed
    commit is deliberately reported as ``unknown`` so a deployment cannot look
    traceable when only a branch name or abbreviated SHA was supplied.
    """

    env = os.environ if environ is None else environ
    configured_path = str(env.get("BUILD_INFO_PATH") or "").strip()
    build_path = path or (
        Path(configured_path) if configured_path else _DEFAULT_BUILD_INFO_PATH
    )
    file_payload = _read_build_file(build_path)

    environment_keys = {
        "BUILD_COMMIT_SHA",
        "GIT_COMMIT_SHA",
        "BUILD_TIME",
        "BUILD_TIMESTAMP",
        "BUILD_RELEASE",
        "APP_VERSION",
        "CONTRACT_VERSION",
        "CONFIG_SCHEMA_VERSION",
        "BUILD_DIRTY",
    }
    has_environment_metadata = any(
        str(env.get(key) or "").strip() for key in environment_keys
    )
    source = (
        "environment"
        if has_environment_metadata
        else ("file" if file_payload else _UNKNOWN)
    )

    commit_sha = _commit_sha(
        env.get("BUILD_COMMIT_SHA"),
        env.get("GIT_COMMIT_SHA"),
        file_payload.get("commit_sha"),
        file_payload.get("commit"),
    )
    built_at = _first_text(
        env.get("BUILD_TIME"),
        env.get("BUILD_TIMESTAMP"),
        file_payload.get("built_at"),
        file_payload.get("build_time_utc"),
        file_payload.get("build_time"),
    )
    raw_source_manifest = file_payload.get("source_manifest")
    source_manifest = (
        {
            "algorithm": str(raw_source_manifest.get("algorithm") or ""),
            "aggregate_sha256": str(
                raw_source_manifest.get("aggregate_sha256") or ""
            ).lower(),
            "file_count": int(raw_source_manifest.get("file_count") or 0),
        }
        if isinstance(raw_source_manifest, dict)
        else {}
    )
    dirty = _as_bool(
        env.get("BUILD_DIRTY")
        if str(env.get("BUILD_DIRTY") or "").strip()
        else file_payload.get("dirty")
    )
    return {
        "schema_version": "1",
        "service": "lolapisevers",
        "release": _first_text(
            env.get("BUILD_RELEASE"),
            env.get("APP_VERSION"),
            file_payload.get("release"),
            file_payload.get("version"),
        ),
        "commit_sha": commit_sha,
        "commit_complete": commit_sha != _UNKNOWN and not dirty,
        "built_at": built_at,
        "build_time_utc": built_at,
        "contract_version": _first_text(
            env.get("CONTRACT_VERSION"),
            file_payload.get("contract_version"),
        ),
        "config_schema_version": _first_text(
            env.get("CONFIG_SCHEMA_VERSION"),
            file_payload.get("config_schema_version"),
        ),
        "dirty": dirty,
        "source_manifest": source_manifest,
        "source": source,
    }
