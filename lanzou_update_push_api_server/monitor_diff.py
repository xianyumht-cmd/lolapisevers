from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any

from .providers import FileEntry, ShareSnapshot, canonical_file_key


def compare_snapshots(
    previous: ShareSnapshot,
    current: ShareSnapshot,
) -> dict[str, list[dict[str, Any]]]:
    use_provider_fingerprint = previous.provider == current.provider

    def fingerprint(item: FileEntry) -> dict[str, str]:
        return (
            item.fingerprint_payload()
            if use_provider_fingerprint
            else item.canonical_fingerprint_payload()
        )

    def grouped(files: list[FileEntry]) -> dict[str, list[FileEntry]]:
        result: dict[str, list[FileEntry]] = {}
        for item in files:
            result.setdefault(canonical_file_key(item), []).append(item)
        for values in result.values():
            values.sort(
                key=lambda item: json.dumps(
                    fingerprint(item),
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
            )
        return result

    previous_map = grouped(previous.files)
    current_map = grouped(current.files)
    added: list[dict[str, Any]] = []
    removed: list[dict[str, Any]] = []
    changed: list[dict[str, Any]] = []
    for key in sorted(set(previous_map) | set(current_map)):
        old_items = previous_map.get(key, [])
        new_items = current_map.get(key, [])
        paired_count = min(len(old_items), len(new_items))
        for index in range(paired_count):
            old = old_items[index]
            new = new_items[index]
            if fingerprint(old) != fingerprint(new):
                changed.append({"before": asdict(old), "after": asdict(new)})
        removed.extend(asdict(item) for item in old_items[paired_count:])
        added.extend(asdict(item) for item in new_items[paired_count:])
    return {"added": added, "removed": removed, "changed": changed}
