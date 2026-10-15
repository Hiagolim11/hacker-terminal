"""VTE terminal pane, search UI and session lifecycle."""

from __future__ import annotations

import logging
import os
import re
import shlex
import shutil
from pathlib import Path
from typing import Callable
from urllib.parse import unquote, urlparse

from .config import AppConfig
from .constants import DEFAULT_FONT_SIZE
from .effects import EffectsLayer
from .keysound import KeySoundEngine
from .fonts import FontChoice, choose_font
from .runtime import Gdk, Gio, GLib, Gtk, Pango, Vte
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


def rgba(value: str, alpha: float = 1.0) -> Gdk.RGBA:
    color = Gdk.RGBA()
    if not color.parse(value):
        raise ValueError(f"Invalid color: {value}")
    color.alpha = alpha
    return color


def resolve_shell() -> str:
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


def path_from_file_uri(uri: str | None) -> Path | None:
    if not uri:
        return None
    parsed = urlparse(uri)
    if parsed.scheme != "file" or parsed.netloc not in ("", "localhost"):
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
        self.sound_enabled = config.preferences.sound
        self.shell_running = False
        self.closing = False
        self.child_pid = -1
        self.title = ""
        self.bell_pending = False
        self.zoom_scroll = 0.0
        self.used_fallback_shell = False
        self.spawn_cancellable: Gio.Cancellable | None = None
        self.font_choice: FontChoice = choose_font(config.preferences.font)

        self.terminal = Vte.Terminal()
        self.terminal.set_mouse_autohide(True)
        self.terminal.set_allow_hyperlink(True)
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
        self.terminal.connect("notify::window-title", self.on_window_title_changed)
        try:
            link_regex = Vte.Regex.new_for_match(URL_PATTERN, -1, PCRE2_MULTILINE)
            link_tag = self.terminal.match_add_regex(link_regex, 0)
            self.terminal.match_set_cursor_name(link_tag, "pointer")
        except GLib.Error:
            pass
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
        self.pack_start(self.scroller, True, True, 0)
        self.search_bar = SearchBar(self.terminal)
        self.pack_start(self.search_bar, False, False, 0)
        self.apply_preferences(theme)

    def apply_preferences(self, theme: Theme) -> None:
        preferences = self.config.preferences
        self.font_choice = choose_font(preferences.font)
        self.terminal.set_font(Pango.FontDescription(f"{self.font_choice.family} {preferences.font_size}"))
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
        child_env = dict(os.environ)
        child_env.update({"TERM": "xterm-256color", "COLORTERM": "truecolor", "HACKER_TERMINAL": "1"})
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
        self.terminal.grab_focus()
        GLib.timeout_add(250, self.show_banner)

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
            (f"\r\n\x1b[1;32m{message}\x1b[0m\r\nUse somente em sistemas autorizados.\r\n").encode()
        )
        return False

    def run_command(self, command: str) -> None:
        if not self.shell_running:
            self.terminal.feed(b"\r\n\x1b[33mO shell ainda nao esta disponivel.\x1b[0m\r\n")
            return
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

    def has_active_process(self) -> bool:
        if not self.shell_running:
            return False
        return bool(self.config.command) or process_has_children(self.child_pid)

    def prepare_close(self) -> None:
        self.closing = True

    def on_terminal_key_press(self, terminal, event) -> bool:
        # Shortcuts are dispatched by the window so that users can rebind them.
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
        uri = self.uri_at_event(event)
        control = bool(event.state & Gdk.ModifierType.CONTROL_MASK)
        if event.button == 1 and control and uri:
            self.open_uri(uri)
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
        if uri:
            actions.insert(0, ("Abrir link", lambda *_: self.open_uri(uri)))
        for label, callback in actions:
            item = Gtk.MenuItem(label=label)
            item.connect("activate", callback)
            menu.append(item)
        menu.show_all()
        menu.popup_at_pointer(event)
        return True

    def uri_at_event(self, event) -> str | None:
        hyperlink = normalize_uri_candidate(self.terminal.hyperlink_check_event(event))
        if hyperlink:
            return hyperlink
        match = self.terminal.match_check_event(event)
        value = match[0] if isinstance(match, tuple) else match
        return normalize_uri_candidate(value)

    @staticmethod
    def open_uri(uri: str) -> None:
        try:
            Gio.AppInfo.launch_default_for_uri(uri, None)
        except GLib.Error as error:
            LOGGER.warning("não foi possível abrir %s: %s", uri, error)

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
        if self.spawn_cancellable is not None:
            self.spawn_cancellable.cancel()
            self.spawn_cancellable = None
