import concurrent.futures
import functools
import io
import os
import threading
import time
from typing import Any, Dict, Iterable, List, Optional


NEGATIVE_IMAGE_CACHE_VALUE = b""
_BACKGROUND_IMAGE_LOCK = threading.Lock()
_BACKGROUND_IMAGE_EXECUTOR: Optional[concurrent.futures.ThreadPoolExecutor] = None
_BACKGROUND_IMAGE_INFLIGHT: set[str] = set()
_BACKGROUND_IMAGE_RETRY_AFTER: Dict[str, float] = {}


def _env_bool(name: str, default: bool) -> bool:
    value = str(os.getenv(name, "1" if default else "0")).strip().lower()
    return value not in {"0", "false", "no", "off", ""}


@functools.lru_cache(maxsize=64)
def load_image_font(size: int, bold: bool = False):
    try:
        from PIL import ImageFont

        candidates = [
            r"C:\Windows\Fonts\msyhbd.ttc" if bold else r"C:\Windows\Fonts\msyh.ttc",
            r"C:\Windows\Fonts\simhei.ttf",
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc" if bold else "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
            r"C:\Windows\Fonts\arial.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        ]
        for font_path in candidates:
            if font_path and os.path.exists(font_path):
                return ImageFont.truetype(font_path, size)
        return ImageFont.load_default()
    except Exception:
        return None


def wrap_draw_text(draw: Any, text: str, font: Any, max_width: int) -> List[str]:
    if not text:
        return [""]
    lines: List[str] = []
    current = ""
    for ch in text:
        trial = current + ch
        try:
            width = draw.textbbox((0, 0), trial, font=font)[2]
        except Exception:
            width = len(trial) * 12
        if current and width > max_width:
            lines.append(current)
            current = ch
        else:
            current = trial
    if current:
        lines.append(current)
    return lines


def fit_text(draw: Any, text: Any, font: Any, max_width: int) -> str:
    value = str(text or "")
    if not value:
        return ""
    try:
        if draw.textbbox((0, 0), value, font=font)[2] <= max_width:
            return value
        ellipsis = "..."
        if draw.textbbox((0, 0), ellipsis, font=font)[2] > max_width:
            return ellipsis

        # Long player/item strings used to be measured once per removed
        # character. Binary search keeps the same output contract while cutting
        # textbbox calls from O(n) to O(log n).
        low = 0
        high = len(value)
        while low < high:
            middle = (low + high + 1) // 2
            candidate = value[:middle] + ellipsis
            if draw.textbbox((0, 0), candidate, font=font)[2] <= max_width:
                low = middle
            else:
                high = middle - 1
        return value[:low] + ellipsis
    except Exception:
        return value[: max(max_width // 12, 1)]


def _env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(str(os.getenv(name, default)).strip())
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(value, maximum))


def _env_float(name: str, default: float, minimum: float, maximum: float) -> float:
    try:
        value = float(str(os.getenv(name, default)).strip())
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(value, maximum))


def image_footer_left() -> str:
    default = "GroupGuardKing-GGK"
    return str(os.getenv("IMAGE_FOOTER_LEFT", default)).strip() or default


def image_footer_right() -> str:
    default = "致力于企业级群管解决方案"
    return str(os.getenv("IMAGE_FOOTER_RIGHT", default)).strip() or default


def image_limits() -> Dict[str, int]:
    return {
        "max_bytes": _env_int("IMAGE_MAX_BYTES", 760_000, 180_000, 2_000_000),
        "max_width": _env_int("IMAGE_MAX_WIDTH", 1080, 640, 1920),
        "max_height": _env_int("IMAGE_MAX_HEIGHT", 1800, 720, 3200),
    }


def _cache_image_result(cache: Any, cache_key: str, content: bytes) -> None:
    if cache is None:
        return
    try:
        cache.set(cache_key, content)
    except Exception:
        pass


def download_image_cached(
    cache: Any,
    url: str,
    timeout: float = 4.0,
    *,
    negative_cache: bool = True,
) -> Optional[bytes]:
    url = str(url or "").strip()
    if not url:
        return None
    cache_key = f"image_asset:{url}"
    if cache is not None:
        cached = cache.get(cache_key)
        if isinstance(cached, bytes):
            return cached or None
    try:
        import requests

        response = requests.get(
            url,
            timeout=timeout,
            headers={"Accept": "image/avif,image/webp,image/*,*/*", "User-Agent": "Mozilla/5.0"},
        )
        content_type = str(response.headers.get("content-type") or "").lower()
        content = response.content
        if not response.ok or not content or len(content) > 2_500_000:
            if negative_cache:
                _cache_image_result(cache, cache_key, NEGATIVE_IMAGE_CACHE_VALUE)
            return None
        if content_type and "image" not in content_type:
            if negative_cache:
                _cache_image_result(cache, cache_key, NEGATIVE_IMAGE_CACHE_VALUE)
            return None
        _cache_image_result(cache, cache_key, content)
        return content
    except Exception:
        if negative_cache:
            _cache_image_result(cache, cache_key, NEGATIVE_IMAGE_CACHE_VALUE)
        return None


def _image_asset_priority(url: str) -> int:
    lowered = url.lower()
    if "profileicon" in lowered:
        return 0
    if "champion-icons" in lowered or "/champion/" in lowered:
        return 1
    if "/item/" in lowered:
        return 2
    return 3


def _background_image_executor() -> concurrent.futures.ThreadPoolExecutor:
    global _BACKGROUND_IMAGE_EXECUTOR
    with _BACKGROUND_IMAGE_LOCK:
        if _BACKGROUND_IMAGE_EXECUTOR is None:
            workers = _env_int("IMAGE_ASSET_BACKGROUND_WORKERS", 4, 1, 16)
            _BACKGROUND_IMAGE_EXECUTOR = concurrent.futures.ThreadPoolExecutor(
                max_workers=workers,
                thread_name_prefix="image-asset-refresh",
            )
        return _BACKGROUND_IMAGE_EXECUTOR


def _schedule_image_refresh(cache: Any, url: str) -> bool:
    """Schedule a missing decorative asset without delaying the current query.

    A small process-wide pool and single-flight set prevent a burst of identical
    player queries from creating duplicate CDN requests. Failures have a short
    cooldown, but are not written into the long-lived negative cache, so a
    temporary CDN outage cannot hide an asset for the full image-cache TTL.
    """

    normalized = str(url or "").strip()
    if not normalized:
        return False

    now = time.monotonic()
    with _BACKGROUND_IMAGE_LOCK:
        retry_after = _BACKGROUND_IMAGE_RETRY_AFTER.get(normalized, 0.0)
        if normalized in _BACKGROUND_IMAGE_INFLIGHT or retry_after > now:
            return False
        _BACKGROUND_IMAGE_INFLIGHT.add(normalized)

    timeout = _env_float("IMAGE_ASSET_BACKGROUND_TIMEOUT_SECONDS", 4.0, 0.5, 15.0)
    cooldown = _env_float("IMAGE_ASSET_BACKGROUND_RETRY_SECONDS", 30.0, 1.0, 600.0)

    def refresh() -> None:
        succeeded = False
        try:
            succeeded = bool(
                download_image_cached(
                    cache,
                    normalized,
                    timeout=timeout,
                    negative_cache=False,
                )
            )
        finally:
            with _BACKGROUND_IMAGE_LOCK:
                _BACKGROUND_IMAGE_INFLIGHT.discard(normalized)
                if succeeded:
                    _BACKGROUND_IMAGE_RETRY_AFTER.pop(normalized, None)
                else:
                    _BACKGROUND_IMAGE_RETRY_AFTER[normalized] = time.monotonic() + cooldown

    try:
        _background_image_executor().submit(refresh)
        return True
    except Exception:
        with _BACKGROUND_IMAGE_LOCK:
            _BACKGROUND_IMAGE_INFLIGHT.discard(normalized)
            _BACKGROUND_IMAGE_RETRY_AFTER[normalized] = time.monotonic() + cooldown
        return False


def prefetch_image_urls(
    cache: Any,
    urls: Iterable[str],
    *,
    timeout: float = 4.0,
    max_workers: int = 8,
    max_assets: int = 72,
    overall_timeout: Optional[float] = None,
    blocking_network: Optional[bool] = None,
) -> Dict[str, bytes]:
    unique: List[str] = []
    seen = set()
    for raw_url in urls:
        url = str(raw_url or "").strip()
        if not url or url in seen:
            continue
        seen.add(url)
        unique.append(url)
        if len(unique) >= max_assets:
            break

    # Profile and champion icons are more important than item icons when the
    # local cache is incomplete.
    unique.sort(key=_image_asset_priority)

    result: Dict[str, bytes] = {}
    missing: List[str] = []
    for url in unique:
        cached = cache.get(f"image_asset:{url}") if cache is not None else None
        if isinstance(cached, bytes):
            if cached:
                result[url] = cached
        else:
            missing.append(url)

    if not missing:
        return result

    # Query rendering is latency-sensitive. Decorative CDN fetches therefore
    # leave the request critical path by default: render immediately with local
    # assets/placeholders and refresh misses in the background. Business/query
    # data freshness is unaffected because it is fetched before rendering.
    should_block = (
        _env_bool("IMAGE_ASSET_BLOCKING_FETCH_ENABLED", False)
        if blocking_network is None
        else bool(blocking_network)
    )
    if not should_block:
        for url in missing:
            _schedule_image_refresh(cache, url)
        return result

    # Explicit blocking mode remains available for maintenance tools and tests.
    request_timeout = min(
        max(0.25, float(timeout)),
        _env_float("IMAGE_ASSET_TIMEOUT_SECONDS", 1.5, 0.25, 5.0),
    )
    total_budget = overall_timeout
    if total_budget is None:
        total_budget = _env_float("IMAGE_ASSET_PREFETCH_BUDGET_SECONDS", 4.5, 0.5, 12.0)
    else:
        total_budget = max(0.1, float(total_budget))

    workers = max(1, min(max_workers, len(missing)))
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=workers)
    future_map = {
        executor.submit(download_image_cached, cache, url, request_timeout): url
        for url in missing
    }
    try:
        done, pending = concurrent.futures.wait(
            tuple(future_map),
            timeout=total_budget,
            return_when=concurrent.futures.ALL_COMPLETED,
        )
        for future in done:
            url = future_map[future]
            try:
                content = future.result()
            except Exception:
                content = None
            if isinstance(content, bytes) and content:
                result[url] = content

        # Blocking mode preserves the old short-circuit behavior after timeout.
        for future in pending:
            url = future_map[future]
            future.cancel()
            _cache_image_result(cache, f"image_asset:{url}", NEGATIVE_IMAGE_CACHE_VALUE)
    finally:
        try:
            executor.shutdown(wait=False, cancel_futures=True)
        except TypeError:
            executor.shutdown(wait=False)
    return result


def encode_png_limited(
    image: Any,
    *,
    max_bytes: Optional[int] = None,
    max_width: Optional[int] = None,
    max_height: Optional[int] = None,
) -> bytes:
    from PIL import Image

    limits = image_limits()
    target_bytes = max_bytes or limits["max_bytes"]
    width_limit = max_width or limits["max_width"]
    height_limit = max_height or limits["max_height"]

    working = image.convert("RGB")
    scale = min(1.0, width_limit / max(working.width, 1), height_limit / max(working.height, 1))
    if scale < 1.0:
        working = working.resize(
            (max(1, int(working.width * scale)), max(1, int(working.height * scale))),
            Image.Resampling.LANCZOS,
        )

    compress_level = _env_int("IMAGE_PNG_COMPRESS_LEVEL", 3, 0, 9)
    optimize = _env_bool("IMAGE_PNG_OPTIMIZE", False)

    def save_png(candidate: Any) -> bytes:
        buffer = io.BytesIO()
        candidate.save(
            buffer,
            format="PNG",
            optimize=optimize,
            compress_level=compress_level,
        )
        return buffer.getvalue()

    # The online path favors a small number of fast encodes. The old level-9
    # optimized encoder repeatedly tried many palettes/resizes, saving bandwidth
    # at the cost of request CPU time.
    best = save_png(working)
    if len(best) <= target_bytes:
        return best

    palette_adaptive = getattr(getattr(Image, "Palette", Image), "ADAPTIVE", 1)
    dither_none = getattr(getattr(Image, "Dither", Image), "NONE", 0)

    def try_palette(candidate: Any, colors: int) -> bytes:
        palette_image = candidate.convert(
            "P",
            palette=palette_adaptive,
            colors=colors,
            dither=dither_none,
        )
        return save_png(palette_image)

    for colors in (192, 128):
        encoded = try_palette(working, colors)
        if len(encoded) < len(best):
            best = encoded
        if len(encoded) <= target_bytes:
            return encoded

    resized = working
    while len(best) > target_bytes and (resized.width > 360 or resized.height > 420):
        ratio = max(0.62, min(0.88, (target_bytes / max(len(best), 1)) ** 0.5 * 0.96))
        next_width = max(360, int(resized.width * ratio))
        next_height = max(420, int(resized.height * ratio))
        if (next_width, next_height) == resized.size:
            break
        resized = resized.resize((next_width, next_height), Image.Resampling.BILINEAR)
        for colors in (96, 64):
            encoded = try_palette(resized, colors)
            if len(encoded) < len(best):
                best = encoded
            if len(encoded) <= target_bytes:
                return encoded

    # At the minimum practical dimensions, reduce palette depth only as far as
    # necessary to keep the existing hard byte ceiling contract.
    if len(best) > target_bytes:
        for colors in (48, 32, 24, 16):
            encoded = try_palette(resized, colors)
            if len(encoded) < len(best):
                best = encoded
            if len(encoded) <= target_bytes:
                return encoded
    return best
