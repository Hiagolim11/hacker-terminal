"""The Quake-style drop-down window (hacker-terminal --dropdown)."""

from __future__ import annotations

from ..dropdown import geometry as dropdown_geometry
from ..runtime import GLib, Gdk, GdkX11, Gtk


class DropdownMixin:
    """Part of HackerTerminal: the Quake-style drop-down window (hacker-terminal --dropdown)."""

    def setup_dropdown(self) -> None:
        self.set_title("Hacker Terminal (suspenso)")
        self.set_decorated(False)
        self.set_keep_above(True)
        self.set_skip_taskbar_hint(True)
        self.set_skip_pager_hint(True)
        self.stick()
        self.get_style_context().add_class("dropdown")
        self.connect("focus-out-event", self.on_dropdown_focus_out)
        # Follow resolution and monitor changes while it is on screen.
        screen = self.get_screen()
        if screen is not None:
            screen.connect("monitors-changed", lambda *_: self.place_dropdown_if_visible())
            screen.connect("size-changed", lambda *_: self.place_dropdown_if_visible())

    def dropdown_area(self) -> tuple[int, int, int, int]:
        """Work area of the monitor under the pointer (multi-monitor aware)."""
        display = Gdk.Display.get_default()
        monitor = None
        seat = display.get_default_seat() if display is not None else None
        if seat is not None and seat.get_pointer() is not None:
            _screen, x, y = seat.get_pointer().get_position()
            monitor = display.get_monitor_at_point(x, y)
        if monitor is None and display is not None:
            monitor = display.get_primary_monitor() or display.get_monitor(0)
        if monitor is None:
            return 0, 0, 1280, 800
        area = monitor.get_workarea()
        return area.x, area.y, area.width, area.height

    def toggle_dropdown(self) -> None:
        if self.get_visible() and self.is_active():
            self.save_session()
            self.hide()
            return
        self.place_dropdown()
        self.show()
        self.place_dropdown()
        # Activated from a global shortcut, the window manager may refuse
        # focus to a plain present(); the X server time counts as user action.
        timestamp = Gtk.get_current_event_time()
        window = self.get_window()
        if not timestamp and GdkX11 is not None and isinstance(window, GdkX11.X11Window):
            timestamp = GdkX11.x11_get_server_time(window)
        self.present_with_time(timestamp or Gdk.CURRENT_TIME)
        pane = self.get_active_terminal()
        if pane is not None:
            pane.terminal.grab_focus()

    def place_dropdown(self) -> None:
        x, y, width, height = dropdown_geometry(self.dropdown_area(), self.preferences.dropdown_height)
        self.resize(width, height)
        self.move(x, y)

    def place_dropdown_if_visible(self) -> None:
        if self.dropdown and self.get_visible() and not self.closing_window:
            self.place_dropdown()

    def on_dropdown_focus_out(self, *_args) -> bool:
        if self.preferences.dropdown_autohide:
            # Deferred: a dialog of our own taking focus must not hide us.
            GLib.timeout_add(200, self.autohide_dropdown)
        return False

    def autohide_dropdown(self) -> bool:
        own_dialog = any(
            window.get_visible() and window.get_transient_for() is self for window in Gtk.Window.list_toplevels()
        )
        if self.get_visible() and not self.is_active() and not own_dialog and not self.closing_window:
            self.save_session()
            self.hide()
        return False
