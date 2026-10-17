"""Background image behind the terminal text.

VTE is told not to clear its background (set_clear_background(False)); the
pane paints the theme's background colour and then the image at the chosen
opacity, and VTE draws the text and coloured cells on top. Effects (rain,
scanlines, CRT) still draw last, over everything.
"""

from __future__ import annotations

import logging
from pathlib import Path

LOGGER = logging.getLogger(__name__)
FITS = ("cover", "contain", "tile")
FIT_LABELS = (("cover", "Preencher"), ("contain", "Ajustar"), ("tile", "Lado a lado"))
MAX_SIDE = 3840  # larger images are scaled down once on load
_loaded: dict[tuple[str, float], object] = {}  # (path, mtime) -> Pixbuf, shared by every pane
_warned: set[str] = set()  # paths already reported, once instead of once per pane


def _warn(path: str, message: str) -> None:
    if path not in _warned:
        _warned.add(path)
        LOGGER.warning(message)


def placement(image: tuple[int, int], area: tuple[int, int], fit: str) -> tuple[float, float, float]:
    """(scale, x, y) that draws an image of size ``image`` into ``area``.

    cover fills the area and crops the overflow evenly; contain shows the
    whole image centred; tile keeps the natural size from the top-left.
    """
    width, height = image
    area_width, area_height = area
    if fit == "tile" or width <= 0 or height <= 0:
        return 1.0, 0.0, 0.0
    choose = max if fit == "cover" else min
    scale = choose(area_width / width, area_height / height)
    return scale, (area_width - width * scale) / 2, (area_height - height * scale) / 2


def load(path: str):
    """The image as a Pixbuf, or None (logged) when it cannot be read."""
    import gi

    gi.require_version("GdkPixbuf", "2.0")
    from gi.repository import GdkPixbuf, GLib

    source = Path(path).expanduser()
    try:
        key = (str(source), source.stat().st_mtime)
    except OSError as error:
        _warn(str(source), f"imagem de fundo indisponível: {error}")
        return None
    if key in _loaded:
        return _loaded[key]
    try:
        pixbuf = GdkPixbuf.Pixbuf.new_from_file(str(source))
        pixbuf = pixbuf.apply_embedded_orientation() or pixbuf
    except GLib.Error as error:
        _warn(str(source), f"imagem de fundo ilegível ({source}): {error.message}")
        return None
    largest = max(pixbuf.get_width(), pixbuf.get_height())
    if largest > MAX_SIDE:
        factor = MAX_SIDE / largest
        pixbuf = pixbuf.scale_simple(
            max(1, round(pixbuf.get_width() * factor)), max(1, round(pixbuf.get_height() * factor)),
            GdkPixbuf.InterpType.BILINEAR,
        )
    _loaded.clear()  # one background at a time: drop the previous image
    _loaded[key] = pixbuf
    _warned.discard(str(source))
    return pixbuf


class BackgroundPainter:
    """Paints colour + image for one pane, caching the scaled image per size."""

    def __init__(self) -> None:
        self.pixbuf = None
        self.scaled = None
        self.cache_key: tuple | None = None

    def set_image(self, pixbuf) -> None:
        if pixbuf is not self.pixbuf:
            self.pixbuf = pixbuf
            self.scaled, self.cache_key = None, None

    def paint(self, cr, width: int, height: int, color: tuple[float, float, float, float],
              opacity: float, fit: str, area: tuple[int, int] | None = None,
              offset: tuple[int, int] = (0, 0)) -> None:
        """Fill ``width`` x ``height``; the image is laid out over ``area``.

        Split panes pass the whole tab as ``area`` and their own position as
        ``offset``, so the picture continues across the split.
        """
        from gi.repository import Gdk, GdkPixbuf

        import cairo

        cr.save()
        cr.set_operator(cairo.OPERATOR_SOURCE)
        cr.set_source_rgba(*color)
        cr.paint()
        cr.set_operator(cairo.OPERATOR_OVER)
        area_width, area_height = area or (width, height)
        if self.pixbuf is not None and opacity > 0 and area_width > 1 and area_height > 1:
            image = (self.pixbuf.get_width(), self.pixbuf.get_height())
            scale, x, y = placement(image, (area_width, area_height), fit)
            x, y = x - offset[0], y - offset[1]
            key = (area_width, area_height, fit)
            if key != self.cache_key:
                if fit == "tile":
                    self.scaled = self.pixbuf
                else:
                    self.scaled = self.pixbuf.scale_simple(
                        max(1, round(image[0] * scale)), max(1, round(image[1] * scale)),
                        GdkPixbuf.InterpType.BILINEAR,
                    )
                self.cache_key = key
            cr.rectangle(0, 0, width, height)
            cr.clip()
            if fit == "tile":
                Gdk.cairo_set_source_pixbuf(cr, self.scaled, -offset[0], -offset[1])
                cr.get_source().set_extend(cairo.EXTEND_REPEAT)
            else:
                Gdk.cairo_set_source_pixbuf(cr, self.scaled, round(x), round(y))
            cr.paint_with_alpha(opacity * color[3])
        cr.restore()
