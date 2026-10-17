"""Draw an image in the terminal output with true-color half blocks.

Each character cell shows two pixels stacked: "▀" painted with the top
pixel as foreground and the bottom one as background. It works in any
true-color terminal, unlike sixel, which many VTE builds leave out.
Transparent pixels keep the terminal's own background, so images look
right on light and dark themes.
"""

from __future__ import annotations

from typing import Callable

Pixel = tuple[int, int, int, int]  # red, green, blue, alpha
OPAQUE = 128  # alpha from which a pixel is drawn
RESET = "\x1b[0m"


def fit(width: int, height: int, columns: int, rows: int) -> tuple[int, int]:
    """Pixel size that fits ``columns`` x ``rows`` cells (two pixels per cell, upright)."""
    columns, rows = max(1, columns), max(1, rows)
    scale = min(1.0, columns / width, (rows * 2) / height)
    new_width = max(1, round(width * scale))
    new_height = max(2, round(height * scale))
    return new_width, new_height + new_height % 2  # whole cells


def cell(top: Pixel, bottom: Pixel) -> tuple[str | None, str | None, str]:
    """(foreground, background, character); None background keeps the terminal's."""
    top_on, bottom_on = top[3] >= OPAQUE, bottom[3] >= OPAQUE
    if top_on and bottom_on:
        return f"38;2;{top[0]};{top[1]};{top[2]}", f"48;2;{bottom[0]};{bottom[1]};{bottom[2]}", "▀"
    if top_on:
        return f"38;2;{top[0]};{top[1]};{top[2]}", None, "▀"
    if bottom_on:
        return f"38;2;{bottom[0]};{bottom[1]};{bottom[2]}", None, "▄"
    return None, None, " "


def render(width: int, height: int, pixel: Callable[[int, int], Pixel]) -> str:
    """Lines of half-block cells for a ``width`` x ``height`` image.

    Color codes are written only when they change, which keeps the output
    (and the scrollback it fills) several times smaller.
    """
    lines = []
    transparent = (0, 0, 0, 0)
    for y in range(0, height, 2):
        parts: list[str] = []
        foreground = background = "unset"
        for x in range(width):
            new_fg, new_bg, char = cell(pixel(x, y), pixel(x, y + 1) if y + 1 < height else transparent)
            codes = []
            if new_bg != background:
                codes.append(new_bg or "49")
                background = new_bg
            if new_fg is not None and new_fg != foreground:
                codes.append(new_fg)
                foreground = new_fg
            if codes:
                parts.append(f"\x1b[{';'.join(codes)}m")
            parts.append(char)
        lines.append("".join(parts) + RESET)
    return "\n".join(lines) + "\n"


def render_file(path: str, columns: int, rows: int) -> str:
    """Load any image GdkPixbuf reads (PNG, JPEG, GIF, WebP, SVG...) and render it."""
    import gi

    gi.require_version("GdkPixbuf", "2.0")
    from gi.repository import GdkPixbuf

    animation = GdkPixbuf.PixbufAnimation.new_from_file(path)
    source = animation.get_static_image() or GdkPixbuf.Pixbuf.new_from_file(path)
    source = source.apply_embedded_orientation() or source
    width, height = fit(source.get_width(), source.get_height(), columns, rows)
    scaled = source.scale_simple(width, height, GdkPixbuf.InterpType.BILINEAR)
    if not scaled.get_has_alpha():
        scaled = scaled.add_alpha(False, 0, 0, 0)
    data = scaled.get_pixels()
    stride = scaled.get_rowstride()

    def pixel(x: int, y: int) -> Pixel:
        offset = y * stride + x * 4
        return data[offset], data[offset + 1], data[offset + 2], data[offset + 3]

    return render(width, height, pixel)
