"""The main window: header, tabs, sessions, preferences and status bar."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Callable

from ..actions import ActionStore
from ..config import AppConfig, ConfigStore
from ..connections import ConnectionStore
from ..constants import APP_NAME
from ..dialogs.actions import ActionEditorDialog
from ..dialogs.common import shorten_home, show_error
from ..dialogs.editors import ProfileEditorDialog
from ..dialogs.palette import CommandPaletteDialog
from ..dialogs.preferences import PreferencesDialog
from ..history import HistoryStore
from ..keysound import KeySoundEngine
from ..openserver import SOCKET_ENV
from ..profiles import ProfileError, ProfileManager
from ..project import detect_project_context
from ..runtime import GLib, Gdk, Gtk, Pango
from ..session import SessionState, SessionStore, SessionTab
from ..shortcuts import ShortcutMap, accelerator_label
from ..terminal import TerminalPane
from ..themes import ThemeManager
from .commands import CommandsMixin
from .dropdown import DropdownMixin
from .output import OutputMixin
from .panel import ActionPanel
from .panes import PanesMixin
from .ssh import SshMixin
from .viewer import ViewerMixin

LOGGER = logging.getLogger(__name__)


TITLE_PREFIX = re.compile(r"^[\w.-]+@[\w.-]+:\s*")  # "user@host: " in shell titles
SESSION_AUTOSAVE_SECONDS = 30


NARROW_WIDTH = 760


COMPACT_WIDTH = 1000


COMPACT_HEIGHT = 600


# A quiet header: everything else (split, search, history, SSH...) is one
# shortcut away and listed in the command palette.
HEADER_ACTIONS = (
    # icon name, fallback glyph, tooltip, shortcut id
    ("tab-new-symbolic", "+", "Nova aba", "new_tab"),
)


HEADER_END_ACTIONS = (  # packed from the right edge
    ("preferences-system-symbolic", "⚙", "Preferências", "preferences"),
    ("view-right-pane-symbolic", "☰", "Mostrar ou ocultar ações", "toggle_panel"),
    ("view-grid-symbolic", "⌘", "Paleta de comandos", "command_palette"),
)


def header_button(icon_name: str, fallback: str, tooltip: str) -> Gtk.Button:
    theme = Gtk.IconTheme.get_default()
    if theme is not None and theme.has_icon(icon_name):
        button = Gtk.Button.new_from_icon_name(icon_name, Gtk.IconSize.MENU)
    else:
        button = Gtk.Button(label=fallback)
    button.set_relief(Gtk.ReliefStyle.NONE)
    button.set_tooltip_text(tooltip)
    button.set_valign(Gtk.Align.CENTER)
    button.set_focus_on_click(False)
    button.get_style_context().add_class("header-action")
    return button


class HackerTerminal(ViewerMixin, CommandsMixin, OutputMixin, DropdownMixin, SshMixin, PanesMixin, Gtk.ApplicationWindow):
    def __init__(
        self,
        application: Gtk.Application,
        config: AppConfig,
        store: ConfigStore,
        action_store: ActionStore,
        session_store: SessionStore,
        theme_manager: ThemeManager,
        profile_manager: ProfileManager,
        css_provider: Gtk.CssProvider,
        dropdown: bool = False,
        restore: bool = True,
    ) -> None:
        super().__init__(application=application, title="Hacker Terminal")
        self.dropdown = dropdown
        self.config = config
        self.preferences = config.preferences
        self.store = store
        self.base_action_store = action_store
        self.action_store = action_store
        self.session_store = session_store
        self.theme_manager = theme_manager
        self.profile_manager = profile_manager
        self.css_provider = css_provider
        self.action_store = self.action_store_for_profile()
        self.shortcuts = ShortcutMap(self.preferences.shortcuts)
        for error in self.shortcuts.errors:
            LOGGER.warning(error)
        self.active_theme = self.theme_manager.get(self.preferences.theme)
        self.preferences.theme = self.active_theme.identifier
        self.translucent = self.enable_translucency()
        self.load_theme_css()
        self.closing_window = False
        self.tab_labels: dict[TerminalPane, Gtk.Label] = {}
        self.page_panes: dict[Gtk.Frame, list[TerminalPane]] = {}
        self.active_panes: dict[Gtk.Frame, TerminalPane] = {}
        self.toolbar_buttons: list[Gtk.Widget] = []
        self.panel_auto_hidden = False
        self.panel_peek = False
        self.viewers: dict[Gtk.Widget, TerminalPane | None] = {}
        self.broadcast_frames: set[Gtk.Frame] = set()
        self.connection_store = ConnectionStore()
        self.history_store = HistoryStore()
        self.open_socket = (
            application.ensure_open_server() if hasattr(application, "ensure_open_server") else None
        )
        self.saved_session = (
            self.session_store.load()
            if restore and self.preferences.restore_session and not self.config.command
            else None
        )
        if self.saved_session is not None:
            self.set_default_size(self.saved_session.width, self.saved_session.height)
        else:
            self.set_default_size(1180, 720)
        self.set_size_request(480, 320)
        self.set_icon_name(APP_NAME)
        self.connect("key-press-event", self.on_window_key_press)
        self.connect("focus-in-event", self.on_window_focus_in)
        self.connect("delete-event", self.on_delete_event)
        self.connect("configure-event", self.on_configure_event)
        self.connect("destroy", self.on_window_destroy)
        self.set_titlebar(self.build_header())
        if dropdown:
            self.setup_dropdown()
        self.update_header_tooltips()
        self.configure_key_sound()

        self.workspace = self.build_workspace()
        self.add(self.workspace)
        # The first tabs exist before the window is shown, so it is laid out
        # and styled once, with the terminal already in place.
        self.open_first_tabs()
        self.show_all()
        self.status_source_id = GLib.timeout_add_seconds(3, self.refresh_status)
        self.command_source_id = 0
        self.update_command_watch()
        self.autosave_source_id = GLib.timeout_add_seconds(SESSION_AUTOSAVE_SECONDS, self.autosave_session)

    def build_header(self) -> Gtk.HeaderBar:
        self.header = Gtk.HeaderBar(title="Hacker Terminal")
        self.header.set_has_subtitle(False)
        self.header.set_show_close_button(True)
        start = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=2)
        start.get_style_context().add_class("header-group")
        for icon_name, fallback, tooltip, action in HEADER_ACTIONS:
            start.pack_start(self.make_header_button(icon_name, fallback, tooltip, action), False, False, 0)
        self.header.pack_start(start)
        end = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=2)
        end.get_style_context().add_class("header-group")
        for icon_name, fallback, tooltip, action in HEADER_END_ACTIONS:
            end.pack_end(self.make_header_button(icon_name, fallback, tooltip, action), False, False, 0)
        self.header.pack_end(end)
        return self.header

    def make_header_button(self, icon_name: str, fallback: str, tooltip: str, action: str) -> Gtk.Button:
        button = header_button(icon_name, fallback, tooltip)
        button.connect("clicked", lambda _button, name=action: self.run_shortcut_action(name))
        button.header_tooltip = tooltip
        button.shortcut_action = action
        self.toolbar_buttons.append(button)
        return button

    def update_header_tooltips(self) -> None:
        for button in self.toolbar_buttons:
            action = getattr(button, "shortcut_action", None)
            if action is None:
                continue
            shortcut = accelerator_label(self.shortcuts.bindings.get(action, ""))
            button.set_tooltip_text(f"{button.header_tooltip} ({shortcut})")

    def shortcut_handlers(self) -> dict[str, Callable[[], object]]:
        viewer_actions = {
            ("copy",): lambda viewer: viewer.copy(),
            ("zoom", 1): lambda viewer: viewer.step_zoom(1),
            ("zoom", -1): lambda viewer: viewer.step_zoom(-1),
            ("zoom", 0): lambda viewer: viewer.set_zoom(1.0),
        }

        def on_terminal(method: str, *args) -> Callable[[], object]:
            def run() -> object:
                viewer = self.active_viewer()
                if viewer is not None:
                    action = viewer_actions.get((method, *args))
                    return action(viewer) if action is not None else None
                pane = self.get_active_terminal()
                return getattr(pane, method)(*args) if pane is not None else None

            return run

        return {
            "new_tab": self.new_tab,
            "close_pane": self.close_active_pane,
            "split_horizontal": lambda: self.split_active(Gtk.Orientation.HORIZONTAL),
            "split_vertical": lambda: self.split_active(Gtk.Orientation.VERTICAL),
            "focus_other_pane": self.focus_other_pane,
            "broadcast": self.toggle_broadcast,
            "ssh_manager": self.show_ssh_manager,
            "rename_pane": self.rename_pane,
            "command_history": self.show_command_history,
            "next_tab": lambda: self.cycle_tab(1),
            "previous_tab": lambda: self.cycle_tab(-1),
            "previous_prompt": lambda: self.jump_to_prompt(-1),
            "next_prompt": lambda: self.jump_to_prompt(1),
            "copy_last_output": self.copy_last_output,
            "copy": on_terminal("copy"),
            "paste": on_terminal("paste"),
            "search": self.search_active,
            "command_palette": self.show_command_palette,
            "toggle_panel": self.toggle_panel,
            "preferences": self.show_preferences,
            "zoom_in": on_terminal("zoom", 1),
            "zoom_out": on_terminal("zoom", -1),
            "zoom_reset": on_terminal("zoom", 0),
            "fullscreen": self.toggle_fullscreen,
        }

    def run_shortcut_action(self, identifier: str) -> None:
        handler = self.shortcut_handlers().get(identifier)
        if handler is not None:
            handler()

    def cycle_tab(self, delta: int) -> None:
        count = self.notebook.get_n_pages()
        if count:
            self.notebook.set_current_page((self.notebook.get_current_page() + delta) % count)

    def toggle_fullscreen(self) -> None:
        gdk_window = self.get_window()
        if gdk_window and gdk_window.get_state() & Gdk.WindowState.FULLSCREEN:
            self.unfullscreen()
        else:
            self.fullscreen()

    def action_store_for_profile(self) -> ActionStore:
        path = self.profile_manager.actions_path(self.preferences.profile)
        return ActionStore(path) if path is not None else self.base_action_store

    def sync_action_store(self) -> None:
        store = self.action_store_for_profile()
        if store.path == self.action_store.path:
            return
        self.action_store = store
        if self.action_panel is not None:
            self.action_panel.action_store = store
            self.action_panel.reload_actions()

    def save_profile_from_current(self) -> None:
        dialog = ProfileEditorDialog(self, self.profile_manager, None)
        while dialog.run() == Gtk.ResponseType.OK:
            try:
                saved = dialog.save(self.preferences, self.action_store)
            except ProfileError as error:
                show_error(dialog, "Perfil inválido", str(error))
                continue
            self.preferences.profile = saved.identifier
            self.preferences_changed()
            break
        dialog.destroy()

    def enable_translucency(self) -> bool:
        screen = self.get_screen()
        visual = screen.get_rgba_visual() if screen is not None else None
        if visual is None or not screen.is_composited():
            return False
        self.set_visual(visual)
        return True

    def load_theme_css(self) -> None:
        # Both are costly (GTK restyles every widget), so only when they change:
        # the startup code has usually loaded the same CSS already.
        opacity = self.preferences.opacity / 100 if self.translucent else 1.0
        css = self.active_theme.css(opacity)
        if getattr(self.css_provider, "loaded_css", None) != css:
            self.css_provider.load_from_data(css)
            self.css_provider.loaded_css = css
        settings = Gtk.Settings.get_default()
        if settings is not None and settings.get_property("gtk-application-prefer-dark-theme") != self.active_theme.dark:
            settings.set_property("gtk-application-prefer-dark-theme", self.active_theme.dark)

    def autosave_session(self) -> bool:
        """Persist the layout periodically so a crash or kill does not lose it."""
        if self.closing_window:
            self.autosave_source_id = 0
            return False
        if self.notebook.get_n_pages():
            self.save_session()
        return True

    def configure_key_sound(self) -> None:
        if self.preferences.sound:
            KeySoundEngine.shared().configure(
                self.preferences.key_switch, self.preferences.key_volume, self.preferences.key_release
            )

    def build_workspace(self) -> Gtk.Widget:
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        root.get_style_context().add_class("app-root")
        body = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        body.get_style_context().add_class("workspace")
        self.notebook = Gtk.Notebook()
        self.notebook.set_scrollable(True)
        self.notebook.set_show_border(False)
        self.notebook.popup_enable()
        self.notebook.connect("switch-page", self.on_switch_page)
        self.notebook.connect("page-added", lambda *_: self.update_tabs_visibility())
        self.notebook.connect("page-removed", lambda *_: self.update_tabs_visibility())
        body.pack_start(self.notebook, True, True, 0)
        self.action_panel: ActionPanel | None = None
        if not self.config.command:
            self.action_panel = ActionPanel(
                self.get_active_terminal,
                self.preferences,
                self.preferences_changed,
                self.action_store,
                self.show_action_editor,
            )
            body.pack_end(self.action_panel, False, False, 0)
            self.apply_panel_visibility()
        root.pack_start(body, True, True, 0)

        statusbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        statusbar.get_style_context().add_class("statusbar-row")
        self.status_context = Gtk.Label(label="", xalign=0)
        self.status_context.set_ellipsize(Pango.EllipsizeMode.START)
        self.status_context.get_style_context().add_class("status-context")
        statusbar.pack_start(self.status_context, True, True, 0)
        self.status = Gtk.Label(label="", xalign=1)
        self.status.set_ellipsize(Pango.EllipsizeMode.START)
        self.status.get_style_context().add_class("status")
        statusbar.pack_end(self.status, False, True, 0)
        root.pack_end(statusbar, False, False, 0)
        return root

    def update_tabs_visibility(self) -> None:
        self.notebook.set_show_tabs(self.notebook.get_n_pages() > 1)

    def on_configure_event(self, _window, event) -> bool:
        width, height = event.width, event.height
        if self.action_panel is not None and width > 1:
            self.action_panel.set_compact(width < COMPACT_WIDTH or height < COMPACT_HEIGHT)
            narrow = width < NARROW_WIDTH
            if narrow != self.panel_auto_hidden:
                self.panel_auto_hidden = narrow
                self.panel_peek = False
                self.apply_panel_visibility()
        return False

    def on_window_focus_in(self, _window, _event) -> bool:
        """Restore VTE focus when X11 consumes the tap that activates the window."""
        self.when_idle(self.restore_active_terminal_focus)
        return False

    def restore_active_terminal_focus(self) -> bool:
        if self.closing_window:
            return False
        pane = self.get_active_terminal()
        if pane is None:
            return False
        if pane.search_bar.get_reveal_child() and pane.search_bar.entry.is_focus():
            return False
        pane.terminal.grab_focus()
        return False

    def open_first_tabs(self) -> bool:
        if self.notebook.get_n_pages() == 0:
            if not self.restore_session():
                self.new_tab(initial=True)
        return False

    def restore_session(self) -> bool:
        state = self.saved_session
        self.saved_session = None
        if state is None:
            return False
        for tab in state.tabs:
            self.new_tab(working_directory=tab.directories[0])
            frame = self.active_frame()
            pane = self.get_active_terminal()
            if frame is not None and pane is not None:
                self.rebuild_layout(frame, pane, tab.tree(), tab.directories)
                for index, leaf in enumerate(self.leaves(frame.get_child())):
                    if tab.name(index):
                        leaf.set_custom_name(tab.name(index))
        if self.notebook.get_n_pages():
            self.notebook.set_current_page(state.active_tab)
            return True
        return False

    def new_tab(self, initial: bool = False, working_directory: Path | None = None) -> None:
        if self.config.command and self.notebook.get_n_pages() > 0:
            return
        command = self.config.command if initial else ()
        active = self.get_active_terminal()
        directory = working_directory or (
            self.config.working_directory
            if initial or active is None
            else active.current_working_directory()
        )
        pane = self.create_terminal(command, directory)
        frame = Gtk.Frame()
        frame.set_shadow_type(Gtk.ShadowType.NONE)
        frame.get_style_context().add_class("terminal-frame")
        frame.add(pane)
        self.page_panes[frame] = [pane]
        self.active_panes[frame] = pane
        tab_box, label = self.make_tab_label("Terminal", None, lambda: self.close_page(frame))
        page = self.notebook.append_page(frame, tab_box)
        self.notebook.set_tab_reorderable(frame, True)
        self.tab_labels[pane] = label
        frame.show_all()
        self.notebook.set_current_page(page)
        self.update_status()
        pane.spawn()

    def make_tab_label(
        self, text: str, icon_name: str | None, on_close: Callable[[], object]
    ) -> tuple[Gtk.Box, Gtk.Label]:
        tab_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=5)
        if icon_name is not None:
            tab_box.pack_start(Gtk.Image.new_from_icon_name(icon_name, Gtk.IconSize.MENU), False, False, 0)
        label = Gtk.Label(label=text)
        label.set_ellipsize(Pango.EllipsizeMode.END)
        label.set_max_width_chars(24)
        label.set_width_chars(18)
        close_button = header_button("window-close-symbolic", "×", "Fechar aba")
        close_button.get_style_context().remove_class("header-action")
        close_button.set_relief(Gtk.ReliefStyle.NONE)
        close_button.set_tooltip_text("Fechar aba")
        close_button.get_style_context().add_class("tab-close")
        close_button.connect("clicked", lambda *_: on_close())
        tab_box.pack_start(label, True, True, 0)
        tab_box.pack_start(close_button, False, False, 0)
        tab_box.show_all()
        return tab_box, label

    def pane_by_id(self, pane_id: str | None) -> TerminalPane | None:
        return next((pane for pane in self.terminals() if pane.pane_id == pane_id), None)

    def create_terminal(self, command: tuple[str, ...], directory: Path) -> TerminalPane:
        runtime = AppConfig(self.preferences, command, directory)
        pane = TerminalPane(
            runtime,
            self.on_terminal_exit,
            self.on_terminal_title_changed,
            self.preferences_changed,
            self.active_theme,
        )
        pane.terminal.connect("focus-in-event", lambda *_args, value=pane: self.on_pane_focus(value))
        pane.on_bell_callback = self.on_pane_bell
        pane.on_view_file = lambda source, path: (
            self.open_file(path, source) if path is not None else self.choose_file_to_view(source)
        )
        if self.open_socket is not None:
            pane.extra_env[SOCKET_ENV] = str(self.open_socket)
        pane.on_output_action = self.on_output_action
        pane.on_command_done = self.on_shell_command_done
        return pane

    def active_frame(self) -> Gtk.Frame | None:
        page = self.notebook.get_current_page()
        frame = self.notebook.get_nth_page(page) if page >= 0 else None
        return frame if isinstance(frame, Gtk.Frame) else None

    def get_active_terminal(self) -> TerminalPane | None:
        frame = self.active_frame()
        return self.active_panes.get(frame) if frame is not None else None

    def terminals(self) -> list[TerminalPane]:
        return [pane for panes in self.page_panes.values() for pane in panes]

    def frame_for_pane(self, pane: TerminalPane) -> Gtk.Frame | None:
        return next((frame for frame, panes in self.page_panes.items() if pane in panes), None)

    def on_pane_focus(self, pane: TerminalPane) -> bool:
        frame = self.frame_for_pane(pane)
        if frame is not None:
            self.active_panes[frame] = pane
            self.update_pane_highlight(frame)
            self.clear_bell(pane)
            if pane.title:
                self.on_terminal_title_changed(pane, pane.title)
        return False

    def on_terminal_exit(self, pane: TerminalPane, _status: int) -> None:
        frame = self.frame_for_pane(pane)
        if frame is not None:
            self.active_panes[frame] = pane
            self.close_active_pane(force=True)

    def on_terminal_title_changed(self, pane: TerminalPane, title: str) -> None:
        label = self.tab_labels.get(pane)
        if pane.custom_name:
            title = pane.custom_name
        if pane.title_prefix and not title.startswith(pane.title_prefix):
            title = f"{pane.title_prefix} · {title}"
        if label is not None:
            # "user@host: ~/dir" says the same thing on every tab; the folder
            # is what tells tabs apart. The full title stays in the tooltip.
            short = TITLE_PREFIX.sub("", title) or title
            if len(short) <= 28:
                compact = short
            elif short.startswith(("~", "/")):
                compact = "…" + short[-27:]  # a folder: its last part matters
            else:
                compact = short[:27] + "…"
            label.set_text(compact)
            label.set_tooltip_text(title)
        if pane is self.get_active_terminal():
            self.header.set_title(title)
            self.set_title(f"{title} — Hacker Terminal")

    def on_switch_page(self, _notebook, page, _number) -> None:
        pane = self.active_panes.get(page) if isinstance(page, Gtk.Frame) else None
        if pane is not None:
            self.when_idle(pane.terminal.grab_focus)
        elif page in self.viewers:
            self.when_idle(page.grab_focus)
        self.when_idle(self.update_status)

    def when_idle(self, callback: Callable[[], object]) -> None:
        """Run ``callback`` once the main loop is idle, unless the window is gone.

        A callback that touched a destroyed window crashed the whole process,
        and every window shares that process.
        """
        def run() -> bool:
            if not self.closing_window:
                callback()
            return False

        GLib.idle_add(run)

    def show_info(self, message: str) -> None:
        dialog = Gtk.MessageDialog(
            transient_for=self,
            modal=True,
            message_type=Gtk.MessageType.INFO,
            buttons=Gtk.ButtonsType.CLOSE,
            text=message,
        )
        dialog.run()
        dialog.destroy()

    def search_active(self) -> None:
        terminal = self.get_active_terminal()
        if terminal is not None:
            terminal.show_search()

    def toggle_panel(self) -> None:
        if self.action_panel is None:
            return
        if self.panel_auto_hidden:
            # Narrow windows hide the panel; the button shows it for a peek
            # whatever the saved preference is, and leaves that preference alone.
            self.panel_peek = not self.panel_peek
            self.apply_panel_visibility()
            return
        self.preferences.panel_visible = not self.action_panel.get_visible()
        self.preferences_changed()

    def show_preferences(self) -> None:
        dialog = PreferencesDialog(
            self,
            self.preferences,
            self.theme_manager,
            self.profile_manager,
            self.action_store,
        )
        response = dialog.run()
        if response == Gtk.ResponseType.OK:
            dialog.apply()
            self.preferences_changed()
        dialog.destroy()
        self.configure_key_sound()  # drop any preview the dialog configured

    def show_action_editor(self) -> None:
        dialog = ActionEditorDialog(self, self.action_store)
        if dialog.run() == Gtk.ResponseType.OK and self.action_store.save(dialog.actions):
            if self.action_panel is not None:
                self.action_panel.reload_actions()
        dialog.destroy()

    def palette_items(self) -> list[tuple[str, str, Callable[[], None]]]:
        items: list[tuple[str, str, Callable[[], None]]] = [
            ("Nova aba", "Terminal", self.new_tab),
            (
                "Dividir painel horizontalmente",
                "Terminal",
                lambda: self.split_active(Gtk.Orientation.HORIZONTAL),
            ),
            (
                "Dividir painel verticalmente",
                "Terminal",
                lambda: self.split_active(Gtk.Orientation.VERTICAL),
            ),
            ("Fechar painel ativo", "Terminal", self.close_active_pane),
            ("Pesquisar no histórico", "Terminal", self.search_active),
            ("Mostrar ou ocultar ações", "Interface", self.toggle_panel),
            ("Preferências", "Interface", self.show_preferences),
            ("Editar ações rápidas", "Interface", self.show_action_editor),
            ("Salvar configurações atuais como perfil", "Perfil", self.save_profile_from_current),
            ("Alternar painel dividido", "Terminal", self.focus_other_pane),
            ("Próxima aba", "Terminal", lambda: self.cycle_tab(1)),
            ("Aba anterior", "Terminal", lambda: self.cycle_tab(-1)),
            ("Tela cheia", "Interface", self.toggle_fullscreen),
            ("Visualizar imagem ou planilha…", "Arquivo", self.choose_file_to_view),
            ("Digitar em todos os painéis da aba (ligar/desligar)", "Terminal", self.toggle_broadcast),
            ("Copiar saída do último comando", "Terminal", self.copy_last_output),
            ("Ir ao prompt anterior", "Terminal", lambda: self.jump_to_prompt(-1)),
            ("Ir ao próximo prompt", "Terminal", lambda: self.jump_to_prompt(1)),
            ("Salvar saída do terminal…", "Arquivo", self.save_output_dialog),
            ("Gravar saída do terminal (iniciar/parar)", "Arquivo", self.toggle_recording),
            ("Aumentar fonte", "Terminal", lambda: self.run_shortcut_action("zoom_in")),
            ("Diminuir fonte", "Terminal", lambda: self.run_shortcut_action("zoom_out")),
            ("Tamanho padrão da fonte", "Terminal", lambda: self.run_shortcut_action("zoom_reset")),
        ]
        for profile in self.profile_manager.all():
            items.append(
                (
                    f"Aplicar perfil: {profile.name}",
                    "Perfil",
                    lambda value=profile.identifier: self.apply_profile(value),
                )
            )
        for theme in self.theme_manager.all():
            items.append(
                (
                    f"Aplicar tema: {theme.name}",
                    "Tema",
                    lambda value=theme.identifier: self.apply_theme(value),
                )
            )
        items.append(("Renomear painel…", "Painel", self.rename_pane))
        items.append(("Histórico de comandos…", "Histórico", self.show_command_history))
        items.append(("Conexões SSH…", "SSH", self.show_ssh_manager))
        for connection in self.connection_store.load():
            items.append((f"SSH: {connection.name}", "SSH", lambda value=connection: self.connect_ssh(value)))
        if self.action_panel is not None:
            for action in self.action_store.load():
                items.append(
                    (
                        action.label,
                        "Ação rápida",
                        lambda value=action: self.action_panel.run_action(value),
                    )
                )
        return items

    def show_command_palette(self) -> None:
        dialog = CommandPaletteDialog(self, self.palette_items())
        response = dialog.run()
        callback = dialog.selected_callback
        dialog.destroy()
        if response == Gtk.ResponseType.OK and callback is not None:
            callback()

    def apply_profile(self, identifier: str) -> None:
        self.profile_manager.apply(identifier, self.preferences)
        self.preferences_changed()

    def apply_theme(self, identifier: str) -> None:
        self.preferences.theme = identifier
        self.preferences_changed()

    def preferences_changed(self) -> None:
        self.preferences.normalize()
        self.place_dropdown_if_visible()  # a new height applies at once
        self.active_theme = self.theme_manager.get(self.preferences.theme)
        self.preferences.theme = self.active_theme.identifier
        self.load_theme_css()
        self.shortcuts = ShortcutMap(self.preferences.shortcuts)
        self.update_header_tooltips()
        self.sync_action_store()
        self.configure_key_sound()
        self.update_command_watch()
        if not self.store.save(self.preferences):
            LOGGER.warning("as preferências não puderam ser salvas em %s", self.store.path)
        for terminal in self.terminals():
            terminal.apply_preferences(self.active_theme)
        if self.action_panel is not None:
            self.apply_panel_visibility()
        self.update_status()
        application = self.get_application()
        if hasattr(application, "sync_preferences"):
            application.sync_preferences(self)

    def apply_panel_visibility(self) -> None:
        if self.action_panel is None:
            return
        visible = self.panel_peek if self.panel_auto_hidden else self.preferences.panel_visible
        self.action_panel.set_no_show_all(not visible)
        self.action_panel.set_visible(visible)

    def update_status(self) -> None:
        tabs = len(self.page_panes)
        panes = len(self.terminals())
        parts = [f"{tabs} {'aba' if tabs == 1 else 'abas'}"]
        if panes != tabs:
            parts.append(f"{panes} {'painel' if panes == 1 else 'painéis'}")
        alerts: list[str] = []  # shown first, in the theme's alert colour
        terminal = self.get_active_terminal()
        directory_text = ""
        viewer = self.active_viewer()
        if viewer is not None:
            directory_text = shorten_home(viewer.path)
        if self.viewers:
            parts.append(f"{len(self.viewers)} {'visualização' if len(self.viewers) == 1 else 'visualizações'}")
        frame = self.active_frame()
        if frame is not None and frame in self.broadcast_frames:
            alerts.append(f"⇉ transmitindo para {len(self.page_panes.get(frame, []))}")
        recording = sum(1 for pane in self.terminals() if pane.recorder is not None)
        if recording:
            alerts.append("● gravando" if recording == 1 else f"● gravando {recording}")
        if terminal is not None:
            directory = terminal.current_working_directory()
            directory_text = shorten_home(directory)
            last = next((mark for mark in reversed(terminal.prompts) if mark.finished), None)
            if last is not None and last.exit_status not in (None, 0):
                alerts.append(f"✗ saída {last.exit_status}")
            context = detect_project_context(directory)
            if context.branch:
                parts.append(f"git {context.branch}")
            if context.environment:
                parts.append(f"env {context.environment}")
        escape = GLib.markup_escape_text
        markup = "  ·  ".join(
            [f'<span foreground="{self.active_theme.danger}">{escape(alert)}</span>' for alert in alerts]
            + [escape(part) for part in parts]
        )
        if self.status.get_label() != markup:
            self.status.set_markup(markup)
        if getattr(self, "toast_text", ""):
            directory_text = self.toast_text
        if self.status_context.get_text() != directory_text:
            self.status_context.set_text(directory_text)
            self.status_context.set_tooltip_text(directory_text or None)
        title = (terminal.title if terminal is not None else "") or directory_text or "Hacker Terminal"
        if self.header.get_title() != title:
            self.header.set_title(title)

    def refresh_status(self) -> bool:
        if self.closing_window:
            return False
        self.update_status()
        return True

    def on_window_destroy(self, _window) -> None:
        self.closing_window = True  # pending idle callbacks must not touch it
        context = GLib.MainContext.default()
        for attribute in ("status_source_id", "autosave_source_id", "command_source_id", "toast_source"):
            source = getattr(self, attribute, 0)
            # A callback that raised was already dropped by GLib; removing it
            # again would warn, so only remove sources that still exist.
            if source and context.find_source_by_id(source) is not None:
                GLib.source_remove(source)
            setattr(self, attribute, 0)

    def confirm_close(self, message: str) -> bool:
        dialog = Gtk.MessageDialog(
            transient_for=self,
            modal=True,
            message_type=Gtk.MessageType.WARNING,
            buttons=Gtk.ButtonsType.NONE,
            text="Encerrar processo?",
        )
        dialog.format_secondary_text(message + " O processo será encerrado ao fechar.")
        dialog.add_buttons("Cancelar", Gtk.ResponseType.CANCEL, "Encerrar", Gtk.ResponseType.OK)
        response = dialog.run()
        dialog.destroy()
        return response == Gtk.ResponseType.OK

    def on_delete_event(self, _window, _event) -> bool:
        if self.closing_window:
            return False
        active = [terminal for terminal in self.terminals() if terminal.has_active_process()]
        if active and not self.confirm_close(f"Existem processos ativos em {len(active)} sessão(ões)."):
            return True
        self.save_session()
        self.closing_window = True
        for terminal in self.terminals():
            terminal.prepare_close()
        return False

    def save_session(self) -> None:
        if self.config.command or not self.preferences.restore_session:
            self.session_store.clear()
            return
        tabs: list[SessionTab] = []
        for page in range(self.notebook.get_n_pages()):
            frame = self.notebook.get_nth_page(page)
            if not isinstance(frame, Gtk.Frame):
                continue
            order = self.leaves(frame.get_child())
            if not order:
                continue
            directories = tuple(pane.current_working_directory() for pane in order)
            names = tuple(pane.custom_name for pane in order)
            tabs.append(SessionTab(directories, None, self.layout_of(frame.get_child(), order), names))
        if not tabs:
            self.session_store.clear()
            return
        width, height = self.get_size()
        self.session_store.save(
            SessionState(width, height, self.notebook.get_current_page(), tuple(tabs))
        )

    def on_window_key_press(self, _window, event) -> bool:
        identifier = self.shortcuts.match(event.keyval, event.state)
        if identifier is None:
            return False
        self.run_shortcut_action(identifier)
        return True
