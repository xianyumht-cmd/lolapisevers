from __future__ import annotations

import concurrent.futures
import hashlib
import io
import json
import os
import re
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CACHE_ROOT = PROJECT_ROOT / "data" / "image-cache"
CDRAGON_BASE = "https://raw.communitydragon.org/latest/plugins/rcp-be-lol-game-data/global/default/v1"
GTIMG_BASE = "https://game.gtimg.cn/images/lol/act/img"

_PROFILE_RE = re.compile(r"/profileicon/(\d+)\.(?:png|jpg|jpeg|webp)(?:$|\?)", re.IGNORECASE)
_CHAMPION_RE = re.compile(r"/champion-icons/(\d+)\.(?:png|jpg|jpeg|webp)(?:$|\?)", re.IGNORECASE)
_ITEM_RE = re.compile(r"/item/(\d+)\.(?:png|jpg|jpeg|webp)(?:$|\?)", re.IGNORECASE)
_VALID_KINDS = {"profile", "champion", "item", "misc"}


def _env_bool(name: str, default: bool) -> bool:
    value = str(os.getenv(name, "1" if default else "0")).strip().lower()
    return value not in {"0", "false", "no", "off", ""}


def _env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(str(os.getenv(name, default)).strip())
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(parsed, maximum))


def _env_float(name: str, default: float, minimum: float, maximum: float) -> float:
    try:
        parsed = float(str(os.getenv(name, default)).strip())
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(parsed, maximum))


def _utc_now_text() -> str:
    return datetime.now(timezone.utc).isoformat()


def image_asset_url(kind: str, asset_id: str | int) -> str:
    normalized_kind = str(kind or "").strip().lower()
    normalized_id = str(asset_id or "").strip()
    if not normalized_id.isdigit():
        return ""
    if normalized_kind == "profile":
        return f"{GTIMG_BASE}/profileicon/{normalized_id}.png"
    if normalized_kind == "champion":
        return f"{CDRAGON_BASE}/champion-icons/{normalized_id}.png"
    if normalized_kind == "item":
        return f"{GTIMG_BASE}/item/{normalized_id}.png"
    return ""


def classify_image_url(url: str) -> tuple[str, str]:
    normalized = str(url or "").strip()
    for kind, pattern in (
        ("profile", _PROFILE_RE),
        ("champion", _CHAMPION_RE),
        ("item", _ITEM_RE),
    ):
        match = pattern.search(normalized)
        if match:
            return kind, match.group(1)
    digest = hashlib.sha256(normalized.encode("utf-8", errors="ignore")).hexdigest()
    return "misc", digest


def _validate_image_bytes(content: bytes) -> tuple[bool, str]:
    if not isinstance(content, bytes) or not content:
        return False, "empty_image"
    if len(content) > 5_000_000:
        return False, "image_too_large"
    try:
        from PIL import Image

        with Image.open(io.BytesIO(content)) as image:
            width, height = image.size
            image.verify()
        if width <= 0 or height <= 0:
            return False, "invalid_dimensions"
        return True, ""
    except Exception as exc:
        return False, f"invalid_image:{exc}"


class DiskImageAssetStore:
    """Persistent image cache keyed by stable LoL resource IDs.

    Known profile/champion/item assets are stored as ``<kind>/<id>.png``.
    Unknown URLs use a SHA-256 filename under ``misc``. Writes are atomic and
    failed refreshes never delete the previous valid file.
    """

    def __init__(
        self,
        root: Optional[Path] = None,
        *,
        enabled: Optional[bool] = None,
        ttl_days: Optional[int] = None,
    ):
        configured_root = str(os.getenv("IMAGE_ASSET_CACHE_DIR") or "").strip()
        self.root = Path(root or configured_root or DEFAULT_CACHE_ROOT).expanduser().resolve()
        self.enabled = _env_bool("IMAGE_ASSET_DISK_CACHE_ENABLED", True) if enabled is None else bool(enabled)
        self.ttl_days = (
            _env_int("IMAGE_ASSET_CACHE_TTL_DAYS", 0, 0, 36500)
            if ttl_days is None
            else max(0, int(ttl_days))
        )
        self._lock = threading.RLock()

    def _path(self, kind: str, asset_id: str) -> Path:
        safe_kind = kind if kind in _VALID_KINDS else "misc"
        safe_id = str(asset_id or "").strip()
        if safe_kind != "misc" and not safe_id.isdigit():
            raise ValueError("known image asset IDs must be numeric")
        if safe_kind == "misc" and not re.fullmatch(r"[0-9a-f]{64}", safe_id):
            safe_id = hashlib.sha256(safe_id.encode("utf-8", errors="ignore")).hexdigest()
        suffix = ".png" if safe_kind != "misc" else ".img"
        return self.root / safe_kind / f"{safe_id}{suffix}"

    def path_for_url(self, url: str) -> Path:
        kind, asset_id = classify_image_url(url)
        return self._path(kind, asset_id)

    def _is_expired(self, path: Path) -> bool:
        if self.ttl_days <= 0:
            return False
        try:
            age_seconds = max(0.0, time.time() - path.stat().st_mtime)
        except OSError:
            return True
        return age_seconds > self.ttl_days * 86400

    def read_url(self, url: str, *, allow_stale: bool = False) -> Optional[bytes]:
        if not self.enabled:
            return None
        path = self.path_for_url(url)
        try:
            if not path.is_file():
                return None
            if not allow_stale and self._is_expired(path):
                return None
            content = path.read_bytes()
        except OSError:
            return None
        if not content or len(content) > 5_000_000:
            return None
        return content

    def write_url(self, url: str, content: bytes) -> dict[str, Any]:
        if not self.enabled:
            return {"ok": False, "status": "disabled"}
        valid, error = _validate_image_bytes(content)
        if not valid:
            return {"ok": False, "status": "invalid", "error": error}
        kind, asset_id = classify_image_url(url)
        path = self._path(kind, asset_id)
        digest = hashlib.sha256(content).hexdigest()
        old_digest = ""
        with self._lock:
            try:
                if path.exists():
                    old_digest = hashlib.sha256(path.read_bytes()).hexdigest()
            except OSError:
                old_digest = ""
            if old_digest == digest:
                try:
                    os.utime(path, None)
                except OSError:
                    pass
                return {
                    "ok": True,
                    "status": "unchanged",
                    "kind": kind,
                    "id": asset_id,
                    "path": str(path),
                    "sha256": digest,
                }

            path.parent.mkdir(parents=True, exist_ok=True)
            temp_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
            try:
                with temp_path.open("wb") as handle:
                    handle.write(content)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temp_path, path)
            finally:
                temp_path.unlink(missing_ok=True)

        return {
            "ok": True,
            "status": "updated" if old_digest else "downloaded",
            "kind": kind,
            "id": asset_id,
            "path": str(path),
            "sha256": digest,
        }

    def fetch_url(
        self,
        url: str,
        *,
        force: bool = False,
        timeout: Optional[float] = None,
    ) -> dict[str, Any]:
        normalized = str(url or "").strip()
        if not normalized:
            return {"ok": False, "status": "failed", "error": "empty_url"}
        if not self.enabled:
            return {"ok": False, "status": "disabled", "error": "disk_cache_disabled"}
        current = self.read_url(normalized, allow_stale=False)
        if current is not None and not force:
            kind, asset_id = classify_image_url(normalized)
            return {
                "ok": True,
                "status": "cached",
                "kind": kind,
                "id": asset_id,
                "path": str(self.path_for_url(normalized)),
            }

        try:
            import requests

            response = requests.get(
                normalized,
                timeout=timeout or _env_float("IMAGE_ASSET_SYNC_TIMEOUT_SECONDS", 8.0, 1.0, 60.0),
                headers={
                    "Accept": "image/avif,image/webp,image/*,*/*",
                    "User-Agent": "Mozilla/5.0",
                },
            )
            content_type = str(response.headers.get("content-type") or "").lower()
            if not response.ok:
                raise RuntimeError(f"http_{response.status_code}")
            if content_type and "image" not in content_type:
                raise RuntimeError(f"unexpected_content_type:{content_type}")
            result = self.write_url(normalized, response.content)
            result["url"] = normalized
            return result
        except Exception as exc:
            stale = self.read_url(normalized, allow_stale=True)
            kind, asset_id = classify_image_url(normalized)
            return {
                "ok": stale is not None,
                "status": "stale" if stale is not None else "failed",
                "kind": kind,
                "id": asset_id,
                "path": str(self.path_for_url(normalized)),
                "url": normalized,
                "error": str(exc),
            }

    def list_ids(self, kind: str) -> list[str]:
        normalized = str(kind or "").strip().lower()
        if normalized not in {"profile", "champion", "item"}:
            return []
        directory = self.root / normalized
        if not directory.exists():
            return []
        return sorted(
            (path.stem for path in directory.glob("*.png") if path.stem.isdigit()),
            key=lambda value: int(value),
        )

    def status(self) -> dict[str, Any]:
        counts = {"profile": 0, "champion": 0, "item": 0, "misc": 0}
        expired = 0
        total_bytes = 0
        latest_mtime = 0.0
        if self.root.exists():
            for kind in counts:
                directory = self.root / kind
                if not directory.exists():
                    continue
                pattern = "*.png" if kind != "misc" else "*.img"
                for path in directory.glob(pattern):
                    try:
                        stat = path.stat()
                    except OSError:
                        continue
                    counts[kind] += 1
                    total_bytes += stat.st_size
                    latest_mtime = max(latest_mtime, stat.st_mtime)
                    if self._is_expired(path):
                        expired += 1
        return {
            "ok": True,
            "enabled": self.enabled,
            "root": str(self.root),
            "ttl_days": self.ttl_days,
            "ttl_label": "长期" if self.ttl_days == 0 else f"{self.ttl_days} 天",
            "counts": counts,
            "total_files": sum(counts.values()),
            "total_bytes": total_bytes,
            "expired_files": expired,
            "last_updated_at": (
                datetime.fromtimestamp(latest_mtime, timezone.utc).isoformat()
                if latest_mtime
                else ""
            ),
        }


class PersistentImageAssetCache:
    """Drop-in ``get``/``set`` cache used by existing image renderers.

    Disk is checked before memory so a manual WebUI refresh becomes visible to
    the main API immediately, even when the main process still holds an older
    in-memory value.
    """

    def __init__(
        self,
        *,
        ttl_seconds: int,
        max_size: int,
        store: Optional[DiskImageAssetStore] = None,
    ):
        from cache import TTLCache

        self.memory = TTLCache(ttl_seconds=ttl_seconds, max_size=max_size)
        self.store = store or get_image_asset_store()

    @staticmethod
    def _url_from_key(key: Any) -> str:
        text = str(key or "")
        prefix = "image_asset:"
        return text[len(prefix):] if text.startswith(prefix) else ""

    def get(self, key: Any) -> Any:
        url = self._url_from_key(key)
        if url:
            disk_content = self.store.read_url(url, allow_stale=False)
            if isinstance(disk_content, bytes) and disk_content:
                try:
                    self.memory.set(str(key), disk_content)
                except Exception:
                    pass
                return disk_content
        return self.memory.get(key)

    def set(self, key: Any, value: Any) -> None:
        url = self._url_from_key(key)
        if url and isinstance(value, bytes) and value:
            self.store.write_url(url, value)
        self.memory.set(key, value)


class ImageAssetSyncManager:
    def __init__(self, store: Optional[DiskImageAssetStore] = None):
        self.store = store or DiskImageAssetStore()
        self._lock = threading.RLock()
        self._state: dict[str, Any] = {
            "running": False,
            "mode": "",
            "started_at": "",
            "finished_at": "",
            "total": 0,
            "completed": 0,
            "downloaded": 0,
            "updated": 0,
            "unchanged": 0,
            "cached": 0,
            "stale": 0,
            "failed": 0,
            "error": "",
            "failures": [],
        }

    def _snapshot(self) -> dict[str, Any]:
        with self._lock:
            return json.loads(json.dumps(self._state, ensure_ascii=False))

    def status(self) -> dict[str, Any]:
        return {
            "ok": True,
            "job": self._snapshot(),
            "cache": self.store.status(),
        }

    def start(self, mode: str) -> dict[str, Any]:
        normalized_mode = str(mode or "missing").strip().lower()
        if normalized_mode not in {"missing", "update"}:
            raise ValueError("mode must be missing or update")
        with self._lock:
            if self._state.get("running"):
                return self.status()
            self._state = {
                "running": True,
                "mode": normalized_mode,
                "started_at": _utc_now_text(),
                "finished_at": "",
                "total": 0,
                "completed": 0,
                "downloaded": 0,
                "updated": 0,
                "unchanged": 0,
                "cached": 0,
                "stale": 0,
                "failed": 0,
                "error": "",
                "failures": [],
            }
        thread = threading.Thread(
            target=self._run,
            args=(normalized_mode,),
            name="lol-image-asset-sync",
            daemon=True,
        )
        thread.start()
        return self.status()

    def _manifest(self) -> list[tuple[str, str, str]]:
        from services.lol_static import get_static_lol_data

        static = get_static_lol_data()
        champion_ids = sorted(
            {key for key in (static.get("champions") or {}) if str(key).isdigit()},
            key=lambda value: int(value),
        )
        item_ids = sorted(
            {key for key in (static.get("items") or {}) if str(key).isdigit()},
            key=lambda value: int(value),
        )
        if not champion_ids and not item_ids:
            raise RuntimeError("英雄和装备静态清单为空，无法执行全量图片同步")
        profile_ids = self.store.list_ids("profile")
        manifest: list[tuple[str, str, str]] = []
        for kind, ids in (
            ("champion", champion_ids),
            ("item", item_ids),
            ("profile", profile_ids),
        ):
            for asset_id in ids:
                url = image_asset_url(kind, asset_id)
                if url:
                    manifest.append((kind, str(asset_id), url))
        return manifest

    def _record_result(self, result: dict[str, Any]) -> None:
        status = str(result.get("status") or "failed")
        with self._lock:
            self._state["completed"] += 1
            if status in {"downloaded", "updated", "unchanged", "cached", "stale"}:
                self._state[status] += 1
            else:
                self._state["failed"] += 1
                failures = self._state["failures"]
                if len(failures) < 50:
                    failures.append(
                        {
                            "kind": result.get("kind"),
                            "id": result.get("id"),
                            "error": result.get("error") or status,
                        }
                    )

    def _run(self, mode: str) -> None:
        try:
            manifest = self._manifest()
            with self._lock:
                self._state["total"] = len(manifest)
            workers = _env_int("IMAGE_ASSET_SYNC_WORKERS", 8, 1, 32)
            force = mode == "update"
            with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
                futures = [
                    executor.submit(self.store.fetch_url, url, force=force)
                    for _kind, _asset_id, url in manifest
                ]
                for future in concurrent.futures.as_completed(futures):
                    try:
                        result = future.result()
                    except Exception as exc:
                        result = {"ok": False, "status": "failed", "error": str(exc)}
                    self._record_result(result)
        except Exception as exc:
            with self._lock:
                self._state["error"] = str(exc)
        finally:
            with self._lock:
                self._state["running"] = False
                self._state["finished_at"] = _utc_now_text()


_STORE_LOCK = threading.Lock()
_STORE: Optional[DiskImageAssetStore] = None
_SYNC_MANAGER: Optional[ImageAssetSyncManager] = None
_STORE_SIGNATURE: tuple[str, str, str] | None = None


def _store_signature() -> tuple[str, str, str]:
    return (
        str(os.getenv("IMAGE_ASSET_CACHE_DIR") or ""),
        str(os.getenv("IMAGE_ASSET_DISK_CACHE_ENABLED") or ""),
        str(os.getenv("IMAGE_ASSET_CACHE_TTL_DAYS") or ""),
    )


def get_image_asset_store() -> DiskImageAssetStore:
    global _STORE, _SYNC_MANAGER, _STORE_SIGNATURE
    signature = _store_signature()
    if _STORE is not None and _STORE_SIGNATURE == signature:
        return _STORE
    with _STORE_LOCK:
        if _STORE is None or _STORE_SIGNATURE != signature:
            _STORE = DiskImageAssetStore()
            _SYNC_MANAGER = ImageAssetSyncManager(_STORE)
            _STORE_SIGNATURE = signature
    return _STORE


def get_image_asset_sync_manager() -> ImageAssetSyncManager:
    global _SYNC_MANAGER
    store = get_image_asset_store()
    if _SYNC_MANAGER is None or _SYNC_MANAGER.store is not store:
        with _STORE_LOCK:
            if _SYNC_MANAGER is None or _SYNC_MANAGER.store is not store:
                _SYNC_MANAGER = ImageAssetSyncManager(store)
    return _SYNC_MANAGER
