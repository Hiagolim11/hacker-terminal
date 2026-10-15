"""Low-cost decorative terminal effects."""

from __future__ import annotations

import random

from .themes import Theme
from .runtime import GLib, Gtk


class EffectsLayer(Gtk.DrawingArea):
    def __init__(self) -> None:
        super().__init__()
        self.enabled = True
        self.running = True
        self.columns: list[dict[str, float]] = []
        self.last_width = 0
        self.matrix_rgb = (0.08, 1.0, 0.55)
        self.scanline_opacity = 0.12
        self.connect("draw", self.on_draw)
        self.source_id = 0
        self.connect("destroy", self.on_destroy)
        self.start_timer()

    def start_timer(self) -> None:
        if not self.source_id and self.running:
            self.source_id = GLib.timeout_add(75, self.tick)

    def tick(self) -> bool:
        # The timer only lives while effects are on, so disabled panes stay idle.
        if self.running and self.enabled:
            self.queue_draw()
            return True
        self.source_id = 0
        return False

    def on_destroy(self, _widget) -> None:
        self.running = False
        if self.source_id:
            GLib.source_remove(self.source_id)
            self.source_id = 0

    def set_enabled(self, enabled: bool) -> None:
        self.enabled = enabled
        self.set_no_show_all(not enabled)
        self.set_visible(enabled)
        if enabled:
            self.start_timer()

    def apply_theme(self, theme: Theme) -> None:
        value = theme.matrix_color.lstrip("#")
        self.matrix_rgb = tuple(int(value[index:index + 2], 16) / 255 for index in (0, 2, 4))
        self.scanline_opacity = theme.scanline_opacity
        self.queue_draw()

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

    def on_draw(self, _widget, context) -> bool:
        if not self.enabled:
            return False
        width, height = self.get_allocated_width(), self.get_allocated_height()
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
                context.set_source_rgba(
                    *self.matrix_rgb,
                    max(0.0, 0.055 - trail * 0.008),
                )
                context.move_to(column["x"], column["y"] - trail * 17)
                context.show_text(random.choice("01ABCDEF"))
        context.set_line_width(1)
        context.set_source_rgba(0, 0, 0, self.scanline_opacity)
        for y_position in range(0, height, 4):
            context.move_to(0, y_position + 0.5)
            context.line_to(width, y_position + 0.5)
        context.stroke()
        return False
