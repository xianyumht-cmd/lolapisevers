import os
from typing import Any, List


def load_image_font(size: int, bold: bool = False):
    try:
        from PIL import ImageFont

        candidates = [
            r"C:\Windows\Fonts\msyhbd.ttc" if bold else r"C:\Windows\Fonts\msyh.ttc",
            r"C:\Windows\Fonts\simhei.ttf",
            r"C:\Windows\Fonts\arial.ttf",
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
