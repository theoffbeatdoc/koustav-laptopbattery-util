"""Programmatically generated battery icon (no image assets needed at runtime)."""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw

_SS = 4  # supersampling factor for smooth edges


def make_icon_image(size: int = 64, enabled: bool = True) -> Image.Image:
    s = size * _SS
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    fill = (63, 185, 80, 255) if enabled else (139, 148, 158, 255)
    rim = (240, 240, 240, 255)
    body = (38, 42, 48, 255)
    x0, y0, x1, y1 = (int(s * v) for v in (0.06, 0.24, 0.86, 0.76))
    w = max(2, s // 16)
    d.rounded_rectangle((x0, y0, x1, y1), radius=s // 10, fill=body, outline=rim, width=w)
    nx0, ny0, nx1, ny1 = (int(s * v) for v in (0.86, 0.40, 0.95, 0.60))
    d.rounded_rectangle((nx0, ny0, nx1, ny1), radius=s // 40, fill=rim)
    pad = w + s // 28
    level = 0.72
    fx1 = x0 + pad + int((x1 - x0 - 2 * pad) * level)
    d.rounded_rectangle((x0 + pad, y0 + pad, fx1, y1 - pad), radius=s // 20, fill=fill)
    if not enabled:
        d.line((int(s * 0.12), int(s * 0.88), int(s * 0.90), int(s * 0.12)),
               fill=(248, 81, 73, 255), width=max(3, s // 12))
    return img.resize((size, size), Image.LANCZOS)


def save_ico(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    make_icon_image(256).save(
        path, format="ICO", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])


if __name__ == "__main__":  # used by build.ps1:  python -m kbu.icon assets/icon.ico
    save_ico(Path(sys.argv[1] if len(sys.argv) > 1 else "icon.ico"))
