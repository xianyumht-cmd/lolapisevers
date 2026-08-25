from __future__ import annotations

import concurrent.futures
import os
import re
import threading
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import requests


_EXTRA_RELEASE_MIRRORS = (
    ("gh-proxy.org", "https://gh-proxy.org/"),
    ("gh.xmly.dev", "https://gh.xmly.dev/"),
    ("hub.glowp.xyz", "https://hub.glowp.xyz/"),
    ("proxy.vvvv.ee", "https://proxy.vvvv.ee/"),
    ("cors.isteed.cc", "https://cors.isteed.cc/"),
    ("githubcdn.com", "https://githubcdn.com/"),
    ("v6.gh-proxy.org", "https://v6.gh-proxy.org/"),
    ("ghproxy.lvedong.eu.org", "https://ghproxy.lvedong.eu.org/"),
)

_ALLOWED_SIGNED_CDN_HOSTS = {
    "release-assets.githubusercontent.com",
    "objects.githubusercontent.com",
}
_MIN_PARALLEL_BYTES = 8 * 1024 * 1024
_SEGMENT_SUFFIX = ".range-"


class _ParallelRangeUnavailable(RuntimeError):
    pass


def _cdn_connections() -> int:
    try:
        value = int(os.getenv("LOLAPI_UPDATE_CDN_CONNECTIONS", "6"))
    except ValueError:
        value = 6
    return max(2, min(value, 8))


def _extend_default_mirrors(core_module: Any) -> None:
    current = tuple(getattr(core_module, "_DEFAULT_RELEASE_MIRRORS", ()))
    seen = {str(prefix) for _label, prefix in current}
    values = list(current)
    for label, prefix in _EXTRA_RELEASE_MIRRORS:
        if prefix in seen:
            continue
        seen.add(prefix)
        values.append((label, prefix))
    core_module._DEFAULT_RELEASE_MIRRORS = tuple(values)


def _signed_cdn_candidate(asset: dict[str, Any], token: str, core_module: Any) -> dict[str, Any] | None:
    api_url = str(asset.get("url") or "").strip()
    if not api_url or not token:
        return None
    try:
        response = requests.get(
            api_url,
            headers=core_module._headers(token, accept="application/octet-stream"),
            timeout=(3.0, 8.0),
            allow_redirects=False,
            stream=True,
        )
    except requests.RequestException:
        return None
    try:
        if response.status_code not in {301, 302, 303, 307, 308}:
            return None
        location = str(response.headers.get("location") or "").strip()
    finally:
        response.close()
    if not location:
        return None
    parsed = urlsplit(location)
    host = str(parsed.hostname or "").lower()
    if parsed.scheme != "https" or host not in _ALLOWED_SIGNED_CDN_HOSTS:
        return None
    return {
        "label": f"github-cdn-{_cdn_connections()}x",
        "url": location,
        "headers": core_module._public_headers(),
        "mirror": False,
        "official": True,
        "parallel_ranges": True,
    }


def _install_candidate_wrapper(core_module: Any) -> None:
    if getattr(core_module, "_cn_accel_candidates_installed", False):
        return
    original = core_module._download_candidates

    def accelerated_candidates(asset: dict[str, Any], token: str) -> list[dict[str, Any]]:
        values = list(original(asset, token))
        signed = _signed_cdn_candidate(asset, token, core_module)
        if signed is not None:
            insert_at = next(
                (index for index, item in enumerate(values) if item.get("label") == "github-api"),
                len(values),
            )
            values.insert(insert_at, signed)
        deduped: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in values:
            url = str(item.get("url") or "")
            if not url or url in seen:
                continue
            seen.add(url)
            deduped.append(item)
        return deduped

    core_module._download_candidates = accelerated_candidates
    core_module._cn_accel_candidates_installed = True


def _segment_paths(temp: Path, count: int) -> list[Path]:
    return [temp.with_name(temp.name + _SEGMENT_SUFFIX + str(index)) for index in range(count)]


def _cleanup_segments(paths: list[Path]) -> None:
    for path in paths:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass


def _split_ranges(start: int, end: int, count: int) -> list[tuple[int, int]]:
    if end < start:
        return []
    total = end - start + 1
    count = max(1, min(count, total))
    base, extra = divmod(total, count)
    values: list[tuple[int, int]] = []
    cursor = start
    for index in range(count):
        size = base + (1 if index < extra else 0)
        values.append((cursor, cursor + size - 1))
        cursor += size
    return values


def _commit_contiguous_prefix(temp: Path, segments: list[Path], ranges: list[tuple[int, int]]) -> int:
    committed = 0
    with temp.open("ab") as output:
        for path, (start, end) in zip(segments, ranges):
            expected = end - start + 1
            try:
                size = path.stat().st_size
            except OSError:
                break
            if size <= 0 or size > expected:
                break
            with path.open("rb") as handle:
                while True:
                    chunk = handle.read(1024 * 1024)
                    if not chunk:
                        break
                    output.write(chunk)
            committed += size
            if size < expected:
                break
        output.flush()
    return committed


def _validate_content_range(value: str, start: int, end: int, expected_bytes: int) -> bool:
    match = re.fullmatch(r"bytes\s+(\d+)-(\d+)/(\d+|\*)", str(value or "").strip(), re.I)
    if not match:
        return False
    got_start = int(match.group(1))
    got_end = int(match.group(2))
    total = match.group(3)
    if got_start != start or got_end != end:
        return False
    if total != "*" and expected_bytes and int(total) != expected_bytes:
        return False
    return True


def _parallel_range_download(
    candidate: dict[str, Any],
    destination: Path,
    expected_bytes: int,
    controller_module: Any,
) -> int:
    if expected_bytes < _MIN_PARALLEL_BYTES:
        raise _ParallelRangeUnavailable("package_too_small")

    temp = destination.with_suffix(destination.suffix + ".part")
    temp.parent.mkdir(parents=True, exist_ok=True)
    offset = temp.stat().st_size if temp.exists() else 0
    if offset > expected_bytes:
        temp.unlink(missing_ok=True)
        offset = 0
    if offset == expected_bytes:
        os.replace(temp, destination)
        return expected_bytes

    remaining = expected_bytes - offset
    if remaining < _MIN_PARALLEL_BYTES:
        raise _ParallelRangeUnavailable("remaining_too_small")

    controller_module._pause_if_requested(
        source=str(candidate["label"]),
        total=offset,
        expected_bytes=expected_bytes,
        offset=offset,
    )
    if controller_module._RESET_EVENT.is_set():
        raise controller_module._ResetRequested()
    if controller_module._RECONNECT_EVENT.is_set():
        controller_module._RECONNECT_EVENT.clear()
        raise controller_module._ReconnectRequested()

    count = min(_cdn_connections(), max(2, remaining // (4 * 1024 * 1024)))
    ranges = _split_ranges(offset, expected_bytes - 1, int(count))
    segments = _segment_paths(temp, len(ranges))
    _cleanup_segments(segments)

    abort = threading.Event()
    progress = [0 for _ in ranges]
    progress_lock = threading.Lock()
    started = time.perf_counter()

    def worker(index: int, start: int, end: int, path: Path) -> None:
        headers = dict(candidate.get("headers") or {})
        headers["Range"] = f"bytes={start}-{end}"
        written = 0
        try:
            with requests.get(
                str(candidate["url"]),
                headers=headers,
                timeout=(3.0, 12.0),
                allow_redirects=True,
                stream=True,
            ) as response:
                if response.status_code != 206:
                    raise _ParallelRangeUnavailable(f"range_http_{response.status_code}")
                if not _validate_content_range(
                    str(response.headers.get("content-range") or ""),
                    start,
                    end,
                    expected_bytes,
                ):
                    raise _ParallelRangeUnavailable("invalid_content_range")
                with path.open("wb") as handle:
                    for chunk in response.iter_content(chunk_size=64 * 1024):
                        if abort.is_set():
                            break
                        if (
                            controller_module._RESET_EVENT.is_set()
                            or controller_module._RECONNECT_EVENT.is_set()
                            or controller_module._PAUSE_EVENT.is_set()
                        ):
                            abort.set()
                            break
                        if not chunk:
                            continue
                        remaining_for_segment = end - start + 1 - written
                        if len(chunk) > remaining_for_segment:
                            raise _ParallelRangeUnavailable("range_overflow")
                        handle.write(chunk)
                        handle.flush()
                        written += len(chunk)
                        with progress_lock:
                            progress[index] = written
                if not abort.is_set() and written != end - start + 1:
                    raise _ParallelRangeUnavailable("short_range")
        except requests.RequestException as exc:
            raise _ParallelRangeUnavailable(exc.__class__.__name__) from exc

    futures: list[concurrent.futures.Future[None]] = []
    errors: list[BaseException] = []
    last_state_at = 0.0
    try:
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=len(ranges),
            thread_name_prefix="release-cdn-range",
        ) as pool:
            for index, ((start, end), path) in enumerate(zip(ranges, segments)):
                futures.append(pool.submit(worker, index, start, end, path))

            while True:
                done, _pending = concurrent.futures.wait(
                    futures,
                    timeout=0.2,
                    return_when=concurrent.futures.FIRST_EXCEPTION,
                )
                for future in done:
                    if future.cancelled():
                        continue
                    exc = future.exception()
                    if exc is not None and exc not in errors:
                        errors.append(exc)
                        abort.set()
                now = time.monotonic()
                if now - last_state_at >= 0.6:
                    with progress_lock:
                        transferred = sum(progress)
                    total = min(expected_bytes, offset + transferred)
                    elapsed = max(time.perf_counter() - started, 0.001)
                    controller_module._write_runtime_state(
                        status="downloading",
                        phase="download_parallel",
                        message=f"正在从 {candidate['label']} 并发分片下载 V3 包",
                        download_source=candidate["label"],
                        downloaded_bytes=total,
                        package_bytes=expected_bytes,
                        progress_percent=round(total * 100.0 / expected_bytes, 1),
                        speed_mbps=round(transferred / elapsed / 1024 / 1024, 2),
                        resumed_bytes=offset,
                        parallel_connections=len(ranges),
                    )
                    last_state_at = now
                if all(future.done() for future in futures):
                    break
                if (
                    controller_module._RESET_EVENT.is_set()
                    or controller_module._RECONNECT_EVENT.is_set()
                    or controller_module._PAUSE_EVENT.is_set()
                ):
                    abort.set()

        committed = _commit_contiguous_prefix(temp, segments, ranges)
        offset += committed
    finally:
        _cleanup_segments(segments)

    if controller_module._RESET_EVENT.is_set():
        raise controller_module._ResetRequested()
    if controller_module._RECONNECT_EVENT.is_set():
        controller_module._RECONNECT_EVENT.clear()
        raise controller_module._ReconnectRequested()
    if controller_module._PAUSE_EVENT.is_set():
        controller_module._pause_if_requested(
            source=str(candidate["label"]),
            total=offset,
            expected_bytes=expected_bytes,
            offset=offset,
        )
        return _parallel_range_download(candidate, destination, expected_bytes, controller_module)
    if errors:
        first = errors[0]
        raise _ParallelRangeUnavailable(str(first)[:200])
    if offset != expected_bytes:
        raise _ParallelRangeUnavailable(f"assembled_size_{offset}")

    os.replace(temp, destination)
    return expected_bytes


def _install_controller_downloader(core_module: Any, controller_module: Any) -> None:
    if getattr(controller_module, "_cn_accel_downloader_installed", False):
        return
    original = controller_module._download_one_connection

    def accelerated_download(
        candidate: dict[str, Any],
        destination: Path,
        expected_bytes: int,
    ) -> int:
        if not candidate.get("parallel_ranges"):
            return original(candidate, destination, expected_bytes)
        try:
            return _parallel_range_download(candidate, destination, expected_bytes, controller_module)
        except (
            controller_module._ResetRequested,
            controller_module._ReconnectRequested,
        ):
            raise
        except _ParallelRangeUnavailable as exc:
            controller_module._write_runtime_state(
                status="reconnecting",
                phase="parallel_fallback",
                message=f"{candidate['label']} 并发分片不可用，回退单连接续传。",
                download_source=candidate["label"],
                parallel_fallback=str(exc)[:200],
            )
            single = dict(candidate)
            single["parallel_ranges"] = False
            return original(single, destination, expected_bytes)

    controller_module._download_one_connection = accelerated_download
    controller_module._cn_accel_downloader_installed = True


def install(core_module: Any, controller_module: Any) -> None:
    if getattr(core_module, "_cn_release_accelerator_installed", False):
        return
    _extend_default_mirrors(core_module)
    _install_candidate_wrapper(core_module)
    _install_controller_downloader(core_module, controller_module)
    core_module._cn_release_accelerator_installed = True


__all__ = [
    "install",
]
