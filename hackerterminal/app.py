"""The Gtk.Application: one process for every plain window, notifications and ht-open routing."""

from __future__ import annotations

import logging
import signal
from pathlib import Path

from .actions import ActionStore
from .config import AppConfig, ConfigStore
from .constants import APP_ID
from .keysound import KeySoundEngine
from .openserver import OpenServer
from .profiles import ProfileManager
from .runtime import GLib, Gio, Gtk
from .session import SessionStore
from .themes import ThemeManager
from .window.main import HackerTerminal

LOGGER = logging.getLogger(__name__)


def report_error(command_line, message: str) -> None:
    """Print on the stderr of the command that asked for the window."""
    if hasattr(command_line, "printerr_literal"):  # GLib 2.80+
        command_line.printerr_literal(message)
    else:
        LOGGER.warning(message.strip())


class HackerTerminalApp(Gtk.Application):
    def __init__(
        self,
        config: AppConfig,
        store: ConfigStore,
        action_store: ActionStore,
        session_store: SessionStore,
        theme_manager: ThemeManager,
        profile_manager: ProfileManager,
        css_provider: Gtk.CssProvider,
        dropdown: bool = False,
        separate: bool = False,
    ) -> None:
        if dropdown:
            # Unique: running --dropdown again reaches this instance over
            # D-Bus and toggles its window instead of opening another.
            super().__init__(application_id=APP_ID + ".Dropdown", flags=Gio.ApplicationFlags.DEFAULT_FLAGS)
        elif separate:
            super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.NON_UNIQUE)
        else:
            # One process for every plain window: a new launch passes its
            # command line here (see launcher.py) and gets a window at once.
            super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        self.dropdown = dropdown
        self.windows_opened = 0
        self.open_server: OpenServer | None = None
        self.open_socket: Path | None = None
        self.syncing_preferences = False
        self.config = config
        self.store = store
        self.action_store = action_store
        self.session_store = session_store
        self.theme_manager = theme_manager
        self.profile_manager = profile_manager
        self.css_provider = css_provider

    def do_startup(self) -> None:
        Gtk.Application.do_startup(self)
        focus = Gio.SimpleAction.new("focus-pane", GLib.VariantType.new("s"))
        focus.connect("activate", self.on_focus_pane)
        self.add_action(focus)
        # Quit cleanly on SIGTERM/SIGINT so sockets and audio are released.
        for signal_number in (signal.SIGTERM, signal.SIGINT):
            GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal_number, self.on_quit_signal)

    def on_focus_pane(self, _action, parameter) -> None:
        """Clicking a "command finished" notification opens that pane."""
        pane_id = parameter.get_string()
        for window in self.get_windows():
            if isinstance(window, HackerTerminal) and window.focus_pane(pane_id):
                return

    def on_quit_signal(self) -> bool:
        for window in self.get_windows():
            if isinstance(window, HackerTerminal):
                window.closing_window = True
                window.save_session()
            window.destroy()
        self.quit()
        return False

    def ensure_open_server(self) -> Path | None:
        """One ht-open socket per process, shared by its windows."""
        if self.open_server is None:
            self.open_server = OpenServer(self.route_open)
            self.open_socket = self.open_server.start()
        return self.open_socket

    def route_open(self, path: Path, pane_id: str | None) -> None:
        windows = [window for window in self.get_windows() if isinstance(window, HackerTerminal)]
        owner = next((window for window in windows if window.pane_by_id(pane_id) is not None), None)
        target = owner or (windows[0] if windows else None)  # get_windows lists the most recent first
        if target is not None:
            target.open_file_from_pane(path, pane_id)

    def sync_preferences(self, origin: "HackerTerminal") -> None:
        """Windows share one Preferences object: apply a change everywhere."""
        if self.syncing_preferences:
            return
        self.syncing_preferences = True
        try:
            for window in self.get_windows():
                if isinstance(window, HackerTerminal) and window is not origin and not window.closing_window:
                    window.preferences_changed()
        finally:
            self.syncing_preferences = False

    def do_command_line(self, command_line) -> int:
        # An exception here would leave the launching command waiting forever.
        try:
            return self.handle_command_line(command_line)
        except Exception:
            LOGGER.exception("falha ao abrir janela pedida pela linha de comando")
            report_error(command_line, "hacker-terminal: não foi possível abrir a janela (veja o log)\n")
            return 1

    def handle_command_line(self, command_line) -> int:
        if self.windows_opened == 0:
            self.activate()  # the first window, configured by cli.main
            return 0
        from .cli import build_parser  # imported here: cli imports this module

        try:
            args = build_parser().parse_args(command_line.get_arguments()[1:])
        except SystemExit:
            report_error(command_line, "hacker-terminal: opções inválidas para uma nova janela\n")
            return 2
        if args.execute is not None and not args.execute:
            report_error(command_line, "hacker-terminal: -e/--execute requer um comando\n")
            return 2
        if args.working_directory:
            directory = Path(args.working_directory).expanduser()
            if not directory.is_absolute():
                directory = Path(command_line.get_cwd() or Path.home()) / directory
            directory = directory.resolve()
            if not directory.is_dir():
                report_error(command_line, f"hacker-terminal: diretório inicial inexistente: {directory}\n")
                return 2
        else:
            directory = self.profile_manager.working_directory(self.config.preferences.profile)
        config = AppConfig(self.config.preferences, tuple(args.execute or ()), directory)
        # Later windows start fresh: the saved tabs already came back in the first.
        self.open_window(config, restore=False, boot=False)
        return 0

    def open_window(self, config: AppConfig, restore: bool = True, boot: bool | None = None) -> "HackerTerminal":
        window = HackerTerminal(
            self, config, self.store, self.action_store, self.session_store,
            self.theme_manager, self.profile_manager, self.css_provider,
            dropdown=self.dropdown, restore=restore, boot=boot,
        )
        self.windows_opened += 1
        if self.dropdown:
            window.toggle_dropdown()
        else:
            window.present()
        return window

    def do_shutdown(self) -> None:
        if self.open_server is not None:
            self.open_server.stop()
        if KeySoundEngine._instance is not None:
            KeySoundEngine._instance.shutdown()
        Gtk.Application.do_shutdown(self)

    def do_activate(self) -> None:
        if self.dropdown:
            existing = next((w for w in self.get_windows() if isinstance(w, HackerTerminal)), None)
            if existing is not None:
                existing.toggle_dropdown()
                return
        self.open_window(self.config, restore=self.windows_opened == 0)
