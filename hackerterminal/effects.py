"""Low-cost decorative terminal effects: digital rain and a CRT screen look."""

from __future__ import annotations

import logging
import math
import os
import random

from .themes import Theme
from .runtime import HAS_CAIRO, GLib, Gtk

if HAS_CAIRO:
    import cairo
else:  # pragma: no cover - effects are disabled without the cairo bindings
    cairo = None

LOGGER = logging.getLogger(__name__)
FRAME_MS = 75
NOISE_TILE = 160
NOISE_VARIANTS = 4
_noise_tiles: list = []


def _hex_rgb(value: str) -> tuple[float, float, float]:
    value = value.lstrip("#")
    return tuple(int(value[index:index + 2], 16) / 255 for index in (0, 2, 4))


def noise_tiles() -> list:
    """A few grain textures, generated once per process and reused by every pane."""
    if not _noise_tiles:
        stride = cairo.ImageSurface.format_stride_for_width(cairo.FORMAT_ARGB32, NOISE_TILE)
        for _ in range(NOISE_VARIANTS):
            data = bytearray(stride * NOISE_TILE)
            grain = os.urandom(NOISE_TILE * NOISE_TILE)
            for index, value in enumerate(grain):
                # Sparse premultiplied light specks; most pixels stay clear.
                alpha = value if value > 150 else 0
                offset = (index // NOISE_TILE) * stride + (index % NOISE_TILE) * 4
                data[offset:offset + 4] = bytes((alpha, alpha, alpha, alpha))
            _noise_tiles.append(
                cairo.ImageSurface.create_for_data(data, cairo.FORMAT_ARGB32, NOISE_TILE, NOISE_TILE, stride)
            )
    return _noise_tiles


class EffectsLayer:
    """Paint effects on top of a widget's own drawing.

    The effects used to live in a Gtk.Overlay child. On X11 that child owns a
    GdkWindow which swallowed scroll events even with pass-through enabled, so
    two-finger touchpad scrolling stopped working whenever effects were on.
    Drawing after the target keeps every input event on the terminal itself.

    Static parts (glow, scanlines, vignette, tube curvature) are rendered once
    per size and theme into cached surfaces; each frame only blits them and
    adds the animated parts (rain, static, flicker). Themes without animated
    parts run no timer at all.
    """

    def __init__(self, target: Gtk.Widget) -> None:
        self.target = target
        self.enabled = False
        self.running = True
        self.source_id = 0
        self.columns: list[dict[str, float]] = []
        self.last_width = 0
        self.theme: Theme | None = None
        self.matrix_rgb = (0.08, 1.0, 0.55)
        self.scanline_opacity = 0.12
        self.draw_handler = 0
        self.cache_key: tuple | None = None
        self.light_layer = None
        self.shade_layer = None
        target.connect("destroy", self.on_destroy)

    # ---------------------------------------------------------------- state

    @property
    def animated(self) -> bool:
        return self.theme.animated if self.theme is not None else True

    def start_timer(self) -> None:
        if not self.source_id and self.running and self.enabled and self.animated:
            self.source_id = GLib.timeout_add(FRAME_MS, self.tick)

    def stop_timer(self) -> None:
        if self.source_id:
            GLib.source_remove(self.source_id)
            self.source_id = 0

    def tick(self) -> bool:
        # The timer only lives while animated effects are on.
        if self.running and self.enabled and self.animated:
            self.target.queue_draw()
            return True
        self.source_id = 0
        return False

    def on_destroy(self, _widget) -> None:
        self.running = False
        self.stop_timer()
        self.light_layer = self.shade_layer = None

    def set_enabled(self, enabled: bool) -> None:
        if enabled and not HAS_CAIRO:
            LOGGER.warning("efeitos visuais indisponíveis: instale python3-gi-cairo")
            enabled = False
        if enabled == self.enabled:
            return
        self.enabled = enabled
        # Only hook the terminal's drawing while effects are on, so a plain
        # terminal never pays for (or depends on) the cairo bindings.
        if enabled and not self.draw_handler:
            self.draw_handler = self.target.connect_after("draw", self.on_draw)
        elif not enabled and self.draw_handler:
            self.target.disconnect(self.draw_handler)
            self.draw_handler = 0
        if enabled:
            self.start_timer()
        else:
            self.stop_timer()
            self.light_layer = self.shade_layer = None
            self.cache_key = None
        self.target.queue_draw()

    def apply_theme(self, theme: Theme) -> None:
        self.theme = theme
        self.matrix_rgb = _hex_rgb(theme.matrix_color)
        self.scanline_opacity = theme.scanline_opacity
        self.cache_key = None
        if self.animated:
            self.start_timer()
        else:
            self.stop_timer()
        self.target.queue_draw()

    # ---------------------------------------------------------- static layers

    def _ensure_layers(self, width: int, height: int) -> None:
        theme = self.theme
        key = (width, height, theme)
        if key == self.cache_key:
            return
        self.cache_key = key
        self.light_layer = self._render_light(width, height, theme) if theme and theme.glow else None
        self.shade_layer = self._render_shade(width, height, theme)

    @staticmethod
    def _render_light(width: int, height: int, theme: Theme):
        """Phosphor glow: light emitted from the middle of the tube."""
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
        context = cairo.Context(surface)
        red, green, blue = _hex_rgb(theme.terminal_foreground)
        radius = math.hypot(width, height) / 2
        gradient = cairo.RadialGradient(width / 2, height / 2, 0, width / 2, height / 2, radius)
        strength = 0.16 * theme.glow
        gradient.add_color_stop_rgba(0.0, red, green, blue, strength)
        gradient.add_color_stop_rgba(0.55, red, green, blue, strength * 0.45)
        gradient.add_color_stop_rgba(1.0, red, green, blue, 0)
        context.set_source(gradient)
        context.paint()
        return surface

    def _render_shade(self, width: int, height: int, theme: Theme | None):
        """Everything that darkens: scanlines, vignette and tube curvature."""
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
        context = cairo.Context(surface)
        if self.scanline_opacity > 0:
            context.set_line_width(1)
            context.set_source_rgba(0, 0, 0, self.scanline_opacity)
            spacing = 3 if theme is not None and theme.scanline_opacity >= 0.2 else 4
            for y_position in range(0, height, spacing):
                context.move_to(0, y_position + 0.5)
                context.line_to(width, y_position + 0.5)
            context.stroke()
        if theme is None:
            return surface
        if theme.vignette:
            # Elliptical: darken toward the edges of the screen, not a circle.
            context.save()
            context.translate(width / 2, height / 2)
            context.scale(width / 2, height / 2)
            gradient = cairo.RadialGradient(0, 0, 0.35, 0, 0, 1.45)
            gradient.add_color_stop_rgba(0.0, 0, 0, 0, 0)
            gradient.add_color_stop_rgba(0.6, 0, 0, 0, 0.35 * theme.vignette)
            gradient.add_color_stop_rgba(1.0, 0, 0, 0, 0.85 * theme.vignette)
            context.set_source(gradient)
            context.paint()
            context.restore()
        if theme.curvature:
            self._render_tube(context, width, height, theme)
        return surface

    @staticmethod
    def _render_tube(context, width: int, height: int, theme: Theme) -> None:
        """Rounded tube corners, an inner bezel shadow and a faint reflection."""
        radius = min(theme.tube_radius, min(width, height) / 2)
        red, green, blue = (value * 0.35 for value in _hex_rgb(theme.terminal_background))
        # Fill outside a rounded rectangle: the bezel hiding the tube corners.
        context.save()
        context.new_path()
        context.rectangle(0, 0, width, height)
        context.new_sub_path()
        context.arc(radius, radius, radius, math.pi, 1.5 * math.pi)
        context.arc(width - radius, radius, radius, 1.5 * math.pi, 2 * math.pi)
        context.arc(width - radius, height - radius, radius, 0, 0.5 * math.pi)
        context.arc(radius, height - radius, radius, 0.5 * math.pi, math.pi)
        context.close_path()
        context.set_fill_rule(cairo.FILL_RULE_EVEN_ODD)
        context.set_source_rgb(red, green, blue)
        context.fill()
        context.restore()
        # Inner shadow along each edge, as if the glass curved away.
        depth = 6 + 22 * theme.curvature
        strength = 0.55 * theme.curvature
        for x0, y0, x1, y1 in ((0, 0, 0, depth), (0, height, 0, height - depth),
                               (0, 0, depth, 0), (width, 0, width - depth, 0)):
            gradient = cairo.LinearGradient(x0, y0, x1, y1)
            gradient.add_color_stop_rgba(0, 0, 0, 0, strength)
            gradient.add_color_stop_rgba(1, 0, 0, 0, 0)
            context.set_source(gradient)
            context.paint()
        # A soft reflection of the room on the glass, top left.
        glare = cairo.RadialGradient(width * 0.22, height * 0.12, 0, width * 0.22, height * 0.12, max(width, height) * 0.45)
        glare.add_color_stop_rgba(0, 1, 1, 1, 0.035 * theme.curvature)
        glare.add_color_stop_rgba(1, 1, 1, 1, 0)
        context.set_source(glare)
        context.paint()

    # --------------------------------------------------------------- drawing

    def rebuild(self, width: int, height: int) -> None:
        self.last_width = width
        count = max(1, width // 30)
        self.columns = [
            {
                "x": float(index * 30 + random.randint(0, 8)),
                "y": random.uniform(-height, 0),
                "speed": random.uniform(2, 6),
            }
            for index in range(count)
        ]

    def _draw_rain(self, context, width: int, height: int) -> None:
        if width != self.last_width or not self.columns:
            self.rebuild(width, height)
        context.select_font_face("monospace", 0, 0)
        context.set_font_size(10)
        for column in self.columns:
            column["y"] += column["speed"]
            if column["y"] > height + 80:
                column["y"] = random.uniform(-260, -20)
                column["speed"] = random.uniform(2, 6)
            for trail in range(6):
                context.set_source_rgba(*self.matrix_rgb, max(0.0, 0.055 - trail * 0.008))
                context.move_to(column["x"], column["y"] - trail * 17)
                context.show_text(random.choice("01ABCDEF"))

    def on_draw(self, widget, context) -> bool:
        if not self.enabled:
            return False
        width, height = widget.get_allocated_width(), widget.get_allocated_height()
        if width <= 0 or height <= 0:
            return False
        theme = self.theme
        context.save()
        if theme is None or theme.rain:
            self._draw_rain(context, width, height)
        self._ensure_layers(width, height)
        if self.light_layer is not None:
            context.set_operator(cairo.OPERATOR_SCREEN)  # light adds, never darkens
            context.set_source_surface(self.light_layer, 0, 0)
            context.paint()
            context.set_operator(cairo.OPERATOR_OVER)
        if theme is not None and theme.noise:
            tile = random.choice(noise_tiles())
            pattern = cairo.SurfacePattern(tile)
            pattern.set_extend(cairo.EXTEND_REPEAT)
            matrix = cairo.Matrix()
            matrix.translate(random.randrange(NOISE_TILE), random.randrange(NOISE_TILE))
            pattern.set_matrix(matrix)
            context.set_source(pattern)
            context.paint_with_alpha(0.22 * theme.noise)
        if self.shade_layer is not None:
            context.set_source_surface(self.shade_layer, 0, 0)
            context.paint()
        if theme is not None and theme.flicker:
            context.set_source_rgba(0, 0, 0, random.random() * 0.09 * theme.flicker)
            context.paint()
        context.restore()
        return False
