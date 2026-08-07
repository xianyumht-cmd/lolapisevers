from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from dataclasses import asdict, dataclass
from typing import Any, TYPE_CHECKING

from lanzou_update_push_api_server.config import WatcherConfig, load_config as load_lanzou_provider_config
from lanzou_update_push_api_server.providers import FileEntry, ProviderChain, WerApiProvider, canonical_file_key, utc_now_iso
from services.target_file_watch_service import (
    SCHEMA,
    ResolvedTargetFile,
    TargetFileWatchError,
    _direct_candidates,
    _event_id,
    _file_fingerprint,
    _stable_url,
)

if TYPE_CHECKING:
    from services.target_file_watch_runtime import SafeTargetFileWatchService


@dataclass(frozen=True)
class DirectoryResolvedFile:
    key: str
    file: ResolvedTargetFile


@dataclass(frozen=True)
class DirectorySnapshot:
    provider: str
    files: tuple[DirectoryResolvedFile, ...]

    @property
    def signature(self) -> str:
        payload = sorted(
            ({"key": item.key, "fingerprint": item.file.fingerprint} for item in self.files),
            key=lambda item: (item["key"], item["fingerprint"]),
        )
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return "sha256:" + hashlib.sha256(encoded).hexdigest()


class DirectoryLanzouResolver:
    """Resolve a Lanzou single-file share or folder into one safe snapshot.

    This intentionally reuses the existing Lanzou providers but owns no watcher,
    event or state from the legacy Lanzou monitor service.
    """

    def _watcher(self, source_url: str) -> WatcherConfig:
        return WatcherConfig(
            id="target-file-watch-directory",
            title="target-file-watch-directory",
            url=source_url,
            enabled=True,
            max_pages=20,
        )

    @staticmethod
    def _resolved(file: FileEntry, provider: str, source_url: str) -> ResolvedTargetFile:
        return ResolvedTargetFile(
            fingerprint=_file_fingerprint(file),
            stable_id=str(file.id or "").split("?", 1)[0].split("#", 1)[0],
            name=str(file.name or "").strip() or "download.bin",
            size=str(file.size or "").strip(),
            modified_time=str(file.modified_time or "").strip(),
            share_link=str(file.link or source_url).strip(),
            provider=str(provider or "").strip(),
        )

    def resolve_snapshot(self, source_url: str) -> DirectorySnapshot:
        provider_config = load_lanzou_provider_config()
        watcher = self._watcher(source_url)
        snapshot = ProviderChain(provider_config).fetch(watcher)
        if not snapshot.files:
            # An empty upstream response can also be a challenge/anti-bot page.
            # Never turn it into a destructive "all files removed" decision.
            raise TargetFileWatchError("蓝奏目录未解析到文件；为避免误判删除，本轮不推进 baseline")

        items: list[DirectoryResolvedFile] = []
        keys: set[str] = set()
        for entry in snapshot.files:
            key = canonical_file_key(entry)
            if key in keys:
                raise TargetFileWatchError(f"蓝奏目录存在无法安全区分的同名文件：{entry.name}")
            keys.add(key)
            items.append(DirectoryResolvedFile(key=key, file=self._resolved(entry, snapshot.provider, source_url)))
        return DirectorySnapshot(provider=str(snapshot.provider or "").strip(), files=tuple(items))

    def resolve_for_delivery(self, source_url: str, key: str, fingerprint: str) -> ResolvedTargetFile:
        fresh = self.resolve_snapshot(source_url)
        current = [item for item in fresh.files if item.key == key]
        if len(current) != 1 or current[0].file.fingerprint != fingerprint:
            raise TargetFileWatchError("目标文件在投递前再次变化，旧事件已失效")
        metadata = current[0].file

        provider_config = load_lanzou_provider_config()
        watcher = self._watcher(source_url)
        try:
            resolved_snapshot = WerApiProvider().fetch(watcher, provider_config)
            matches = [item for item in resolved_snapshot.files if canonical_file_key(item) == key]
            if len(matches) != 1:
                raise TargetFileWatchError("直链 Provider 未唯一匹配到目标文件")
            candidate_file = matches[0]
            for candidate in _direct_candidates(candidate_file):
                if _stable_url(candidate) == _stable_url(source_url):
                    continue
                return ResolvedTargetFile(**{**asdict(metadata), "direct_url": candidate})
        except TargetFileWatchError:
            raise
        except Exception as exc:
            logging.getLogger("LOLDataSystem.TargetFileWatch").warning(
                "fresh Lanzou directory direct-url resolution failed: %s",
                type(exc).__name__,
            )
        raise TargetFileWatchError("未取得可下载直链；请确认现有蓝奏直链 Provider/API Key 配置可用")


def _file_state(item: DirectoryResolvedFile) -> dict[str, Any]:
    file = item.file
    return {
        "key": item.key,
        "fingerprint": file.fingerprint,
        "stable_id": file.stable_id,
        "name": file.name,
        "size": file.size,
        "modified_time": file.modified_time,
        "share_link": file.share_link,
        "provider": file.provider,
    }


def _snapshot_state(snapshot: DirectorySnapshot) -> dict[str, Any]:
    return {
        "signature": snapshot.signature,
        "provider": snapshot.provider,
        "file_count": len(snapshot.files),
        "files": [_file_state(item) for item in snapshot.files],
    }


def _legacy_file_key(value: dict[str, Any]) -> str:
    return canonical_file_key(
        FileEntry(
            id=str(value.get("stable_id") or ""),
            name=str(value.get("name") or ""),
            size=str(value.get("size") or ""),
            modified_time=str(value.get("modified_time") or ""),
            link=str(value.get("share_link") or ""),
        )
    )


def _baseline_files(value: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(value, dict):
        return {}
    files = value.get("files")
    if isinstance(files, list):
        out: dict[str, dict[str, Any]] = {}
        for raw in files:
            if not isinstance(raw, dict):
                continue
            key = str(raw.get("key") or "").strip() or _legacy_file_key(raw)
            out[key] = raw
        return out
    if value.get("fingerprint"):
        key = _legacy_file_key(value)
        return {key: {"key": key, **value}}
    return {}


async def check_directory_once(
    service: "SafeTargetFileWatchService",
    resolver: DirectoryLanzouResolver,
) -> dict[str, Any]:
    async with service._check_lock:
        service._load_config()
        if not service._config.enabled:
            return {"ok": False, "skipped": True, "error": "target_file_watch_disabled"}

        now = utc_now_iso()
        try:
            current = await asyncio.to_thread(resolver.resolve_snapshot, service._config.source_url)
            current_state = _snapshot_state(current)
            service._state["last_check_at"] = now
            service._state["last_success_at"] = now
            service._state["last_error_code"] = ""
            service._state["source_url"] = service._config.source_url

            baseline = service._state.get("baseline") if isinstance(service._state.get("baseline"), dict) else None
            if baseline is None:
                service._state["baseline"] = current_state
                service._state["pending"] = None
                service._save_state()
                return {
                    "ok": True,
                    "state": "baselined",
                    "uploaded": False,
                    "file_count": len(current.files),
                    "signature": current.signature,
                }

            baseline_map = _baseline_files(baseline)
            current_map = {item.key: item for item in current.files}
            changed = [
                item
                for item in current.files
                if item.key not in baseline_map
                or str(baseline_map[item.key].get("fingerprint") or "") != item.file.fingerprint
            ]
            removed_keys = [key for key in baseline_map if key not in current_map]

            if not changed:
                state_name = "baseline_updated" if removed_keys else "unchanged"
                service._state["baseline"] = current_state
                service._state["pending"] = None
                service._save_state()
                return {
                    "ok": True,
                    "state": state_name,
                    "uploaded": False,
                    "file_count": len(current.files),
                    "removed_count": len(removed_keys),
                    "signature": current.signature,
                }

            pending_events: list[dict[str, Any]] = []
            for item in changed:
                event_id = _event_id(service._config.source_url, item.file.fingerprint)
                pending_events.append(
                    {
                        "event_id": event_id,
                        "key": item.key,
                        "fingerprint": item.file.fingerprint,
                        "file": item.file.public_file(),
                    }
                )
            service._state["pending"] = {
                "detected_at": now,
                "target_signature": current.signature,
                "events": pending_events,
                "removed_keys": removed_keys,
            }
            service._save_state()

            delivered: list[dict[str, Any]] = []
            for item, pending in zip(changed, pending_events):
                delivery = await asyncio.to_thread(
                    resolver.resolve_for_delivery,
                    service._config.source_url,
                    item.key,
                    item.file.fingerprint,
                )
                payload = {
                    "schema": SCHEMA,
                    "event_id": pending["event_id"],
                    "source_url": service._config.source_url,
                    "fingerprint": item.file.fingerprint,
                    "detected_at": now,
                    "file": delivery.public_file(),
                    "direct_url": delivery.direct_url,
                }
                response = await asyncio.to_thread(service._deliver, payload)
                delivered.append(
                    {
                        "event_id": pending["event_id"],
                        "file": delivery.public_file(),
                        "callback": response,
                    }
                )

            service._state["baseline"] = current_state
            service._state["pending"] = None
            service._state["last_delivery_at"] = utc_now_iso()
            service._state["last_event_id"] = delivered[-1]["event_id"] if delivered else ""
            service._state["last_error_code"] = ""
            service._save_state()
            return {
                "ok": True,
                "state": "delivered",
                "uploaded": True,
                "uploaded_count": len(delivered),
                "removed_count": len(removed_keys),
                "file_count": len(current.files),
                "events": delivered,
                "signature": current.signature,
            }
        except Exception as exc:
            service._state["last_check_at"] = now
            service._state["last_error_at"] = utc_now_iso()
            service._state["last_error_code"] = str(exc)[:240]
            service._save_state()
            raise
