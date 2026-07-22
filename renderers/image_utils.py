import concurrent.futures
import io
import os
from typing import Any, Dict, Iterable, List, Optional


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
        current = value
        while current and draw.textbbox((0, 0), current + ellipsis, font=font)[2] > max_width:
            current = current[:-1]
        return (current + ellipsis) if current else ellipsis
    except Exception:
        return value[: max(max_width // 12, 1)]


def _env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(str(os.getenv(name, default)).strip())
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(value, maximum))


def image_brand() -> str:
    return str(os.getenv("IMAGE_BRAND", "LOLApiServers")).strip() or "LOLApiServers"


def image_watermark() -> str:
    default = f"{image_brand()} · xianyumht-cmd"
    return str(os.getenv("IMAGE_WATERMARK", default)).strip() or default


def image_limits() -> Dict[str, int]:
    return {
        "max_bytes": _env_int("IMAGE_MAX_BYTES", 760_000, 180_000, 2_000_000),
        "max_width": _env_int("IMAGE_MAX_WIDTH", 1080, 640, 1920),
        "max_height": _env_int("IMAGE_MAX_HEIGHT", 1800, 720, 3200),
    }


def download_image_cached(cache: Any, url: str, timeout: float = 4.0) -> Optional[bytes]:
    url = str(url or "").strip()
    if not url:
        return None
    cache_key = f"image_asset:{url}"
    if cache is not None:
        cached = cache.get(cache_key)
        if isinstance(cached, bytes):
            return cached
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
            return None
        if content_type and "image" not in content_type:
            return None
        if cache is not None:
            cache.set(cache_key, content)
        return content
    except Exception:
        return None


def prefetch_image_urls(
    cache: Any,
    urls: Iterable[str],
    *,
    timeout: float = 4.0,
    max_workers: int = 8,
    max_assets: int = 72,
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

    result: Dict[str, bytes] = {}
    missing: List[str] = []
    for url in unique:
        cached = cache.get(f"image_asset:{url}") if cache is not None else None
        if isinstance(cached, bytes):
            result[url] = cached
        else:
            missing.append(url)

    if not missing:
        return result

    workers = max(1, min(max_workers, len(missing)))
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        future_map = {
            executor.submit(download_image_cached, cache, url, timeout): url
            for url in missing
        }
        for future in concurrent.futures.as_completed(future_map):
            url = future_map[future]
            try:
                content = future.result()
            except Exception:
                content = None
            if isinstance(content, bytes):
                result[url] = content
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

    def save_png(candidate: Any) -> bytes:
        buffer = io.BytesIO()
        candidate.save(buffer, format="PNG", optimize=True, compress_level=9)
        return buffer.getvalue()

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

    for colors in (192, 160, 128, 96, 64):
        encoded = try_palette(working, colors)
        if len(encoded) < len(best):
            best = encoded
        if len(encoded) <= target_bytes:
            return encoded

    resized = working
    while resized.width > 680 and resized.height > 760:
        resized = resized.resize(
            (max(680, int(resized.width * 0.92)), max(760, int(resized.height * 0.92))),
            Image.Resampling.LANCZOS,
        )
        for colors in (96, 64):
            encoded = try_palette(resized, colors)
            if len(encoded) < len(best):
                best = encoded
            if len(encoded) <= target_bytes:
                return encoded
        if resized.width <= 680 or resized.height <= 760:
            break

    # Highly detailed screenshots can remain large even after normal palette
    # compression. Continue with adaptive downscaling so the byte ceiling is a
    # real upper bound rather than a best-effort hint.
    while len(best) > target_bytes and (resized.width > 360 or resized.height > 420):
        ratio = max(0.62, min(0.88, (target_bytes / max(len(best), 1)) ** 0.5 * 0.95))
        next_width = max(360, int(resized.width * ratio))
        next_height = max(420, int(resized.height * ratio))
        if (next_width, next_height) == resized.size:
            break
        resized = resized.resize((next_width, next_height), Image.Resampling.BILINEAR)
        for colors in (64, 48, 32, 24, 16):
            encoded = try_palette(resized, colors)
            if len(encoded) < len(best):
                best = encoded
            if len(encoded) <= target_bytes:
                return encoded
    return best
