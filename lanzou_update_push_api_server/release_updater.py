from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from core.build_info import load_build_info


REPOSITORY = "xianyumht-cmd/lolapisevers"
LATEST_RELEASE_URL = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
_PACKAGE_RE = re.compile(
    r"^LOLDataSystem-full-bug-repair-safe-deploy-([0-9a-f]{12})-py311-py314-winps51-v3\.zip$"
)
_METADATA_SUFFIX = ".metadata.json"
_FULL_SHA_RE = re.compile(r"^[0-9a-f]{40}$")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
_UPDATE_HOME = Path(
    os.getenv("LOLAPI_UPDATE_HOME")
    or (
        Path(os.getenv("PROGRAMDATA") or PROJECT_ROOT.parent)
        / "LOLDataSystem"
        / "updates"
    )
).resolve()
_TOKEN_PATH = _UPDATE_HOME / "github-release-token.txt"
_STATE_PATH = _UPDATE_HOME / "update-state.json"


class ReleaseUpdateError(RuntimeError):
    pass


def _ensure_home() -> None:
    _UPDATE_HOME.mkdir(parents=True, exist_ok=True)


def _read_token() -> str:
    env_token = str(os.getenv("LOLAPI_UPDATE_GITHUB_TOKEN") or "").strip()
    if env_token:
        return env_token
    try:
        return _TOKEN_PATH.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def save_release_token(token: str) -> dict[str, Any]:
    value = str(token or "").strip()
    _ensure_home()
    if not value:
        _TOKEN_PATH.unlink(missing_ok=True)
        return {"ok": True, "configured": bool(os.getenv("LOLAPI_UPDATE_GITHUB_TOKEN")), "source": "environment" if os.getenv("LOLAPI_UPDATE_GITHUB_TOKEN") else "none"}
    temp = _TOKEN_PATH.with_suffix(".tmp")
    temp.write_text(value, encoding="utf-8")
    try:
        os.chmod(temp, 0o600)
    except OSError:
        pass
    os.replace(temp, _TOKEN_PATH)
    return {"ok": True, "configured": True, "source": "file"}


def _headers(token: str, *, accept: str = "application/vnd.github+json") -> dict[str, str]:
    headers = {
        "Accept": accept,
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "LOLDataSystem-Release-Updater/1",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _request_json(url: str, token: str, timeout: float = 12.0) -> dict[str, Any]:
    try:
        response = requests.get(url, headers=_headers(token), timeout=(3.0, timeout))
    except requests.RequestException as exc:
        raise ReleaseUpdateError(f"GitHub Release 请求失败：{exc.__class__.__name__}") from exc
    if response.status_code == 404 and not token:
        raise ReleaseUpdateError("私有仓库需要先配置 GitHub Release 只读 Token")
    if not response.ok:
        raise ReleaseUpdateError(f"GitHub Release 请求失败：HTTP {response.status_code}")
    try:
        data = response.json()
    except ValueError as exc:
        raise ReleaseUpdateError("GitHub Release 返回了无效 JSON") from exc
    if not isinstance(data, dict):
        raise ReleaseUpdateError("GitHub Release 返回格式无效")
    return data


def _select_assets(release: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    assets = release.get("assets") if isinstance(release.get("assets"), list) else []
    zip_asset = None
    metadata_asset = None
    for asset in assets:
        if not isinstance(asset, dict):
            continue
        name = str(asset.get("name") or "")
        if _PACKAGE_RE.fullmatch(name):
            zip_asset = asset
        elif name.endswith(_METADATA_SUFFIX) and "full-bug-repair-safe-deploy" in name and "winps51-v3" in name:
            metadata_asset = asset
    if not zip_asset or not metadata_asset:
        raise ReleaseUpdateError("最新 Release 缺少 V3 ZIP 或 metadata 资产")
    expected_metadata = str(zip_asset.get("name") or "")[:-4] + _METADATA_SUFFIX
    if str(metadata_asset.get("name") or "") != expected_metadata:
        raise ReleaseUpdateError("Release ZIP 与 metadata 文件名不匹配")
    return zip_asset, metadata_asset


def _download_asset_bytes(asset: dict[str, Any], token: str, *, max_bytes: int) -> bytes:
    url = str(asset.get("url") or "").strip()
    if not url:
        raise ReleaseUpdateError("Release 资产缺少下载地址")
    try:
        response = requests.get(
            url,
            headers=_headers(token, accept="application/octet-stream"),
            timeout=(4.0, 30.0),
            allow_redirects=True,
        )
    except requests.RequestException as exc:
        raise ReleaseUpdateError(f"Release 资产下载失败：{exc.__class__.__name__}") from exc
    if not response.ok:
        raise ReleaseUpdateError(f"Release 资产下载失败：HTTP {response.status_code}")
    content = response.content
    if not content or len(content) > max_bytes:
        raise ReleaseUpdateError("Release 资产大小异常")
    return content


def _load_metadata(asset: dict[str, Any], token: str) -> dict[str, Any]:
    raw = _download_asset_bytes(asset, token, max_bytes=512_000)
    try:
        data = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ReleaseUpdateError("Release metadata 无法解析") from exc
    if not isinstance(data, dict):
        raise ReleaseUpdateError("Release metadata 根节点必须是对象")
    return data


def _validate_metadata(metadata: dict[str, Any], zip_name: str) -> str:
    if str(metadata.get("schema_version") or "") != "lolapisevers-safe-deployment-artifact.v1":
        raise ReleaseUpdateError("Release metadata schema 不受支持")
    if str(metadata.get("filename") or "") != zip_name:
        raise ReleaseUpdateError("Release metadata filename 与 ZIP 不一致")
    target = str(metadata.get("target_commit") or "").strip().lower()
    if not _FULL_SHA_RE.fullmatch(target):
        raise ReleaseUpdateError("Release metadata target_commit 无效")
    if int(metadata.get("package_revision") or 0) != 3:
        raise ReleaseUpdateError("只允许 V3 安全部署包")
    for key in ("powershell_utf8_parse_input", "baseline_aware_readiness"):
        if metadata.get(key) is not True:
            raise ReleaseUpdateError(f"Release metadata 缺少安全标志：{key}")
    expected_sha = str(metadata.get("zip_sha256") or "").strip().lower()
    if not re.fullmatch(r"[0-9a-f]{64}", expected_sha):
        raise ReleaseUpdateError("Release metadata zip_sha256 无效")
    return target


def _read_state() -> dict[str, Any]:
    try:
        data = json.loads(_STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_state(data: dict[str, Any]) -> None:
    _ensure_home()
    temp = _STATE_PATH.with_suffix(".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, _STATE_PATH)


def release_update_status() -> dict[str, Any]:
    current = load_build_info()
    current_commit = str(current.get("commit_sha") or "unknown").lower()
    token = _read_token()
    base = {
        "ok": True,
        "repository": REPOSITORY,
        "current_commit": current_commit,
        "current_release": str(current.get("release") or "unknown"),
        "token_configured": bool(token),
        "token_source": "environment" if os.getenv("LOLAPI_UPDATE_GITHUB_TOKEN") else ("file" if _TOKEN_PATH.exists() else "none"),
        "platform_supported": os.name == "nt",
        "update_state": _read_state(),
    }
    try:
        release = _request_json(LATEST_RELEASE_URL, token)
        zip_asset, metadata_asset = _select_assets(release)
        metadata = _load_metadata(metadata_asset, token)
        target = _validate_metadata(metadata, str(zip_asset.get("name") or ""))
        base.update(
            {
                "latest_release": str(release.get("tag_name") or release.get("name") or ""),
                "latest_release_name": str(release.get("name") or ""),
                "published_at": str(release.get("published_at") or ""),
                "target_commit": target,
                "package_name": str(zip_asset.get("name") or ""),
                "package_bytes": int(metadata.get("bytes") or zip_asset.get("size") or 0),
                "available": target != current_commit,
                "status": "update_available" if target != current_commit else "current",
            }
        )
    except ReleaseUpdateError as exc:
        base.update({"status": "unavailable", "available": False, "error": str(exc)})
    return base


def _download_zip(asset: dict[str, Any], token: str, destination: Path, expected_bytes: int) -> None:
    url = str(asset.get("url") or "").strip()
    if not url:
        raise ReleaseUpdateError("Release ZIP 缺少下载地址")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp = destination.with_suffix(".part")
    total = 0
    try:
        with requests.get(
            url,
            headers=_headers(token, accept="application/octet-stream"),
            timeout=(4.0, 60.0),
            allow_redirects=True,
            stream=True,
        ) as response:
            if not response.ok:
                raise ReleaseUpdateError(f"Release ZIP 下载失败：HTTP {response.status_code}")
            with temp.open("wb") as handle:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if not chunk:
                        continue
                    total += len(chunk)
                    if total > 1_500_000_000:
                        raise ReleaseUpdateError("Release ZIP 超过允许大小")
                    handle.write(chunk)
    except requests.RequestException as exc:
        temp.unlink(missing_ok=True)
        raise ReleaseUpdateError(f"Release ZIP 下载失败：{exc.__class__.__name__}") from exc
    if expected_bytes and total != expected_bytes:
        temp.unlink(missing_ok=True)
        raise ReleaseUpdateError(f"Release ZIP 大小校验失败：{total} != {expected_bytes}")
    os.replace(temp, destination)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_extract(zip_path: Path, destination: Path) -> None:
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True, exist_ok=True)
    root = destination.resolve()
    with zipfile.ZipFile(zip_path) as archive:
        for info in archive.infolist():
            candidate = (destination / info.filename).resolve()
            try:
                candidate.relative_to(root)
            except ValueError as exc:
                raise ReleaseUpdateError("Release ZIP 包含越界路径") from exc
        archive.extractall(destination)


def _find_deployer(extract_root: Path) -> Path:
    matches = list(extract_root.rglob("Deploy-FullBugRepairSafe.ps1"))
    if len(matches) != 1:
        raise ReleaseUpdateError(f"Release ZIP 部署脚本数量异常：{len(matches)}")
    return matches[0]


def _helper_script(deployer: Path, log_path: Path) -> str:
    project = str(PROJECT_ROOT)
    deploy = str(deployer)
    log = str(log_path)
    return f'''$ErrorActionPreference = "Stop"
Set-StrictMode -Version 2.0
Start-Sleep -Seconds 3
$deployPath = {json.dumps(deploy)}
$projectRoot = {json.dumps(project)}
$logPath = {json.dumps(log)}
Start-Transcript -Path $logPath -Append | Out-Null
try {{
    $command = Get-Command -LiteralPath $deployPath
    $invoke = @{{}}
    if ($command.Parameters.ContainsKey("ProjectRoot")) {{ $invoke["ProjectRoot"] = $projectRoot }}
    if ($command.Parameters.ContainsKey("ProductionRoot")) {{ $invoke["ProductionRoot"] = $projectRoot }}
    if ($command.Parameters.ContainsKey("RepositoryRoot")) {{ $invoke["RepositoryRoot"] = $projectRoot }}
    if ($command.Parameters.ContainsKey("BaseUrl")) {{ $invoke["BaseUrl"] = "http://127.0.0.1:5001" }}
    if ($command.Parameters.ContainsKey("Hero")) {{ $invoke["Hero"] = "阿狸" }}
    $known = @("ProjectRoot", "ProductionRoot", "RepositoryRoot", "BaseUrl", "Hero")
    $missing = @()
    foreach ($entry in $command.Parameters.GetEnumerator()) {{
        $attrs = @($entry.Value.Attributes | Where-Object {{ $_ -is [System.Management.Automation.ParameterAttribute] }})
        if (@($attrs | Where-Object {{ $_.Mandatory }}).Count -gt 0 -and -not $invoke.ContainsKey($entry.Key) -and $known -notcontains $entry.Key) {{
            $missing += $entry.Key
        }}
    }}
    if ($missing.Count -gt 0) {{ throw "Updater cannot resolve mandatory deploy parameters: $($missing -join ', ')" }}
    & $deployPath @invoke
    if ($LASTEXITCODE -ne 0) {{ throw "Deployment process failed with ExitCode=$LASTEXITCODE" }}
}} catch {{
    Write-Error $_
    exit 1
}} finally {{
    Stop-Transcript | Out-Null
}}
'''


def start_release_update() -> dict[str, Any]:
    if os.name != "nt":
        raise ReleaseUpdateError("一键升级只允许在 Windows 生产机执行")
    token = _read_token()
    release = _request_json(LATEST_RELEASE_URL, token)
    zip_asset, metadata_asset = _select_assets(release)
    zip_name = str(zip_asset.get("name") or "")
    metadata = _load_metadata(metadata_asset, token)
    target = _validate_metadata(metadata, zip_name)
    current = str(load_build_info().get("commit_sha") or "unknown").lower()
    if target == current:
        return {"ok": True, "scheduled": False, "message": "当前已经是最新版本", "target_commit": target}

    release_id = str(release.get("id") or int(time.time()))
    staging = _UPDATE_HOME / f"release-{release_id}-{target[:12]}"
    staging.mkdir(parents=True, exist_ok=True)
    zip_path = staging / zip_name
    _download_zip(zip_asset, token, zip_path, int(metadata.get("bytes") or 0))
    actual_sha = _sha256(zip_path)
    expected_sha = str(metadata.get("zip_sha256") or "").lower()
    if actual_sha != expected_sha:
        zip_path.unlink(missing_ok=True)
        raise ReleaseUpdateError("Release ZIP SHA-256 校验失败")

    extract_root = staging / "extracted"
    _safe_extract(zip_path, extract_root)
    deployer = _find_deployer(extract_root)
    helper = staging / "Start-VerifiedReleaseUpdate.ps1"
    log_path = staging / "update.log"
    helper.write_text(_helper_script(deployer, log_path), encoding="utf-8-sig")

    creationflags = 0
    if hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP"):
        creationflags |= subprocess.CREATE_NEW_PROCESS_GROUP
    if hasattr(subprocess, "DETACHED_PROCESS"):
        creationflags |= subprocess.DETACHED_PROCESS
    process = subprocess.Popen(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(helper),
        ],
        cwd=str(staging),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=creationflags,
        close_fds=True,
    )
    state = {
        "status": "scheduled",
        "scheduled_at": datetime.now(timezone.utc).isoformat(),
        "release": str(release.get("tag_name") or release.get("name") or ""),
        "target_commit": target,
        "package": zip_name,
        "package_sha256": actual_sha,
        "staging": str(staging),
        "log": str(log_path),
        "pid": int(process.pid),
    }
    _write_state(state)
    return {"ok": True, "scheduled": True, **state}


__all__ = [
    "ReleaseUpdateError",
    "release_update_status",
    "save_release_token",
    "start_release_update",
]
