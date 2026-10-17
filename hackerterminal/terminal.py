"""VTE terminal pane, search UI and session lifecycle."""

from __future__ import annotations

import functools
import logging
import os
import re
import shlex
import shutil
import socket
import uuid
from pathlib import Path
from dataclasses import dataclass
from typing import Callable
from urllib.parse import unquote, urlparse

from .config import AppConfig
from .documents import IMAGE_SUFFIXES, SPREADSHEET_SUFFIXES
from .openserver import PANE_ENV
from .constants import DEFAULT_FONT_SIZE
from .effects import EffectsLayer
from .keysound import KeySoundEngine
from .fonts import FontChoice, choose_font
from .runtime import Atk, Gdk, Gio, GLib, Gtk, Pango, Vte
from .session import clean_name
from .sandbox import IN_FLATPAK, export_to_host, host_command, host_shell
from .themes import Theme

LOGGER = logging.getLogger(__name__)
PCRE2_MULTILINE = 0x00000400
CURSOR_SHAPES = {
    "block": Vte.CursorShape.BLOCK,
    "ibeam": Vte.CursorShape.IBEAM,
    "underline": Vte.CursorShape.UNDERLINE,
}
CURSOR_BLINK = {
    "system": Vte.CursorBlinkMode.SYSTEM,
    "on": Vte.CursorBlinkMode.ON,
    "off": Vte.CursorBlinkMode.OFF,
}
# C0 controls other than tab/newline/carriage return, plus DEL and C1 controls.
UNSAFE_PASTE_CHARACTERS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")
URL_PATTERN = r"(?:https?|ftp|file)://[^\s<>{}\[\]\"']+"
# File names with a viewable extension, e.g. in `ls` output; Ctrl+click opens them.
VIEWABLE_SUFFIXES = sorted(suffix[1:] for suffix in IMAGE_SUFFIXES | SPREADSHEET_SUFFIXES)
FILE_PATTERN = (
    r"(?<![\w/:.~-])(?:~|\.{1,2})?/?(?:[\w@+,.-]+/)*[\w@+,.-]*\w\.(?i:"
    + "|".join(VIEWABLE_SUFFIXES)
    + r")(?![\w/])"
)
TOOLS_DIRECTORY = Path(__file__).resolve().parent.parent / "bin"
SHELL_DIRECTORY = Path(__file__).resolve().parent / "shell"
MARK_PROPERTY = "vte.ext.hackerterminal.mark"
# Termprops arrived in VTE 0.78 (Ubuntu 24.04 ships 0.76): without them the
# shell integration stays off and command alerts fall back to /proc polling.
HAS_TERMPROPS = hasattr(Vte, "install_termprop") and hasattr(Vte, "get_termprops")
# Sixel images need a VTE built with it (Debian/Kali builds leave it out);
# ht-open --inline draws images everywhere else.
HAS_SIXEL = bool(Vte.get_feature_flags() & Vte.FeatureFlags.FLAG_SIXEL) and hasattr(Vte.Terminal, "set_enable_sixel")
if HAS_TERMPROPS and MARK_PROPERTY not in Vte.get_termprops():
    # Custom termprops must exist before terminals are created; shell hooks
    # set it with OSC 666 once per prompt.
    Vte.install_termprop(MARK_PROPERTY, Vte.PropertyType.STRING, Vte.PropertyFlags.NONE)


@dataclass
class PromptMark:
    """A prompt seen in the terminal and, once known, its command's result."""

    row: int            # last row of the prompt (where the command is typed)
    column: int         # cursor column after the prompt
    prompt_lines: int
    command: str = ""
    exit_status: int | None = None
    duration: float = 0.0
    finished: bool = False

    @property
    def first_row(self) -> int:
        return self.row - self.prompt_lines + 1


def parse_mark(value: str) -> tuple[int, int | None, float, int, str] | None:
    """Decode ``1|seq|status|duration_ms|prompt_lines|command`` from the hooks.

    OSC 666 treats ";" as a separator between properties, so fields use "|"
    and the command is percent-encoded by the hooks.
    """
    parts = value.split("|", 5)
    if len(parts) != 6 or parts[0] != "1":
        return None
    try:
        sequence = int(parts[1])
        status = int(parts[2]) if parts[2] else None
        duration = int(parts[3] or 0) / 1000
        lines = max(1, min(10, int(parts[4] or 1)))
    except ValueError:
        return None
    return sequence, status, duration, lines, unquote(parts[5])


def command_extra_rows(mark: PromptMark, columns: int) -> int:
    """Rows a typed command adds below the prompt line (wrapping and newlines)."""
    lines = mark.command.split("\n")
    extra = max(0, mark.column + len(lines[0]) - 1) // columns
    for line in lines[1:]:
        extra += 1 + max(0, len(line) - 1) // columns
    return extra


def integration_launch(argv: list[str], custom_shell: str) -> tuple[list[str], dict[str, str]]:
    """Adapt the shell command line to load the integration hooks."""
    if not HAS_TERMPROPS:
        return argv, {}
    if os.environ.get("HACKER_TERMINAL_SHELL_INTEGRATION", "1").strip().lower() in ("0", "false", "no", "off"):
        return argv, {}
    name = Path(argv[0]).name
    plain = len(argv) == 1 or argv[1:] == ["-l"]
    if not plain:
        return argv, {}  # the user's own arguments win
    directory = host_files("shell")
    if directory is None:
        return argv, {}
    if name == "zsh" and (directory / "zsh" / ".zshenv").is_file():
        env = {"ZDOTDIR": str(directory / "zsh"), "HACKER_TERMINAL_SHELL_INTEGRATION": "zsh"}
        if os.environ.get("ZDOTDIR") and not IN_FLATPAK:
            env["HACKER_TERMINAL_ZDOTDIR"] = os.environ["ZDOTDIR"]
        return argv, env
    if name == "bash" and (directory / "bash" / "integration.bash").is_file():
        script = str(directory / "bash" / "integration.bash")
        return [argv[0], "--init-file", script, "-i"], {"HACKER_TERMINAL_SHELL_INTEGRATION": "bash"}
    return argv, {}


def resolve_viewable(text: str, directory: Path) -> Path | None:
    """Turn a file name seen in the terminal into an existing viewable file."""
    candidate = Path(os.path.expanduser(text.strip()))
    if not candidate.is_absolute():
        candidate = directory / candidate
    try:
        candidate = candidate.resolve()
    except (OSError, RuntimeError):
        return None
    if candidate.suffix.lower() not in IMAGE_SUFFIXES | SPREADSHEET_SUFFIXES:
        return None
    return candidate if candidate.is_file() else None


def rgba(value: str, alpha: float = 1.0) -> Gdk.RGBA:
    color = Gdk.RGBA()
    if not color.parse(value):
        raise ValueError(f"Invalid color: {value}")
    color.alpha = alpha
    return color


@functools.lru_cache(maxsize=None)
def host_files(name: str) -> Path | None:
    """Our files as the shell sees them: copied out of the sandbox under Flatpak."""
    source = SHELL_DIRECTORY if name == "shell" else TOOLS_DIRECTORY
    if not IN_FLATPAK:
        return source
    return export_to_host(source, name)


def resolve_shell() -> str:
    if IN_FLATPAK:
        return host_shell()
    configured = os.environ.get("SHELL")
    if configured and Path(configured).is_file() and os.access(configured, os.X_OK):
        return configured
    return shutil.which("zsh") or shutil.which("bash") or "/bin/sh"


def shell_argv(custom: str = "", warn: bool = True) -> list[str]:
    """Return the configured shell command, or the login shell as fallback."""
    if custom:
        try:
            argv = shlex.split(custom)
        except ValueError:
            argv = []
        if argv and IN_FLATPAK:
            return [os.path.expanduser(argv[0]), *argv[1:]]  # a host path we cannot check
        if argv and (resolved := shutil.which(os.path.expanduser(argv[0]))):
            return [resolved, *argv[1:]]
        if warn:
            LOGGER.warning("shell personalizado indisponível: %s", custom)
    return [resolve_shell(), "-l"]


def paste_risks(text: str) -> list[str]:
    """Describe why pasting ``text`` could run something unexpectedly."""
    risks = []
    if "\n" in text.rstrip("\n") or "\r" in text:
        risks.append("contém várias linhas e pode executar comandos")
    elif text.endswith("\n"):
        risks.append("termina com quebra de linha e será executado imediatamente")
    if UNSAFE_PASTE_CHARACTERS.search(text.replace("\r", "")):
        risks.append("contém caracteres de controle ocultos")
    return risks

def process_has_children(process_id: int) -> bool:
    if process_id <= 0:
        return False
    children_file = Path(f"/proc/{process_id}/task/{process_id}/children")
    try:
        return bool(children_file.read_text(encoding="ascii").strip())
    except OSError:
        return False


def foreground_child(process_id: int) -> tuple[int, str] | None:
    """The newest child of the shell and its command name, if one is running."""
    if process_id <= 0:
        return None
    try:
        children = Path(f"/proc/{process_id}/task/{process_id}/children").read_text(encoding="ascii").split()
        if not children:
            return None
        child = int(children[-1])
        name = Path(f"/proc/{child}/comm").read_text(encoding="utf-8", errors="replace").strip()
    except (OSError, ValueError):
        return None
    return child, name or "processo"


def format_duration(seconds: float) -> str:
    seconds = int(round(seconds))
    if seconds < 60:
        return f"{seconds} s"
    minutes, seconds = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes} min {seconds:02d} s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours} h {minutes:02d} min"


HTML_HEADER = (
    "<!doctype html>\n<html><head><meta charset=\"utf-8\"><title>{title}</title>"
    "<style>body{{background:{background};color:{foreground};margin:24px}}"
    "pre{{font:13px/1.35 monospace;white-space:pre-wrap;margin:0}}</style></head><body>\n"
)


def unlimited_scrollback(limit: int) -> bool:
    # VTE reports an unlimited scrollback (set as -1) as G_MAXLONG.
    return limit < 0 or limit >= 2**31


class OutputRecorder:
    """Append a pane's finished lines to a file while recording.

    Lines are written as soon as the cursor has moved past them, every
    couple of seconds, so a later `clear` (which may wipe the scrollback)
    or a scrollback overflow cannot lose what was already recorded.
    """

    FLUSH_SECONDS = 1

    def __init__(self, terminal: Vte.Terminal, path: Path, html: bool, header: str = "") -> None:
        self.terminal = terminal
        self.path = path
        self.html = html
        self.saved_row = terminal.get_cursor_position()[1]
        self.lines = 0
        self.lost_rows = 0
        self.handle = path.open("w", encoding="utf-8")
        os.chmod(path, 0o600)
        if header:
            self.handle.write(header)
        self.source_id = GLib.timeout_add_seconds(self.FLUSH_SECONDS, self._tick)
        # Fast output could push unsaved rows out of the scrollback between
        # ticks; flush early once half of it is pending.
        self.changed_handler = terminal.connect("contents-changed", self._on_contents_changed)

    def _on_contents_changed(self, terminal) -> None:
        # The scrollback is unlimited while recording, so this only keeps
        # each write (and the temporary scrollback) reasonably small.
        if self.handle is not None and terminal.get_cursor_position()[1] - self.saved_row > 5_000:
            self._tick()

    def first_available_row(self) -> int:
        limit = self.terminal.get_scrollback_lines()
        if unlimited_scrollback(limit):
            return 0  # nothing has been dropped
        cursor_row = self.terminal.get_cursor_position()[1]
        return max(0, cursor_row - limit + 1)

    def flush(self) -> None:
        if self.handle is None:
            return
        cursor_row = self.terminal.get_cursor_position()[1]
        if cursor_row < self.saved_row:
            self.saved_row = cursor_row  # the scrollback was reset under us
        first = self.first_available_row()
        if self.saved_row < first:
            self.lost_rows += first - self.saved_row
            self.saved_row = first
        end = cursor_row - 1  # only rows the cursor has left are final
        if end < self.saved_row:
            return
        fmt = Vte.Format.HTML if self.html else Vte.Format.TEXT
        result = self.terminal.get_text_range_format(fmt, self.saved_row, 0, end, self.terminal.get_column_count())
        text = result[0] if isinstance(result, tuple) else result
        if text:
            if self.html:
                text = text.replace("<pre>", "").replace("</pre>", "")
            self.handle.write(text if text.endswith("\n") else text + "\n")
            self.handle.flush()
        self.lines += end - self.saved_row + 1
        self.saved_row = end + 1

    def _tick(self) -> bool:
        if self.handle is None:
            return False
        try:
            self.flush()
        except (OSError, ValueError) as error:
            LOGGER.warning("gravação interrompida: %s", error)
            self.stop()
            return False
        return True

    def stop(self) -> None:
        if self.handle is None:
            return
        if self.source_id and GLib.MainContext.default().find_source_by_id(self.source_id) is not None:
            GLib.source_remove(self.source_id)
        self.source_id = 0
        if self.changed_handler:
            self.terminal.disconnect(self.changed_handler)
            self.changed_handler = 0
        try:
            # Include the current line too: recording is over.
            cursor_row = self.terminal.get_cursor_position()[1]
            if cursor_row >= self.saved_row:
                fmt = Vte.Format.HTML if self.html else Vte.Format.TEXT
                result = self.terminal.get_text_range_format(
                    fmt, max(self.saved_row, self.first_available_row()), 0, cursor_row, self.terminal.get_column_count()
                )
                text = result[0] if isinstance(result, tuple) else result
                if text and text.strip():
                    if self.html:
                        text = text.replace("<pre>", "").replace("</pre>", "")
                    self.handle.write(text.rstrip("\n") + "\n")
            if self.html:
                self.handle.write("</pre></body></html>\n")
        finally:
            self.handle.close()
            self.handle = None


def path_from_file_uri(uri: str | None) -> Path | None:
    if not uri:
        return None
    parsed = urlparse(uri)
    # Shells report their host name; another host means a remote (SSH) path.
    local_names = ("", "localhost", socket.gethostname().casefold())
    if parsed.scheme != "file" or parsed.netloc.casefold() not in local_names:
        return None
    path = Path(unquote(parsed.path))
    return path if path.is_dir() else None


def normalize_uri_candidate(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = value.rstrip(".,;:!?)]}")
    parsed = urlparse(cleaned)
    return cleaned if parsed.scheme in {"http", "https", "ftp", "file"} else None


class SearchBar(Gtk.Revealer):
    def __init__(self, terminal: Vte.Terminal) -> None:
        super().__init__()
        self.terminal = terminal
        self.last_result = False
        self.set_transition_type(Gtk.RevealerTransitionType.SLIDE_UP)
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        row.get_style_context().add_class("search-bar")
        self.entry = Gtk.Entry()
        self.entry.set_placeholder_text("Pesquisar no histórico…")
        self.entry.get_style_context().add_class("search-entry")
        self.entry.connect("changed", self.on_changed)
        self.entry.connect("activate", lambda *_: self.find_next())
        self.entry.connect("key-press-event", self.on_key_press)
        row.pack_start(self.entry, True, True, 0)
        for label, tooltip, callback in (
            ("↑", "Resultado anterior", self.find_previous),
            ("↓", "Próximo resultado", self.find_next),
            ("×", "Fechar pesquisa", self.hide_search),
        ):
            button = Gtk.Button(label=label)
            button.set_relief(Gtk.ReliefStyle.NONE)
            button.set_tooltip_text(tooltip)
            button.get_style_context().add_class("search-button")
            button.connect("clicked", lambda _button, action=callback: action())
            row.pack_start(button, False, False, 0)
        self.add(row)

    def show_search(self) -> None:
        self.set_reveal_child(True)
        self.entry.grab_focus()
        self.entry.select_region(0, -1)

    def hide_search(self) -> None:
        self.set_reveal_child(False)
        self.terminal.search_set_regex(None, 0)
        self.terminal.grab_focus()

    def on_changed(self, entry: Gtk.Entry) -> None:
        text = entry.get_text()
        if not text:
            self.terminal.search_set_regex(None, 0)
            self.last_result = False
            return
        try:
            regex = Vte.Regex.new_for_search(re.escape(text), -1, PCRE2_MULTILINE)
            self.terminal.search_set_regex(regex, 0)
            self.terminal.search_set_wrap_around(True)
            self.last_result = self.terminal.search_find_next()
        except GLib.Error:
            self.terminal.search_set_regex(None, 0)
            self.last_result = False

    def find_next(self) -> None:
        if self.entry.get_text():
            self.last_result = self.terminal.search_find_next()

    def find_previous(self) -> None:
        if self.entry.get_text():
            self.last_result = self.terminal.search_find_previous()

    def on_key_press(self, _entry, event) -> bool:
        if event.keyval == Gdk.KEY_Escape:
            self.hide_search()
            return True
        return False


class TerminalPane(Gtk.Box):
    def __init__(
        self,
        config: AppConfig,
        on_exit: Callable[["TerminalPane", int], None],
        on_title_changed: Callable[["TerminalPane", str], None],
        on_preferences_changed: Callable[[], None],
        theme: Theme,
    ) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.get_style_context().add_class("terminal-pane")
        self.config = config
        self.on_exit_callback = on_exit
        self.on_title_changed_callback = on_title_changed
        self.on_preferences_changed = on_preferences_changed
        self.on_bell_callback: Callable[["TerminalPane"], None] | None = None
        self.on_view_file: Callable[["TerminalPane", Path | None], None] | None = None
        self.on_output_action: Callable[["TerminalPane", str], None] | None = None
        self.pane_id = uuid.uuid4().hex
        self.extra_env: dict[str, str] = {}
        self.link_tag = -1
        self.file_tag = -1
        self.sound_enabled = config.preferences.sound
        self.shell_running = False
        self.closing = False
        self.child_pid = -1
        self.title = ""
        self.bell_pending = False
        self.recorder: OutputRecorder | None = None
        self.prompts: list[PromptMark] = []
        self.broadcast_peers: list["TerminalPane"] = []
        self.mirroring = False
        self.banner_shown = False
        self.theme_override: Theme | None = None
        self.custom_name = ""
        self.command_pending = False
        self.title_prefix = ""
        self.pending_input = ""
        self.last_mark_sequence = -1
        self.on_command_done: Callable[["TerminalPane", PromptMark], None] | None = None
        self.gutter_handler = 0
        self.command_started: float | None = None
        self.command_name: str | None = None
        self.zoom_scroll = 0.0
        self.used_fallback_shell = False
        self.spawn_cancellable: Gio.Cancellable | None = None
        self.font_choice: FontChoice = choose_font(config.preferences.font)

        self.terminal = Vte.Terminal()
        self.terminal.set_mouse_autohide(True)
        self.terminal.set_allow_hyperlink(True)
        if HAS_SIXEL:
            self.terminal.set_enable_sixel(True)  # img2sixel, chafa -f sixel...
        self.terminal.set_audible_bell(False)
        # VTE's native bridge to GtkScrolledWindow correctly handles the
        # high-resolution deltas generated by XInput/libinput touchpads.
        self.terminal.set_enable_fallback_scrolling(True)
        self.terminal.set_scroll_unit_is_pixels(True)
        self.terminal.add_events(
            Gdk.EventMask.BUTTON_PRESS_MASK
            | Gdk.EventMask.BUTTON_RELEASE_MASK
            | Gdk.EventMask.SCROLL_MASK
            | Gdk.EventMask.SMOOTH_SCROLL_MASK
            | Gdk.EventMask.TOUCH_MASK
        )
        self.terminal.connect("key-press-event", self.on_terminal_key_press)
        self.terminal.connect("key-release-event", self.on_terminal_key_release)
        self.terminal.connect("focus-out-event", lambda *_args: KeySoundEngine.shared().reset_keys() or False)
        self.terminal.connect("scroll-event", self.on_terminal_scroll)
        self.terminal.connect("button-press-event", self.on_button_press)
        self.terminal.connect("button-release-event", self.on_pointer_release)
        self.terminal.connect("touch-event", self.on_touch_event)
        self.terminal.connect("child-exited", self.on_child_exited)
        self.terminal.connect("selection-changed", self.on_selection_changed)
        self.terminal.connect("bell", self.on_bell)
        if HAS_TERMPROPS:
            self.terminal.connect("termprop-changed", self.on_termprop_changed)
        self.terminal.connect("commit", self.on_commit)
        self.terminal.connect("notify::window-title", self.on_window_title_changed)
        try:
            link_regex = Vte.Regex.new_for_match(URL_PATTERN, -1, PCRE2_MULTILINE)
            self.link_tag = self.terminal.match_add_regex(link_regex, 0)
            self.terminal.match_set_cursor_name(self.link_tag, "pointer")
        except GLib.Error:
            pass
        try:
            file_regex = Vte.Regex.new_for_match(FILE_PATTERN, -1, PCRE2_MULTILINE)
            self.file_tag = self.terminal.match_add_regex(file_regex, 0)
            self.terminal.match_set_cursor_name(self.file_tag, "pointer")
        except GLib.Error as error:
            LOGGER.debug("padrão de arquivos indisponível: %s", error)
        self.connect("destroy", self.on_destroy)

        self.scroller = Gtk.ScrolledWindow()
        self.scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.scroller.set_shadow_type(Gtk.ShadowType.NONE)
        self.scroller.add_events(
            Gdk.EventMask.BUTTON_PRESS_MASK
            | Gdk.EventMask.SCROLL_MASK
            | Gdk.EventMask.SMOOTH_SCROLL_MASK
            | Gdk.EventMask.TOUCH_MASK
        )
        self.scroller.connect("button-press-event", self.on_scroller_pointer)
        self.scroller.connect("touch-event", self.on_touch_event)
        self.scroller.connect("scroll-event", self.on_terminal_scroll)
        self.scroller.add(self.terminal)
        # Effects are painted on the terminal itself; an overlay window would
        # intercept touchpad scrolling on X11.
        self.effects = EffectsLayer(self.terminal)
        # Shown only for named panes, so splits are easy to tell apart.
        self.name_bar = Gtk.Label(xalign=0)
        self.name_bar.set_ellipsize(Pango.EllipsizeMode.END)
        self.name_bar.get_style_context().add_class("pane-name")
        self.name_bar.set_no_show_all(True)
        self.pack_start(self.name_bar, False, False, 0)
        self.pack_start(self.scroller, True, True, 0)
        self.search_bar = SearchBar(self.terminal)
        self.pack_start(self.search_bar, False, False, 0)
        self.apply_preferences(theme)

    def apply_preferences(self, theme: Theme) -> None:
        # An SSH tab keeps its host's theme whatever the window uses.
        theme = self.theme_override or theme
        preferences = self.config.preferences
        self.font_choice = choose_font(preferences.font)
        self.terminal.set_font(Pango.FontDescription(f"{self.font_choice.family} {preferences.font_size}"))
        if getattr(self, "recorder", None) is None:
            self.terminal.set_scrollback_lines(preferences.scrollback_lines)
        self.terminal.set_cursor_shape(CURSOR_SHAPES.get(preferences.cursor_shape, Vte.CursorShape.BLOCK))
        self.terminal.set_cursor_blink_mode(CURSOR_BLINK.get(preferences.cursor_blink, Vte.CursorBlinkMode.SYSTEM))
        self.terminal.set_bold_is_bright(preferences.bold_is_bright)
        self.terminal.set_scroll_on_output(preferences.scroll_on_output)
        self.terminal.set_scroll_on_keystroke(preferences.scroll_on_keystroke)
        self.sound_enabled = preferences.sound
        self.effects.set_enabled(preferences.effects)
        self.effects.apply_theme(theme)
        self.terminal.set_color_cursor(rgba(theme.cursor))
        self.terminal.set_color_highlight(rgba(theme.selection_background))
        self.terminal.set_color_highlight_foreground(rgba(theme.selection_foreground))
        self.theme_colors = (theme.terminal_background, theme.terminal_foreground)
        self.mark_colors = (
            tuple(int(theme.accent[index:index + 2], 16) / 255 for index in (1, 3, 5)),
            tuple(int(theme.danger[index:index + 2], 16) / 255 for index in (1, 3, 5)),
        )
        self.terminal.set_colors(
            rgba(theme.terminal_foreground),
            rgba(theme.terminal_background, preferences.opacity / 100),
            [rgba(color) for color in theme.ansi],
        )

    def zoom(self, delta: int) -> None:
        preferences = self.config.preferences
        preferences.font_size = (
            DEFAULT_FONT_SIZE
            if delta == 0
            else min(32, max(6, preferences.font_size + delta))
        )
        self.on_preferences_changed()

    def spawn(self) -> None:
        if self.shell_running or self.spawn_cancellable is not None:
            return
        if self.config.command:
            argv = list(self.config.command)
        elif self.used_fallback_shell:
            argv = shell_argv()
        else:
            argv = shell_argv(self.config.preferences.shell)
        LOGGER.debug("iniciando %s em %s", argv, self.config.working_directory)
        if not self.banner_shown:
            # Before the shell starts, so its prompt lands below the banner;
            # printing it later raced with the shell and garbled lines.
            self.banner_shown = True
            self.show_banner()
        child_env = dict(os.environ)
        child_env.update({"TERM": "xterm-256color", "COLORTERM": "truecolor", "HACKER_TERMINAL": "1"})
        child_env.update(self.extra_env)
        child_env[PANE_ENV] = self.pane_id
        child_env.pop("HACKER_TERMINAL_ZDOTDIR", None)
        if not self.config.command and self.config.preferences.shell_integration:
            argv, integration_env = integration_launch(argv, self.config.preferences.shell)
            child_env.update(integration_env)
        else:
            child_env["HACKER_TERMINAL_SHELL_INTEGRATION"] = "0"
        if (TOOLS_DIRECTORY / "ht-open").is_file():
            # Appended, so a user's own command with the same name still wins.
            child_env["PATH"] = os.pathsep.join(filter(None, [child_env.get("PATH", ""), str(TOOLS_DIRECTORY)]))
        if IN_FLATPAK:
            argv, child_env = self.host_launch(argv, child_env)
        environment = [f"{key}={value}" for key, value in child_env.items()]
        self.spawn_cancellable = Gio.Cancellable()
        self.terminal.spawn_async(
            Vte.PtyFlags.DEFAULT,
            str(self.config.working_directory),
            argv,
            environment,
            GLib.SpawnFlags.SEARCH_PATH,
            None,
            None,
            -1,
            self.spawn_cancellable,
            self.on_spawned,
            None,
        )

    def host_launch(self, argv: list[str], child_env: dict[str, str]) -> tuple[list[str], dict[str, str]]:
        """Run on the host: pass only our own variables, the host keeps its own."""
        ours = {key: value for key, value in child_env.items() if os.environ.get(key) != value}
        ours.pop("PATH", None)
        version = Vte.get_major_version() * 10000 + Vte.get_minor_version() * 100 + Vte.get_micro_version()
        ours["VTE_VERSION"] = str(version)  # distro vte.sh hooks report the directory only then
        tools = host_files("bin")
        if tools is not None:
            ours["HACKER_TERMINAL_TOOLS"] = str(tools)
        return host_command(argv, self.config.working_directory, ours), dict(os.environ)

    def on_spawned(self, _terminal, process_id, error, _data) -> None:
        self.spawn_cancellable = None
        if error and (self.closing or error.matches(Gio.io_error_quark(), Gio.IOErrorEnum.CANCELLED)):
            return
        if error:
            LOGGER.warning("falha ao iniciar o processo: %s", error)
            self.terminal.feed(f"\r\n\x1b[31mFalha ao iniciar o processo: {error}\x1b[0m\r\n".encode())
            if not self.config.command and self.config.preferences.shell and not self.used_fallback_shell:
                self.used_fallback_shell = True
                self.terminal.feed(b"Usando o shell padr\xc3\xa3o do sistema.\r\n")
                self.spawn()
            return
        self.child_pid = process_id
        self.shell_running = True
        if self.pending_input:
            # Typed before the prompt exists, the tty would echo it twice:
            # wait for the shell's first output, then let it settle.
            self.pending_handler = self.terminal.connect("contents-changed", self.on_first_output)
        self.terminal.grab_focus()

    def show_banner(self) -> bool:
        if self.config.command or self.closing:
            return False
        glyph_status = (
            "Nerd Font + Powerline"
            if self.font_choice.has_nerd_symbols
            else "Powerline"
            if self.font_choice.has_powerline
            else "fallback basico"
        )
        message = f"HACKER-TERMINAL ONLINE | fonte: {self.font_choice.family} ({glyph_status})"
        self.terminal.feed(
            (f"\x1b[1;32m{message}\x1b[0m\r\nUse somente em sistemas autorizados.\r\n").encode()
        )
        return False

    def on_first_output(self, _terminal: Vte.Terminal) -> None:
        self.terminal.disconnect(self.pending_handler)
        GLib.timeout_add(300, self.send_pending_input)

    def send_pending_input(self) -> bool:
        if self.pending_input and self.shell_running and not self.closing:
            command, self.pending_input = self.pending_input, ""
            self.run_command(command)
        return False

    def run_command(self, command: str) -> None:
        if not self.shell_running:
            self.terminal.feed(b"\r\n\x1b[33mO shell ainda nao esta disponivel.\x1b[0m\r\n")
            return
        if self.recorder is not None:
            self.recorder.flush()
        # feed_child emits "commit", so broadcasting mirrors this too.
        self.terminal.feed_child((command + "\n").encode())

    def copy(self) -> None:
        if self.terminal.get_has_selection():
            self.terminal.copy_clipboard_format(Vte.Format.TEXT)

    def paste(self) -> None:
        clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
        clipboard.request_text(lambda _clipboard, text: self.paste_text(text))

    def paste_text(self, text: str | None) -> None:
        if not text or self.closing:
            return
        risks = paste_risks(text) if self.config.preferences.confirm_paste else []
        if risks and not self.confirm_paste(text, risks):
            return
        if hasattr(self.terminal, "paste_text"):
            self.terminal.paste_text(text)  # honours bracketed paste mode
        else:
            self.terminal.feed_child(text.encode())

    def confirm_paste(self, text: str, risks: list[str]) -> bool:
        parent = self.get_toplevel()
        dialog = Gtk.MessageDialog(
            transient_for=parent if isinstance(parent, Gtk.Window) else None,
            modal=True,
            message_type=Gtk.MessageType.WARNING,
            buttons=Gtk.ButtonsType.NONE,
            text="Colar este conteúdo?",
        )
        preview = text if len(text) <= 600 else text[:600] + "…"
        dialog.format_secondary_text("O texto " + "; ".join(risks) + ".\n\n" + preview)
        dialog.add_buttons("Cancelar", Gtk.ResponseType.CANCEL, "Colar mesmo assim", Gtk.ResponseType.OK)
        dialog.set_default_response(Gtk.ResponseType.CANCEL)
        response = dialog.run()
        dialog.destroy()
        return response == Gtk.ResponseType.OK

    def on_selection_changed(self, terminal) -> None:
        if self.config.preferences.copy_on_select and terminal.get_has_selection():
            terminal.copy_clipboard_format(Vte.Format.TEXT)

    def on_bell(self, _terminal) -> None:
        if not self.config.preferences.bell_notify:
            return
        self.bell_pending = True
        if self.on_bell_callback is not None:
            self.on_bell_callback(self)

    def show_search(self) -> None:
        self.search_bar.show_search()

    def current_working_directory(self) -> Path:
        current = path_from_file_uri(self.terminal.get_current_directory_uri())
        return current or self.config.working_directory

    # ------------------------------------------------------------ broadcast

    def on_commit(self, _terminal, text: str, _size: int) -> None:
        """Keystrokes (and pastes) sent to this shell; mirror them when broadcasting."""
        if "\r" in text or "\n" in text:
            self.command_pending = True  # cleared by the next prompt mark
        if self.broadcast_peers and not self.mirroring:
            self.forward_to_peers(text.encode("utf-8", "surrogateescape"))

    def forward_to_peers(self, data: bytes) -> None:
        for peer in self.broadcast_peers:
            if peer.shell_running and not peer.closing:
                # feed_child emits "commit" on the peer too; without this
                # guard the panes would echo each other forever.
                peer.mirroring = True
                try:
                    peer.terminal.feed_child(data)
                finally:
                    peer.mirroring = False

    # ---------------------------------------------------- shell integration

    @property
    def integrated(self) -> bool:
        return bool(self.prompts)

    def first_buffer_row(self) -> int:
        """Absolute row shown at scroll position 0 (older rows were dropped)."""
        cursor_row = self.terminal.get_cursor_position()[1]
        height = max(1, self.terminal.get_char_height())
        rows = round(self.terminal.get_vadjustment().get_upper() / height)
        return max(0, cursor_row - rows + 1)

    def on_termprop_changed(self, terminal, name: str) -> None:
        if name != MARK_PROPERTY:
            return
        value, _length = terminal.get_termprop_string(name)
        parsed = parse_mark(value or "")
        if parsed is None:
            return
        sequence, status, duration, lines, command = parsed
        if sequence == self.last_mark_sequence:
            return
        self.last_mark_sequence = sequence
        self.command_pending = False
        column, row = terminal.get_cursor_position()
        # A `clear` that wipes the scrollback renumbers rows; drop stale marks.
        first = self.first_buffer_row()
        self.prompts = [mark for mark in self.prompts if first <= mark.row < row]
        if self.prompts and command:
            previous = self.prompts[-1]
            previous.command, previous.exit_status, previous.duration = command, status, duration
            previous.finished = True
            if self.on_command_done is not None:
                self.on_command_done(self, previous)
        self.prompts.append(PromptMark(row, column, lines))
        del self.prompts[:-500]  # plenty for jumping, bounded memory
        self.ensure_gutter()
        terminal.queue_draw()

    def output_rows(self, index: int) -> tuple[int, int] | None:
        """Rows printed by the command typed at prompt ``index``."""
        if not 0 <= index < len(self.prompts) - 1:
            return None
        mark, following = self.prompts[index], self.prompts[index + 1]
        start = mark.row + 1 + command_extra_rows(mark, max(1, self.terminal.get_column_count()))
        end = following.first_row - 1
        return (start, end) if end >= start else None

    def last_output(self) -> tuple[PromptMark, str] | None:
        for index in range(len(self.prompts) - 2, -1, -1):
            mark = self.prompts[index]
            if not mark.finished:
                continue
            rows = self.output_rows(index)
            if rows is None:
                return mark, ""
            result = self.terminal.get_text_range_format(
                Vte.Format.TEXT, rows[0], 0, rows[1], self.terminal.get_column_count()
            )
            text = (result[0] if isinstance(result, tuple) else result) or ""
            return mark, text.rstrip("\n")
        return None

    def copy_last_output(self) -> tuple[PromptMark, int] | None:
        found = self.last_output()
        if found is None:
            return None
        mark, text = found
        Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).set_text(text, -1)
        return mark, (text.count("\n") + 1 if text else 0)

    def top_visible_row(self) -> float:
        """Absolute row shown at the top of the view.

        VTE exposes no screen offset, and after a `clear` the screen no
        longer ends at the cursor; the accessible caret's pixel position
        tells where the cursor row is drawn, which pins the mapping.
        """
        adjustment = self.terminal.get_vadjustment()
        column, row = self.terminal.get_cursor_position()
        key = (adjustment.get_value(), adjustment.get_upper(), row, column, self.terminal.get_allocated_height())
        if key == getattr(self, "_top_cache", (None, None))[0]:
            return self._top_cache[1]
        height = max(1, self.terminal.get_char_height())
        top = None
        accessible = self.terminal.get_accessible() if Atk is not None else None
        if isinstance(accessible, Atk.Text) and self.terminal.get_toplevel() is not None:
            offset = accessible.get_caret_offset()
            origin = self.terminal.translate_coordinates(self.terminal.get_toplevel(), 0, 0)
            if offset >= 0 and origin is not None:
                _x, y, _width, _height = accessible.get_character_extents(offset, Atk.CoordType.WINDOW)
                padding = self.terminal.get_style_context().get_padding(Gtk.StateFlags.NORMAL).top
                if y > -10_000:  # extents are -1 when unavailable
                    top = row - round((y - origin[1] - padding) / height)
        if top is None:
            top = self.first_buffer_row() + adjustment.get_value() / height
        self._top_cache = (key, top)
        return top

    def jump_to_prompt(self, direction: int) -> bool:
        """Scroll so the previous/next prompt is at the top; True if moved."""
        if not self.prompts:
            return False
        top = self.top_visible_row()
        rows = [mark.first_row for mark in self.prompts]
        if direction < 0:
            candidates = [row for row in rows if row < top - 0.5]
            target = candidates[-1] if candidates else None
        else:
            candidates = [row for row in rows if row > top + 0.5]
            target = candidates[0] if candidates else None
        if target is None:
            return False
        adjustment = self.terminal.get_vadjustment()
        height = self.terminal.get_char_height()
        # Relative move from the current view: no need to know where the
        # buffer starts (it shifts after `clear` or a scrollback overflow).
        value = adjustment.get_value() + (target - top) * height
        adjustment.set_value(max(adjustment.get_lower(), min(value, adjustment.get_upper() - adjustment.get_page_size())))
        return True

    def ensure_gutter(self) -> None:
        if not self.gutter_handler:
            self.gutter_handler = self.terminal.connect_after("draw", self.draw_gutter)

    def draw_gutter(self, widget, context) -> bool:
        """A thin bar beside each finished command: accent if OK, red if it failed."""
        if not self.prompts or not self.config.preferences.command_marks:
            return False
        height = widget.get_char_height()
        top = self.top_visible_row()
        visible_rows = widget.get_allocated_height() / max(1, height) + 1
        padding = widget.get_style_context().get_padding(Gtk.StateFlags.NORMAL)
        accent, danger = getattr(self, "mark_colors", ((0.4, 0.8, 0.6), (0.9, 0.3, 0.3)))
        for mark in self.prompts:
            if not mark.finished or mark.exit_status is None:
                continue
            offset = mark.first_row - top
            if offset < -mark.prompt_lines or offset > visible_rows:
                continue
            color = accent if mark.exit_status == 0 else danger
            context.set_source_rgba(*color, 0.55 if mark.exit_status == 0 else 0.9)
            y = padding.top + offset * height
            context.rectangle(0, y, max(2, padding.left - 1) if padding.left > 3 else 2, height * mark.prompt_lines)
            context.fill()
        return False

    # ------------------------------------------------- saving and recording

    def html_header(self, title: str) -> str:
        background, foreground = getattr(self, "theme_colors", ("#000000", "#ffffff"))
        return HTML_HEADER.format(title=GLib.markup_escape_text(title), background=background, foreground=foreground) + "<pre>"

    def save_output(self, path: Path) -> int:
        """Write everything still in the scrollback; returns the line count."""
        html = path.suffix.lower() in (".html", ".htm")
        cursor_row = self.terminal.get_cursor_position()[1]
        limit = self.terminal.get_scrollback_lines()
        first = 0 if unlimited_scrollback(limit) else max(0, cursor_row - limit + 1)
        fmt = Vte.Format.HTML if html else Vte.Format.TEXT
        result = self.terminal.get_text_range_format(fmt, first, 0, cursor_row, self.terminal.get_column_count())
        text = (result[0] if isinstance(result, tuple) else result) or ""
        if html:
            text = self.html_header(path.stem) + text.replace("<pre>", "").replace("</pre>", "") + "</pre></body></html>\n"
        elif not text.endswith("\n"):
            text += "\n"
        temporary = path.with_name(f".{path.name}.tmp")
        temporary.write_text(text, encoding="utf-8")
        temporary.chmod(0o600)
        temporary.replace(path)
        return cursor_row - first + 1

    def start_recording(self, path: Path) -> None:
        self.stop_recording()
        html = path.suffix.lower() in (".html", ".htm")
        self.recorder = OutputRecorder(self.terminal, path, html, self.html_header(path.stem) if html else "")
        # VTE handles a burst of output in one go and only then reports it,
        # so a bounded scrollback could drop rows before they are recorded.
        # Unlimited scrollback lives in compressed temporary files, not RAM.
        self.terminal.set_scrollback_lines(-1)

    def stop_recording(self) -> OutputRecorder | None:
        recorder, self.recorder = self.recorder, None
        if recorder is not None:
            recorder.stop()
            if not self.closing:
                self.terminal.set_scrollback_lines(self.config.preferences.scrollback_lines)
        return recorder

    def poll_command(self, now: float) -> tuple[str, float] | None:
        """Track the running command; report (name, duration) when it ends."""
        running = foreground_child(self.child_pid) if self.shell_running and not self.config.command else None
        if running is not None:
            if self.command_started is None:
                self.command_started, self.command_name = now, running[1]
            return None
        if self.command_started is None:
            return None
        finished = (self.command_name or "comando", now - self.command_started)
        self.command_started = self.command_name = None
        return finished

    def has_active_process(self) -> bool:
        if not self.shell_running:
            return False
        if IN_FLATPAK:
            # The host's processes are invisible here; the prompt marks tell
            # whether a command is still running.
            return bool(self.config.command) or (self.integrated and self.command_pending)
        return bool(self.config.command) or process_has_children(self.child_pid)

    def prepare_close(self) -> None:
        self.closing = True

    def on_terminal_key_press(self, terminal, event) -> bool:
        # Shortcuts are dispatched by the window so that users can rebind them.
        if self.recorder is not None and event.keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            # Everything before a new command is final: save it before the
            # command can clear the scrollback.
            self.recorder.flush()
        if self.sound_enabled:
            KeySoundEngine.shared().press(event.hardware_keycode, event.keyval)
        return False

    def on_terminal_key_release(self, _terminal, event) -> bool:
        if self.sound_enabled:
            KeySoundEngine.shared().release(event.hardware_keycode, event.keyval)
        return False

    def on_terminal_scroll(self, _terminal, event) -> bool:
        """Reactivate the pane; Ctrl+wheel zooms, other scrolling stays with VTE/GTK."""
        self.terminal.grab_focus()
        if event.state & Gdk.ModifierType.CONTROL_MASK:
            delta = 0.0
            if event.direction == Gdk.ScrollDirection.UP:
                delta = -1.0
            elif event.direction == Gdk.ScrollDirection.DOWN:
                delta = 1.0
            elif event.direction == Gdk.ScrollDirection.SMOOTH:
                # Touchpads send many fractional deltas; zoom one step per unit.
                self.zoom_scroll += event.get_scroll_deltas()[2]
                if abs(self.zoom_scroll) >= 1.0:
                    delta, self.zoom_scroll = self.zoom_scroll, 0.0
                else:
                    return True
            if delta:
                self.zoom(1 if delta < 0 else -1)
                return True
        return False

    def on_scroller_pointer(self, _widget, _event) -> bool:
        """Recover focus when an input backend targets the scroll container."""
        self.terminal.grab_focus()
        return False

    def on_pointer_release(self, _widget, _event) -> bool:
        """Handle touchpad taps synthesized only as a button release."""
        self.terminal.grab_focus()
        return False

    def on_touch_event(self, _widget, event) -> bool:
        """Recover focus from native touch events without consuming the gesture."""
        if event.type == Gdk.EventType.TOUCH_BEGIN:
            self.terminal.grab_focus()
        return False

    def on_button_press(self, terminal, event) -> bool:
        # VTE does not consistently reclaim focus after toolbar/sidebar widgets
        # receive it, especially with some GTK 3 input backends.
        terminal.grab_focus()
        control = bool(event.state & Gdk.ModifierType.CONTROL_MASK)
        if not (event.button == 3 or (event.button == 1 and control)):
            return False  # plain clicks never need link or file matching
        uri = self.uri_at_event(event)
        viewable = None if uri else self.file_at_event(event)
        if event.button == 1 and control and uri:
            self.open_uri(uri)
            return True
        if event.button == 1 and control and viewable is not None and self.on_view_file is not None:
            self.on_view_file(self, viewable)
            return True
        if event.button != 3:
            return False
        menu = Gtk.Menu()
        actions = [
            ("Copiar", lambda *_: self.copy()),
            ("Colar", lambda *_: self.paste()),
            ("Pesquisar", lambda *_: self.show_search()),
            ("Limpar", lambda *_: self.run_command("clear")),
        ]
        if self.integrated:
            actions.append(("Copiar saída do último comando", lambda *_: self.on_output_action(self, "copy-last")))
        if self.on_output_action is not None:
            label = "Parar de digitar em todos os painéis" if self.broadcast_peers else "Digitar em todos os painéis da aba"
            actions.append((label, lambda *_: self.on_output_action(self, "broadcast")))
        if self.on_output_action is not None:
            actions.append(("Renomear painel…", lambda *_: self.on_output_action(self, "rename")))
            actions.append(("Salvar saída…", lambda *_: self.on_output_action(self, "save")))
            recording = "Parar gravação" if self.recorder is not None else "Gravar saída…"
            actions.append((recording, lambda *_: self.on_output_action(self, "record")))
        if self.on_view_file is not None:
            actions.append(("Visualizar arquivo…", lambda *_: self.on_view_file(self, None)))
            if viewable is not None:
                actions.insert(0, (f"Visualizar {viewable.name}", lambda *_: self.on_view_file(self, viewable)))
        if uri:
            actions.insert(0, ("Abrir link", lambda *_: self.open_uri(uri)))
        for label, callback in actions:
            item = Gtk.MenuItem(label=label)
            item.connect("activate", callback)
            menu.append(item)
        menu.show_all()
        menu.popup_at_pointer(event)
        return True

    def file_at_event(self, event) -> Path | None:
        match = self.terminal.match_check_event(event)
        if not isinstance(match, tuple) or match[0] is None or match[1] != self.file_tag:
            return None
        return resolve_viewable(match[0], self.current_working_directory())

    def uri_at_event(self, event) -> str | None:
        hyperlink = normalize_uri_candidate(self.terminal.hyperlink_check_event(event))
        if hyperlink:
            return hyperlink
        match = self.terminal.match_check_event(event)
        if isinstance(match, tuple):
            if match[1] == self.file_tag:
                return None
            value = match[0]
        else:
            value = match
        return normalize_uri_candidate(value)

    @staticmethod
    def open_uri(uri: str) -> None:
        try:
            Gio.AppInfo.launch_default_for_uri(uri, None)
        except GLib.Error as error:
            LOGGER.warning("não foi possível abrir %s: %s", uri, error)

    def set_custom_name(self, name: str) -> None:
        self.custom_name = clean_name(name)
        self.name_bar.set_text(self.custom_name)
        self.name_bar.set_visible(bool(self.custom_name))
        self.on_title_changed_callback(self, self.title or "Terminal")

    def on_window_title_changed(self, _terminal, _property) -> None:
        self.title = self.terminal.get_window_title() or ""
        self.on_title_changed_callback(self, self.title or "Terminal")

    def on_child_exited(self, _terminal, status: int) -> None:
        self.shell_running = False
        self.child_pid = -1
        if not self.closing:
            self.on_exit_callback(self, status)

    def on_destroy(self, _widget) -> None:
        self.closing = True
        self.stop_recording()
        if self.spawn_cancellable is not None:
            self.spawn_cancellable.cancel()
            self.spawn_cancellable = None
