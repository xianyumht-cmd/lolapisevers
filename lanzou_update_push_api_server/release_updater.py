from __future__ import annotations

import concurrent.futures
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
_REQUIRED_MANIFEST_FLAGS = (
    "candidate_tests_before_stop",
    "automatic_rollback",
    "offline_dependencies",
    "powershell_utf8_parse_input",
    "baseline_aware_readiness",
)
_DEFAULT_RELEASE_MIRRORS = (
    ("gh-proxy.com", "https://gh-proxy.com/"),
    ("ghproxy.net", "https://ghproxy.net/"),
    ("ghfast.top", "https://ghfast.top/"),
    ("gh.ddlc.top", "https://gh.ddlc.top/"),
)
_ACTIVE_UPDATE_STATUSES = {"running", "downloading", "verifying", "extracting", "scheduling"}

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


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


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
        env_configured = bool(os.getenv("LOLAPI_UPDATE_GITHUB_TOKEN"))
        return {
            "ok": True,
            "configured": env_configured,
            "source": "environment" if env_configured else "none",
        }
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
        "User-Agent": "LOLDataSystem-Release-Updater/2",
        "Accept-Encoding": "identity",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _public_headers() -> dict[str, str]:
    return {
        "Accept": "application/octet-stream",
        "User-Agent": "LOLDataSystem-Release-Updater/2",
        "Accept-Encoding": "identity",
    }


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
    zip_assets = []
    metadata_assets = []
    for asset in assets:
        if not isinstance(asset, dict):
            continue
        name = str(asset.get("name") or "")
        if _PACKAGE_RE.fullmatch(name):
            zip_assets.append(asset)
        elif name.endswith(_METADATA_SUFFIX) and "full-bug-repair-safe-deploy" in name and "winps51-v3" in name:
            metadata_assets.append(asset)
    if len(zip_assets) != 1 or len(metadata_assets) != 1:
        raise ReleaseUpdateError(
            f"最新 Release 的 V3 资产数量异常：zip={len(zip_assets)} metadata={len(metadata_assets)}"
        )
    zip_asset = zip_assets[0]
    metadata_asset = metadata_assets[0]
    expected_metadata = str(zip_asset.get("name") or "")[:-4] + _METADATA_SUFFIX
    if str(metadata_asset.get("name") or "") != expected_metadata:
        raise ReleaseUpdateError("Release ZIP 与 metadata 文件名不匹配")
    return zip_asset, metadata_asset


def _download_asset_bytes(asset: dict[str, Any], token: str, *, max_bytes: int) -> bytes:
    # Metadata remains on the authenticated GitHub API path. Mirrors are only
    # allowed for the ZIP after trusted metadata has supplied its SHA-256.
    url = str(asset.get("url") or "").strip()
    if not url:
        raise ReleaseUpdateError("Release 资产缺少下载地址")
    try:
        response = requests.get(
            url,
            headers=_headers(token, accept="application/octet-stream"),
            timeout=(3.0, 12.0),
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
    match = _PACKAGE_RE.fullmatch(zip_name)
    if not match:
        raise ReleaseUpdateError("Release ZIP 文件名不受支持")
    target = str(metadata.get("target_commit") or "").strip().lower()
    if not _FULL_SHA_RE.fullmatch(target):
        raise ReleaseUpdateError("Release metadata target_commit 无效")
    if match.group(1) != target[:12]:
        raise ReleaseUpdateError("Release ZIP 文件名提交前缀与 metadata 不一致")
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


def _update_state(*, status: str, phase: str, message: str = "", **fields: Any) -> dict[str, Any]:
    state = _read_state()
    state.update(
        {
            "status": status,
            "phase": phase,
            "message": message,
            "updated_at": _utc_now(),
            **fields,
        }
    )
    _write_state(state)
    return state


def _mirror_prefixes() -> list[tuple[str, str]]:
    raw = str(os.getenv("LOLAPI_RELEASE_MIRRORS") or "").strip()
    values: list[tuple[str, str]] = []
    if raw:
        for index, item in enumerate(re.split(r"[;,\n]+", raw), start=1):
            prefix = item.strip()
            if not prefix:
                continue
            if not prefix.startswith("https://"):
                continue
            if "@" in prefix.split("://", 1)[1].split("/", 1)[0]:
                continue
            values.append((f"custom-{index}", prefix.rstrip("/") + "/"))
    values.extend(_DEFAULT_RELEASE_MIRRORS)
    deduped: list[tuple[str, str]] = []
    seen = set()
    for label, prefix in values:
        if prefix in seen:
            continue
        seen.add(prefix)
        deduped.append((label, prefix))
    return deduped


def _browser_download_url(asset: dict[str, Any]) -> str:
    url = str(asset.get("browser_download_url") or "").strip()
    expected_prefix = f"https://github.com/{REPOSITORY}/releases/download/"
    if url.startswith(expected_prefix):
        return url
    return ""


def _download_candidates(asset: dict[str, Any], token: str) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    browser_url = _browser_download_url(asset)
    if browser_url:
        for label, prefix in _mirror_prefixes():
            candidates.append(
                {
                    "label": label,
                    "url": prefix + browser_url,
                    "headers": _public_headers(),
                    "mirror": True,
                }
            )
        candidates.append(
            {
                "label": "github-direct",
                "url": browser_url,
                "headers": _public_headers(),
                "mirror": False,
            }
        )
    api_url = str(asset.get("url") or "").strip()
    if api_url:
        candidates.append(
            {
                "label": "github-api",
                "url": api_url,
                "headers": _headers(token, accept="application/octet-stream"),
                "mirror": False,
            }
        )
    deduped = []
    seen = set()
    for candidate in candidates:
        url = candidate["url"]
        if url in seen:
            continue
        seen.add(url)
        deduped.append(candidate)
    if not deduped:
        raise ReleaseUpdateError("Release ZIP 缺少可用下载地址")
    return deduped


def _probe_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    started = time.perf_counter()
    headers = dict(candidate["headers"])
    headers["Range"] = "bytes=0-65535"
    try:
        with requests.get(
            candidate["url"],
            headers=headers,
            timeout=(2.5, 4.0),
            allow_redirects=True,
            stream=True,
        ) as response:
            if response.status_code not in {200, 206}:
                return {
                    "label": candidate["label"],
                    "ok": False,
                    "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
                    "error": f"HTTP {response.status_code}",
                }
            prefix = b""
            for chunk in response.iter_content(chunk_size=64 * 1024):
                if chunk:
                    prefix = bytes(chunk[:8])
                    break
            if not prefix.startswith(b"PK"):
                return {
                    "label": candidate["label"],
                    "ok": False,
                    "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
                    "error": "not_zip",
                }
    except requests.RequestException as exc:
        return {
            "label": candidate["label"],
            "ok": False,
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
            "error": exc.__class__.__name__,
        }
    return {
        "label": candidate["label"],
        "ok": True,
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
        "error": "",
    }


def _rank_download_candidates(
    candidates: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if len(candidates) == 1:
        probe = _probe_candidate(candidates[0])
        return candidates, [probe]

    results: list[dict[str, Any]] = []
    with concurrent.futures.ThreadPoolExecutor(
        max_workers=min(6, len(candidates)),
        thread_name_prefix="release-mirror-probe",
    ) as pool:
        futures = [pool.submit(_probe_candidate, candidate) for candidate in candidates]
        for future in concurrent.futures.as_completed(futures):
            try:
                results.append(future.result())
            except Exception as exc:
                results.append(
                    {
                        "label": "unknown",
                        "ok": False,
                        "elapsed_ms": 999999.0,
                        "error": exc.__class__.__name__,
                    }
                )

    result_by_label = {item.get("label"): item for item in results}
    index_by_label = {candidate["label"]: idx for idx, candidate in enumerate(candidates)}
    ranked = sorted(
        candidates,
        key=lambda candidate: (
            0 if result_by_label.get(candidate["label"], {}).get("ok") else 1,
            float(result_by_label.get(candidate["label"], {}).get("elapsed_ms") or 999999.0),
            index_by_label.get(candidate["label"], 999),
        ),
    )
    return ranked, results


def _download_from_candidate(
    candidate: dict[str, Any],
    destination: Path,
    expected_bytes: int,
) -> int:
    temp = destination.with_suffix(destination.suffix + ".part")
    offset = temp.stat().st_size if temp.exists() else 0
    if expected_bytes and offset > expected_bytes:
        temp.unlink(missing_ok=True)
        offset = 0

    headers = dict(candidate["headers"])
    if offset:
        headers["Range"] = f"bytes={offset}-"

    started = time.perf_counter()
    last_state_at = 0.0
    try:
        with requests.get(
            candidate["url"],
            headers=headers,
            timeout=(3.0, 12.0),
            allow_redirects=True,
            stream=True,
        ) as response:
            if response.status_code not in {200, 206}:
                raise ReleaseUpdateError(
                    f"{candidate['label']} 下载失败：HTTP {response.status_code}"
                )
            append = bool(offset and response.status_code == 206)
            if offset and not append:
                offset = 0
            mode = "ab" if append else "wb"
            total = offset
            with temp.open(mode) as handle:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if not chunk:
                        continue
                    total += len(chunk)
                    if total > 1_500_000_000:
                        raise ReleaseUpdateError("Release ZIP 超过允许大小")
                    if expected_bytes and total > expected_bytes:
                        raise ReleaseUpdateError(
                            f"{candidate['label']} 返回大小超过 metadata"
                        )
                    handle.write(chunk)
                    now = time.monotonic()
                    if now - last_state_at >= 0.8:
                        elapsed = max(time.perf_counter() - started, 0.001)
                        transferred = max(total - offset, 0)
                        percent = (
                            round(total * 100.0 / expected_bytes, 1)
                            if expected_bytes
                            else 0.0
                        )
                        _update_state(
                            status="downloading",
                            phase="download",
                            message=f"正在从 {candidate['label']} 下载 V3 包",
                            download_source=candidate["label"],
                            downloaded_bytes=total,
                            package_bytes=expected_bytes,
                            progress_percent=percent,
                            speed_mbps=round(transferred / elapsed / 1024 / 1024, 2),
                            resumed_bytes=offset,
                        )
                        last_state_at = now
    except requests.RequestException as exc:
        raise ReleaseUpdateError(
            f"{candidate['label']} 下载失败：{exc.__class__.__name__}"
        ) from exc

    total = temp.stat().st_size if temp.exists() else 0
    if expected_bytes and total != expected_bytes:
        raise ReleaseUpdateError(
            f"{candidate['label']} 大小校验失败：{total} != {expected_bytes}"
        )
    os.replace(temp, destination)
    return total


def _download_zip(
    asset: dict[str, Any],
    token: str,
    destination: Path,
    expected_bytes: int,
) -> tuple[str, list[dict[str, Any]]]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    candidates = _download_candidates(asset, token)
    _update_state(
        status="running",
        phase="mirror_probe",
        message="正在并行测速 GitHub 与镜像源",
        mirror_candidates=[candidate["label"] for candidate in candidates],
        package_bytes=expected_bytes,
    )
    ranked, probes = _rank_download_candidates(candidates)
    _update_state(
        status="running",
        phase="mirror_selected",
        message=f"测速完成，优先使用 {ranked[0]['label']}",
        mirror_probes=probes,
        download_source=ranked[0]["label"],
    )

    errors: list[dict[str, Any]] = []
    for candidate in ranked:
        try:
            _update_state(
                status="downloading",
                phase="download",
                message=f"正在从 {candidate['label']} 下载 V3 包",
                download_source=candidate["label"],
                download_errors=errors,
            )
            _download_from_candidate(candidate, destination, expected_bytes)
            return candidate["label"], errors
        except ReleaseUpdateError as exc:
            errors.append({"source": candidate["label"], "error": str(exc)[:240]})
            _update_state(
                status="running",
                phase="source_fallback",
                message=f"{candidate['label']} 失败，自动切换下一下载源",
                download_source=candidate["label"],
                download_errors=errors,
            )

    raise ReleaseUpdateError(
        "所有 Release 下载源均失败：" + "；".join(
            f"{item['source']}={item['error']}" for item in errors[-4:]
        )
    )


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


def _validate_embedded_manifest(extract_root: Path, target_commit: str) -> Path:
    manifests = list(extract_root.rglob("manifest.json"))
    if len(manifests) != 1:
        raise ReleaseUpdateError(f"Release ZIP manifest 数量异常：{len(manifests)}")
    manifest_path = manifests[0]
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ReleaseUpdateError("Release ZIP manifest 无法解析") from exc
    if not isinstance(manifest, dict):
        raise ReleaseUpdateError("Release ZIP manifest 根节点必须是对象")
    if str(manifest.get("target_commit") or "").lower() != target_commit:
        raise ReleaseUpdateError("Release ZIP manifest 目标提交不一致")
    if int(manifest.get("package_revision") or 0) != 3:
        raise ReleaseUpdateError("Release ZIP manifest 不是 V3")
    deployment = manifest.get("deployment") if isinstance(manifest.get("deployment"), dict) else {}
    for key in _REQUIRED_MANIFEST_FLAGS:
        if deployment.get(key) is not True:
            raise ReleaseUpdateError(f"Release ZIP manifest 缺少安全标志：{key}")
    return manifest_path


def _find_deployer(extract_root: Path, manifest_path: Path) -> Path:
    preferred = manifest_path.parent / "Deploy-FullBugRepairSafe.ps1"
    if preferred.is_file():
        return preferred
    matches = list(extract_root.rglob("Deploy-FullBugRepairSafe.ps1"))
    if len(matches) != 1:
        raise ReleaseUpdateError(f"Release ZIP 部署脚本数量异常：{len(matches)}")
    return matches[0]


def _ps_quote(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _helper_script(deployer: Path, log_path: Path) -> str:
    project = _ps_quote(str(PROJECT_ROOT))
    deploy = _ps_quote(str(deployer))
    log = _ps_quote(str(log_path))
    return f'''$ErrorActionPreference = "Stop"
Set-StrictMode -Version 2.0
Start-Sleep -Seconds 3
$deployPath = {deploy}
$projectRoot = {project}
$logPath = {log}
Start-Transcript -Path $logPath -Append | Out-Null
try {{
    $command = Get-Command -Name $deployPath -ErrorAction Stop
    $invoke = @{{}}
    if ($command.Parameters.ContainsKey("ProjectRoot")) {{ $invoke["ProjectRoot"] = $projectRoot }}
    if ($command.Parameters.ContainsKey("ProductionRoot")) {{ $invoke["ProductionRoot"] = $projectRoot }}
    if ($command.Parameters.ContainsKey("RepositoryRoot")) {{ $invoke["RepositoryRoot"] = $projectRoot }}
    if ($command.Parameters.ContainsKey("BaseUrl")) {{ $invoke["BaseUrl"] = "http://127.0.0.1:5001" }}
    if ($command.Parameters.ContainsKey("Hero")) {{ $invoke["Hero"] = "阿狸" }}
    $missing = @()
    foreach ($entry in $command.Parameters.GetEnumerator()) {{
        $attrs = @($entry.Value.Attributes | Where-Object {{ $_ -is [System.Management.Automation.ParameterAttribute] }})
        if (@($attrs | Where-Object {{ $_.Mandatory }}).Count -gt 0 -and -not $invoke.ContainsKey($entry.Key)) {{
            $missing += $entry.Key
        }}
    }}
    if ($missing.Count -gt 0) {{
        throw "Updater cannot resolve mandatory deploy parameters: $($missing -join ', ')"
    }}
    & $deployPath @invoke
    if ($LASTEXITCODE -ne 0) {{
        throw "Deployment process failed with ExitCode=$LASTEXITCODE"
    }}
}} catch {{
    Write-Error $_
    exit 1
}} finally {{
    Stop-Transcript | Out-Null
}}
'''


def release_update_status() -> dict[str, Any]:
    current = load_build_info()
    current_commit = str(current.get("commit_sha") or "unknown").lower()
    token = _read_token()
    state = _read_state()
    base = {
        "ok": True,
        "repository": REPOSITORY,
        "current_commit": current_commit,
        "current_release": str(current.get("release") or "unknown"),
        "token_configured": bool(token),
        "token_source": "environment"
        if os.getenv("LOLAPI_UPDATE_GITHUB_TOKEN")
        else ("file" if _TOKEN_PATH.exists() else "none"),
        "platform_supported": os.name == "nt",
        "update_state": state,
        "mirrors": [label for label, _prefix in _mirror_prefixes()],
    }

    # Progress polling during a running update stays local instead of repeatedly
    # querying GitHub and downloading metadata again.
    if str(state.get("status") or "").lower() in _ACTIVE_UPDATE_STATUSES:
        target = str(state.get("target_commit") or "")
        base.update(
            {
                "latest_release": str(state.get("release") or ""),
                "latest_release_name": str(state.get("release") or ""),
                "published_at": "",
                "target_commit": target,
                "package_name": str(state.get("package") or ""),
                "package_bytes": int(state.get("package_bytes") or 0),
                "available": True,
                "status": "updating",
            }
        )
        return base

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


def start_release_update() -> dict[str, Any]:
    if os.name != "nt":
        raise ReleaseUpdateError("一键升级只允许在 Windows 生产机执行")

    try:
        _update_state(
            status="running",
            phase="release_check",
            message="正在检查最新 Release",
            started_at=_utc_now(),
            downloaded_bytes=0,
            progress_percent=0,
            download_errors=[],
        )
        token = _read_token()
        release = _request_json(LATEST_RELEASE_URL, token)
        zip_asset, metadata_asset = _select_assets(release)
        zip_name = str(zip_asset.get("name") or "")
        release_name = str(release.get("tag_name") or release.get("name") or "")
        _update_state(
            status="running",
            phase="metadata",
            message="正在读取并验证官方 metadata",
            release=release_name,
            package=zip_name,
        )
        metadata = _load_metadata(metadata_asset, token)
        target = _validate_metadata(metadata, zip_name)
        expected_bytes = int(metadata.get("bytes") or zip_asset.get("size") or 0)
        expected_sha = str(metadata.get("zip_sha256") or "").lower()
        _update_state(
            status="running",
            phase="metadata_verified",
            message="metadata 已校验，准备测速下载源",
            release=release_name,
            target_commit=target,
            package=zip_name,
            package_bytes=expected_bytes,
        )

        current = str(load_build_info().get("commit_sha") or "unknown").lower()
        if target == current:
            state = _update_state(
                status="current",
                phase="complete",
                message="当前已经是最新版本",
                release=release_name,
                target_commit=target,
                package=zip_name,
            )
            return {
                "ok": True,
                "scheduled": False,
                "message": "当前已经是最新版本",
                "target_commit": target,
                **state,
            }

        release_id = str(release.get("id") or int(time.time()))
        staging = _UPDATE_HOME / f"release-{release_id}-{target[:12]}"
        staging.mkdir(parents=True, exist_ok=True)
        zip_path = staging / zip_name

        download_source = "local-cache"
        download_errors: list[dict[str, Any]] = []
        cached_ok = False
        if zip_path.is_file():
            try:
                cached_ok = (
                    (not expected_bytes or zip_path.stat().st_size == expected_bytes)
                    and _sha256(zip_path) == expected_sha
                )
            except OSError:
                cached_ok = False
        if cached_ok:
            _update_state(
                status="verifying",
                phase="local_cache",
                message="命中已校验的本地 V3 包，跳过重新下载",
                download_source=download_source,
                downloaded_bytes=zip_path.stat().st_size,
                progress_percent=100.0,
            )
        else:
            zip_path.unlink(missing_ok=True)
            download_source, download_errors = _download_zip(
                zip_asset,
                token,
                zip_path,
                expected_bytes,
            )

        _update_state(
            status="verifying",
            phase="sha256",
            message="下载完成，正在校验 SHA-256",
            download_source=download_source,
            downloaded_bytes=zip_path.stat().st_size,
            package_bytes=expected_bytes,
            progress_percent=100.0,
            download_errors=download_errors,
        )
        actual_sha = _sha256(zip_path)
        if actual_sha != expected_sha:
            zip_path.unlink(missing_ok=True)
            raise ReleaseUpdateError("Release ZIP SHA-256 校验失败")

        extract_root = staging / "extracted"
        _update_state(
            status="extracting",
            phase="extract",
            message="SHA-256 已通过，正在安全解压并检查 manifest",
            package_sha256=actual_sha,
        )
        _safe_extract(zip_path, extract_root)
        manifest_path = _validate_embedded_manifest(extract_root, target)
        deployer = _find_deployer(extract_root, manifest_path)
        helper = staging / "Start-VerifiedReleaseUpdate.ps1"
        log_path = staging / "update.log"
        helper.write_text(_helper_script(deployer, log_path), encoding="utf-8-sig")

        _update_state(
            status="scheduling",
            phase="schedule",
            message="校验全部通过，正在启动独立部署进程",
            staging=str(staging),
            log=str(log_path),
        )
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
            "phase": "scheduled",
            "message": "独立部署进程已启动",
            "scheduled_at": _utc_now(),
            "updated_at": _utc_now(),
            "release": release_name,
            "target_commit": target,
            "package": zip_name,
            "package_bytes": expected_bytes,
            "package_sha256": actual_sha,
            "download_source": download_source,
            "download_errors": download_errors,
            "downloaded_bytes": zip_path.stat().st_size,
            "progress_percent": 100.0,
            "staging": str(staging),
            "log": str(log_path),
            "pid": int(process.pid),
        }
        _write_state(state)
        return {"ok": True, "scheduled": True, **state}
    except ReleaseUpdateError as exc:
        _update_state(
            status="failed",
            phase="failed",
            message="一键升级未启动",
            error=str(exc),
        )
        raise
    except Exception as exc:
        _update_state(
            status="failed",
            phase="failed",
            message="一键升级发生未预期错误",
            error=exc.__class__.__name__,
        )
        raise


__all__ = [
    "ReleaseUpdateError",
    "release_update_status",
    "save_release_token",
    "start_release_update",
]
