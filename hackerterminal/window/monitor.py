"""Resource monitor: one shared sampler, the status-bar summary and the panel section."""

from __future__ import annotations

import collections
import shutil
from typing import Callable

from ..runtime import Gdk, GLib, Gio, Gtk, Pango
from ..sysmon import (
    HOT_CELSIUS,
    NVIDIA_QUERY,
    STATUS_ITEMS,
    Snapshot,
    SystemReader,
    frequency,
    gigabytes,
    parse_nvidia_smi,
    status_groups,
)

INTERVAL_MS = 2000
HISTORY = 30  # one minute at INTERVAL_MS


class MonitorService:
    """Samples while at least one window listens; every window shares the readings."""

    _shared: "MonitorService | None" = None

    @classmethod
    def shared(cls) -> "MonitorService":
        if cls._shared is None:
            cls._shared = cls()
        return cls._shared

    def __init__(self, reader: SystemReader | None = None) -> None:
        self.reader = reader or SystemReader()
        self.listeners: list[Callable[[Snapshot], None]] = []
        self.source = 0
        self.latest: Snapshot | None = None
        self.history: dict[str, collections.deque] = {
            name: collections.deque(maxlen=HISTORY) for name in ("cpu", "ram", "gpu")
        }
        self.nvidia: list = []  # last nvidia-smi answer
        self.nvidia_running = False
        self.has_nvidia_smi = shutil.which("nvidia-smi") is not None

    def subscribe(self, listener: Callable[[Snapshot], None]) -> None:
        if listener in self.listeners:
            return
        self.listeners.append(listener)
        if not self.source:
            self.reader.sample()  # first reading: CPU load needs two
            self.source = GLib.timeout_add(INTERVAL_MS, self.tick)
            GLib.timeout_add(400, self.tick_once)  # something to show right away
        elif self.latest is not None:
            listener(self.latest)

    def unsubscribe(self, listener: Callable[[Snapshot], None]) -> None:
        if listener in self.listeners:
            self.listeners.remove(listener)
        if not self.listeners and self.source:
            GLib.source_remove(self.source)
            self.source = 0

    @property
    def running(self) -> bool:
        return bool(self.source)

    def tick_once(self) -> bool:
        if self.source:
            self.tick()
        return False

    def tick(self) -> bool:
        snapshot = self.reader.sample()
        if any(gpu.driver == "nvidia" for gpu in snapshot.gpus) and self.has_nvidia_smi:
            snapshot.gpus = [gpu for gpu in snapshot.gpus if gpu.driver != "nvidia"] + self.nvidia
            self.query_nvidia()
        self.latest = snapshot
        self.history["cpu"].append(snapshot.cpu_percent)
        self.history["ram"].append(100 * snapshot.ram_fraction if snapshot.ram_fraction is not None else None)
        gpu = snapshot.gpu
        if gpu is not None and gpu.busy is not None:
            self.history["gpu"].append(gpu.busy)
        elif gpu is not None and gpu.mhz is not None and gpu.max_mhz:
            self.history["gpu"].append(100 * gpu.mhz / gpu.max_mhz)  # Intel: the clock is the only sign of load
        else:
            self.history["gpu"].append(None)
        for listener in list(self.listeners):
            listener(snapshot)
        return True

    def query_nvidia(self) -> None:
        # Out of process and asynchronous: nvidia-smi takes tens of milliseconds.
        if self.nvidia_running:
            return
        try:
            process = Gio.Subprocess.new(NVIDIA_QUERY, Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_SILENCE)
        except GLib.Error:
            self.has_nvidia_smi = False
            return
        self.nvidia_running = True

        def finished(proc, result) -> None:
            self.nvidia_running = False
            try:
                _ok, output, _error = proc.communicate_utf8_finish(result)
            except GLib.Error:
                return
            self.nvidia = parse_nvidia_smi(output or "")

        process.communicate_utf8_async(None, None, finished)


class Sparkline(Gtk.DrawingArea):
    """The last minute of a 0–100 value, drawn in the theme's accent colour."""

    def __init__(self, height: int = 24) -> None:
        super().__init__()
        self.values: list[float | None] = []
        self.set_size_request(-1, height)
        self.get_style_context().add_class("monitor-graph")
        self.connect("draw", self.on_draw)

    def set_values(self, values) -> None:
        self.values = list(values)
        self.queue_draw()

    def on_draw(self, _widget, cr) -> bool:
        width, height = self.get_allocated_width(), self.get_allocated_height()
        context = self.get_style_context()
        color = context.get_color(context.get_state())
        cr.set_source_rgba(color.red, color.green, color.blue, 0.18)
        cr.rectangle(0, height - 1, width, 1)  # baseline
        cr.fill()
        points = [(index, value) for index, value in enumerate(self.values) if value is not None]
        if len(points) < 2:
            return False
        step = width / (HISTORY - 1)
        offset = (HISTORY - len(self.values)) * step  # newest at the right edge

        def xy(index: int, value: float) -> tuple[float, float]:
            return offset + index * step, height - 1 - (height - 3) * max(0.0, min(100.0, value)) / 100

        cr.move_to(xy(*points[0])[0], height)
        for point in points:
            cr.line_to(*xy(*point))
        cr.line_to(xy(*points[-1])[0], height)
        cr.close_path()
        cr.set_source_rgba(color.red, color.green, color.blue, 0.16)
        cr.fill()
        cr.set_line_width(1.5)
        cr.move_to(*xy(*points[0]))
        for point in points[1:]:
            cr.line_to(*xy(*point))
        cr.set_source_rgba(color.red, color.green, color.blue, 0.95)
        cr.stroke()
        return False


class CoreBars(Gtk.DrawingArea):
    """One thin bar per CPU core."""

    def __init__(self) -> None:
        super().__init__()
        self.loads: list[float] = []
        self.set_size_request(-1, 14)
        self.get_style_context().add_class("monitor-graph")
        self.connect("draw", self.on_draw)

    def set_loads(self, loads: list[float]) -> None:
        self.loads = loads
        self.set_tooltip_text("  ".join(f"{index}: {load:.0f}%" for index, load in enumerate(loads)) or None)
        self.queue_draw()

    def on_draw(self, _widget, cr) -> bool:
        if not self.loads:
            return False
        width, height = self.get_allocated_width(), self.get_allocated_height()
        context = self.get_style_context()
        color = context.get_color(context.get_state())
        gap = 2
        bar = (width - gap * (len(self.loads) - 1)) / len(self.loads)
        for index, load in enumerate(self.loads):
            x = index * (bar + gap)
            cr.set_source_rgba(color.red, color.green, color.blue, 0.16)
            cr.rectangle(x, 0, bar, height)
            cr.fill()
            filled = height * max(0.0, min(100.0, load)) / 100
            cr.set_source_rgba(color.red, color.green, color.blue, 0.9)
            cr.rectangle(x, height - filled, bar, filled)
            cr.fill()
        return False


class MonitorSection(Gtk.Box):
    """The "Sistema" block at the top of the side panel."""

    def __init__(self) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.get_style_context().add_class("monitor-section")
        title = Gtk.Label(label="Sistema", xalign=0)
        title.get_style_context().add_class("panel-title")
        title.set_margin_start(4)
        title.set_margin_bottom(6)
        self.pack_start(title, False, False, 0)
        self.rows: dict[str, tuple[Gtk.Box, Gtk.Label, Gtk.Label]] = {}
        self.graphs: dict[str, Sparkline] = {}
        for key, name in (("cpu", "CPU"), ("ram", "Memória"), ("gpu", "GPU")):
            row = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
            row.get_style_context().add_class("monitor-row")
            line = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            label = Gtk.Label(label=name, xalign=0)
            label.get_style_context().add_class("monitor-name")
            value = Gtk.Label(label="…", xalign=1)
            value.set_ellipsize(Pango.EllipsizeMode.END)
            value.get_style_context().add_class("monitor-value")
            line.pack_start(label, False, False, 0)
            line.pack_end(value, True, True, 0)
            row.pack_start(line, False, False, 0)
            detail = Gtk.Label(label="", xalign=0)
            detail.set_ellipsize(Pango.EllipsizeMode.END)
            detail.get_style_context().add_class("monitor-detail")
            row.pack_start(detail, False, False, 0)
            graph = Sparkline()
            row.pack_start(graph, False, False, 0)
            if key == "cpu":
                self.cores = CoreBars()
                row.pack_start(self.cores, False, False, 0)
            self.pack_start(row, False, False, 0)
            self.rows[key] = (row, value, detail)
            self.graphs[key] = graph

    def update(self, snapshot: Snapshot, history: dict) -> None:
        row, value, detail = self.rows["cpu"]
        value.set_text(f"{snapshot.cpu_percent:.0f}%" if snapshot.cpu_percent is not None else "—")
        details = []
        if snapshot.cpu_mhz:
            details.append(frequency(snapshot.cpu_mhz) + (f" de {frequency(snapshot.cpu_max_mhz)}" if snapshot.cpu_max_mhz else ""))
        if snapshot.cpu_temp is not None:
            details.append(f"{snapshot.cpu_temp:.0f} °C")
        self.set_detail(detail, details, snapshot.cpu_temp is not None and snapshot.cpu_temp >= HOT_CELSIUS)
        self.cores.set_loads(snapshot.cores)
        self.graphs["cpu"].set_values(history["cpu"])

        row, value, detail = self.rows["ram"]
        fraction = snapshot.ram_fraction
        value.set_text(f"{100 * fraction:.0f}%" if fraction is not None else "—")
        details = []
        if snapshot.ram_used is not None and snapshot.ram_total:
            details.append(f"{gigabytes(snapshot.ram_used)} de {gigabytes(snapshot.ram_total)} GB")
        if snapshot.swap_total:
            details.append(f"swap {gigabytes(snapshot.swap_used or 0)} GB")
        self.set_detail(detail, details, "ram" in snapshot.alerts())
        self.graphs["ram"].set_values(history["ram"])

        row, value, detail = self.rows["gpu"]
        gpu = snapshot.gpu
        row.set_visible(gpu is not None)
        if gpu is not None:
            if gpu.busy is not None:
                value.set_text(f"{gpu.busy:.0f}%")
            else:
                value.set_text(frequency(gpu.mhz) if gpu.mhz is not None else "—")
            details = [gpu.name]
            if gpu.busy is not None and gpu.mhz is not None:
                details.append(frequency(gpu.mhz))
            elif gpu.max_mhz:
                details.append(f"máx. {frequency(gpu.max_mhz)}")
            if gpu.vram_used is not None and gpu.vram_total:
                details.append(f"VRAM {gigabytes(gpu.vram_used)}/{gigabytes(gpu.vram_total)} GB")
            if gpu.temp is not None:
                details.append(f"{gpu.temp:.0f} °C")
            self.set_detail(detail, details, gpu.temp is not None and gpu.temp >= HOT_CELSIUS)
            tooltip = None
            if gpu.driver in ("i915", "xe"):
                tooltip = ("Gráfico: clock em relação ao máximo. O uso em % e a memória de vídeo não existem "
                           "para gráficos integrados Intel sem permissão de administrador; eles usam a RAM do sistema.")
            row.set_tooltip_text(tooltip)
            self.graphs["gpu"].set_values(history["gpu"])

    @staticmethod
    def set_detail(label: Gtk.Label, parts: list[str], alert: bool) -> None:
        label.set_text(" · ".join(parts))
        context = label.get_style_context()
        (context.add_class if alert else context.remove_class)("monitor-alert")


class MonitorMixin:
    """The window's side: a clickable summary in the status bar, the panel
    section, and listening only while the window can be seen."""

    def build_monitor_status(self) -> Gtk.Widget:
        self.monitor_label = Gtk.Label(label="", xalign=1)
        self.monitor_label.get_style_context().add_class("status")
        self.monitor_label.get_style_context().add_class("monitor-status")
        box = Gtk.EventBox(visible_window=False)
        box.add(self.monitor_label)
        box.set_tooltip_text("Uso do sistema: clique para ver os detalhes no painel lateral")
        box.connect("button-press-event", lambda *_: self.show_monitor_details())
        self.monitor_status = box
        self.monitor_listening = False
        self.monitor_hidden = False  # minimized, or a dropdown pulled up
        self.connect("window-state-event", self.on_monitor_window_state)
        self.connect("map-event", lambda *_: self.set_monitor_hidden(False))
        self.connect("unmap-event", lambda *_: self.set_monitor_hidden(True))
        self.connect("destroy", lambda *_: self.stop_monitor())
        return box

    def apply_monitor(self) -> None:
        enabled = self.preferences.monitor
        self.monitor_status.set_no_show_all(not enabled)
        self.monitor_status.set_visible(enabled)
        if enabled:
            self.monitor_status.show_all()
        if self.action_panel is not None:
            self.action_panel.set_monitor_visible(enabled)
        wanted = enabled and not self.monitor_hidden and not getattr(self, "closing_window", False)
        service = MonitorService.shared()
        if wanted and not self.monitor_listening:
            self.monitor_listening = True
            service.subscribe(self.on_monitor_sample)
        elif not wanted and self.monitor_listening:
            self.stop_monitor()

    def stop_monitor(self) -> None:
        if getattr(self, "monitor_listening", False):
            self.monitor_listening = False
            MonitorService.shared().unsubscribe(self.on_monitor_sample)

    def set_monitor_hidden(self, hidden: bool) -> bool:
        if hidden != self.monitor_hidden:
            self.monitor_hidden = hidden
            self.apply_monitor()
        return False

    def on_monitor_window_state(self, _window, event) -> bool:
        self.set_monitor_hidden(bool(event.new_window_state & Gdk.WindowState.ICONIFIED))
        return False

    def on_monitor_sample(self, snapshot: Snapshot) -> None:
        if getattr(self, "closing_window", False):
            return
        items = [item for item in self.preferences.monitor_items.split(",") if item in STATUS_ITEMS]
        escape = GLib.markup_escape_text
        danger = self.active_theme.danger
        markup = "   ".join(
            f'<span foreground="{danger}">{escape(text)}</span>' if alert else escape(text)
            for text, alert in status_groups(snapshot, items)
        )
        if self.monitor_label.get_label() != markup:
            self.monitor_label.set_markup(markup)
        panel = self.action_panel
        if panel is not None and panel.get_mapped():
            panel.monitor_section.update(snapshot, MonitorService.shared().history)

    def show_monitor_details(self) -> bool:
        panel = self.action_panel
        if panel is None:
            return True
        if not panel.get_visible():
            self.toggle_panel()
        panel.scroller.get_vadjustment().set_value(0)  # the section sits at the top
        latest = MonitorService.shared().latest
        if latest is not None:
            panel.monitor_section.update(latest, MonitorService.shared().history)
        return True


__all__ = ["MonitorMixin", "MonitorService", "MonitorSection", "Sparkline", "CoreBars"]
