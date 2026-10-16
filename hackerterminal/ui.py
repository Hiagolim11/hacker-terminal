"""Main window, tabs, actions and preferences dialog."""

from __future__ import annotations

import dataclasses
import logging
import os
import shlex
import shutil
import signal
import tempfile
import time
import uuid
from pathlib import Path
from typing import Callable

from .actions import ActionStore, QuickAction
from .actions import fields as command_fields, fill as fill_command
from .audio import SoundPlayer, make_tone
from .config import AppConfig, ConfigStore, Preferences
from .constants import APP_ID, APP_NAME, VERSION
from .constants import DEFAULT_THEME
from .fonts import choose_font, installed_font_families
from .connections import Connection, ConnectionError, ConnectionStore, validate as validate_connection
from .documents import kind_of
from .dropdown import DEFAULT_KEY, bind_xfce, launch_command, xfce_available, xfce_binding
from .dropdown import geometry as dropdown_geometry
from .openserver import SOCKET_ENV, OpenServer
from .keysound import (
    SYNTH_SWITCHES,
    KeySoundEngine,
    list_packs,
    load_pack,
    packs_directory,
    PackError,
)
from .profiles import Profile, ProfileError, ProfileManager, profile_from_preferences, slugify
from .project import detect_project_context
from .runtime import Gdk, GdkX11, Gio, GLib, Gtk, Pango
from .session import MAX_PANES_PER_TAB, SessionState, SessionStore, SessionTab
from .shortcuts import MODIFIER_MASK, SHORTCUT_ACTIONS, ShortcutMap, accelerator_label, accelerator_name
from .terminal import TerminalPane, format_duration, shell_argv
from .themes import THEME_COLOR_FIELDS, Theme, ThemeManager, ThemeError

LOGGER = logging.getLogger(__name__)
SESSION_AUTOSAVE_SECONDS = 30


PANEL_WIDTH = 220
COMPACT_PANEL_WIDTH = 178
NARROW_WIDTH = 760
COMPACT_WIDTH = 1000
COMPACT_HEIGHT = 600

HEADER_ACTIONS = (
    # icon name, fallback glyph, tooltip, shortcut id
    ("tab-new-symbolic", "+", "Nova aba", "new_tab"),
    ("view-dual-symbolic", "▥", "Dividir painel", "split_horizontal"),
    ("edit-find-symbolic", "⌕", "Pesquisar no histórico", "search"),
    ("view-grid-symbolic", "⌘", "Paleta de comandos", "command_palette"),
    ("network-server-symbolic", "⇄", "Conexões SSH", "ssh_manager"),
)
HEADER_END_ACTIONS = (
    ("preferences-system-symbolic", "⚙", "Preferências", "preferences"),
    ("view-right-pane-symbolic", "☰", "Mostrar ou ocultar ações", "toggle_panel"),
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


MAX_PACK_BYTES = 100 * 1024 * 1024


def install_sound_pack(source: Path) -> str:
    """Validate a sound pack and copy it into the user's pack folder."""
    if packs_directory() in source.resolve().parents:
        return source.name
    total = sum(item.stat().st_size for item in source.rglob("*") if item.is_file())
    if total > MAX_PACK_BYTES:
        raise PackError("o pacote tem mais de 100 MB")
    load_pack(source)  # raises PackError for anything unusable
    base = slugify(source.name) or "pacote"
    destination = packs_directory() / base
    counter = 2
    while destination.exists():
        destination = packs_directory() / f"{base}-{counter}"
        counter += 1
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(
            source,
            destination,
            ignore=lambda folder, names: [name for name in names if (Path(folder) / name).is_symlink()],
        )
    except OSError as error:
        raise PackError(f"não foi possível copiar o pacote: {error}") from error
    return destination.name


CRT_LABELS = (
    ("glow", "Brilho do fósforo"),
    ("vignette", "Vinheta"),
    ("noise", "Ruído estático"),
    ("flicker", "Cintilação"),
    ("curvature", "Curvatura da tela"),
)
# Debian/Kali packages for fonts suggested by the built-in themes.
FONT_PACKAGES = {"terminus": "fonts-terminus-otb", "ibm 3270": "fonts-3270"}


def shlex_first(command: str) -> str:
    try:
        parts = shlex.split(command)
    except ValueError:
        return command
    return parts[0] if parts else ""


def show_error(parent: Gtk.Window, title: str, message: str) -> None:
    dialog = Gtk.MessageDialog(
        transient_for=parent,
        modal=True,
        message_type=Gtk.MessageType.ERROR,
        buttons=Gtk.ButtonsType.CLOSE,
        text=title,
    )
    dialog.format_secondary_text(message)
    dialog.run()
    dialog.destroy()


def confirm(parent: Gtk.Window, title: str, message: str, action: str) -> bool:
    dialog = Gtk.MessageDialog(
        transient_for=parent,
        modal=True,
        message_type=Gtk.MessageType.QUESTION,
        buttons=Gtk.ButtonsType.NONE,
        text=title,
    )
    dialog.format_secondary_text(message)
    dialog.add_buttons("Cancelar", Gtk.ResponseType.CANCEL, action, Gtk.ResponseType.OK)
    response = dialog.run()
    dialog.destroy()
    return response == Gtk.ResponseType.OK


def mark_suggested(dialog: Gtk.Dialog) -> None:
    button = dialog.get_widget_for_response(Gtk.ResponseType.OK)
    if button is not None:
        button.get_style_context().add_class("suggested-action")


def shorten_home(path: Path) -> str:
    try:
        return "~/" + str(path.relative_to(Path.home())) if path != Path.home() else "~"
    except ValueError:
        return str(path)


class ActionPanel(Gtk.Box):
    def __init__(
        self,
        get_terminal: Callable[[], TerminalPane | None],
        preferences: Preferences,
        on_preferences_changed: Callable[[], None],
        action_store: ActionStore,
        on_edit_actions: Callable[[], None],
    ) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.get_terminal = get_terminal
        self.preferences = preferences
        self.on_preferences_changed = on_preferences_changed
        self.action_store = action_store
        self.on_edit_actions = on_edit_actions
        self.field_memory: dict[str, str] = {}  # last values typed into {fields}, this session only
        self.action_buttons: list[Gtk.Button] = []
        self.compact = False
        self.set_size_request(PANEL_WIDTH, -1)
        self.get_style_context().add_class("panel")
        self.scroller = Gtk.ScrolledWindow()
        self.scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.scroller.set_shadow_type(Gtk.ShadowType.NONE)
        self.scroller.set_overlay_scrolling(True)
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        content.get_style_context().add_class("panel-inner")
        title = Gtk.Label(label="AÇÕES RÁPIDAS", xalign=0)
        title.get_style_context().add_class("panel-title")
        title.set_margin_start(4)
        title.set_margin_bottom(8)
        content.pack_start(title, False, False, 0)
        self.actions_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        content.pack_start(self.actions_box, False, False, 0)
        self.reload_actions()
        edit_button = Gtk.Button()
        edit_button.add(self.button_content("＋", "Editar ações…", link=True))
        edit_button.set_relief(Gtk.ReliefStyle.NONE)
        edit_button.set_tooltip_text("Adicionar, editar e reordenar ações")
        edit_button.get_style_context().add_class("action-button")
        edit_button.connect("clicked", lambda *_: self.on_edit_actions())
        content.pack_start(edit_button, False, False, 0)
        separator = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        separator.set_margin_top(10)
        separator.set_margin_bottom(10)
        content.pack_start(separator, False, False, 0)
        preferences_label = Gtk.Label(label="PREFERÊNCIAS", xalign=0)
        preferences_label.get_style_context().add_class("panel-section")
        preferences_label.set_margin_start(4)
        preferences_label.set_margin_bottom(4)
        content.pack_start(preferences_label, False, False, 0)
        self.effects = Gtk.CheckButton(label="Efeitos visuais")
        self.effects.connect("toggled", self.on_effects_toggled)
        content.pack_start(self.effects, False, False, 0)
        self.sound = Gtk.CheckButton(label="Som do teclado")
        self.sound.connect("toggled", self.on_sound_toggled)
        content.pack_start(self.sound, False, False, 0)
        hint = Gtk.Label(label="Ctrl+Shift+P abre a paleta", xalign=0)
        hint.get_style_context().add_class("panel-hint")
        hint.set_line_wrap(True)
        hint.set_margin_top(10)
        hint.set_margin_start(4)
        content.pack_start(hint, False, False, 0)
        self.scroller.add(content)
        self.pack_start(self.scroller, True, True, 0)
        self.sync()

    def reload_actions(self) -> None:
        for child in self.actions_box.get_children():
            child.destroy()
        self.action_buttons = []
        for action in self.action_store.load():
            button = Gtk.Button()
            # "…" signals that the action asks for fields first.
            label = action.label + (" …" if command_fields(action.command) else "")
            button.add(self.button_content("›", label, warning=action.confirm))
            button.set_halign(Gtk.Align.FILL)
            button.set_relief(Gtk.ReliefStyle.NONE)
            button.get_style_context().add_class("action-button")
            button.connect("clicked", lambda _button, value=action: self.run_action(value))
            button.set_tooltip_text(f"Executar: {action.command}")
            self.action_buttons.append(button)
            self.actions_box.pack_start(button, False, False, 0)
        self.actions_box.show_all()

    @staticmethod
    def button_content(marker: str, text: str, warning: bool = False, link: bool = False) -> Gtk.Box:
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        dot = Gtk.Label(label=marker)
        dot.get_style_context().add_class("action-dot")
        box.pack_start(dot, False, False, 0)
        label = Gtk.Label(label=text, xalign=0)
        label.set_ellipsize(Pango.EllipsizeMode.END)
        if link:
            label.get_style_context().add_class("panel-link")
        box.pack_start(label, True, True, 0)
        if warning:
            mark = Gtk.Label(label="●")
            mark.set_tooltip_text("Pede confirmação")
            mark.get_style_context().add_class("action-warning")
            box.pack_end(mark, False, False, 0)
        return box

    def run_action(self, action: QuickAction) -> None:
        command = action.command
        parent = self.get_toplevel()
        if command_fields(command):
            dialog = FieldsDialog(parent if isinstance(parent, Gtk.Window) else None, action, self.field_memory)
            response = dialog.run()
            command = dialog.command() if response == Gtk.ResponseType.OK else ""
            if command:
                dialog.remember()
            dialog.destroy()
            if not command:
                return
        if action.confirm:
            parent = self.get_toplevel()
            dialog = Gtk.MessageDialog(
                transient_for=parent if isinstance(parent, Gtk.Window) else None,
                modal=True,
                message_type=Gtk.MessageType.WARNING,
                buttons=Gtk.ButtonsType.NONE,
                text=f"Executar “{action.label}”?",
            )
            dialog.format_secondary_text(command)
            dialog.add_buttons("Cancelar", Gtk.ResponseType.CANCEL, "Executar", Gtk.ResponseType.OK)
            response = dialog.run()
            dialog.destroy()
            if response != Gtk.ResponseType.OK:
                return
        self.run_command(command)

    def set_compact(self, compact: bool) -> None:
        if compact == self.compact:
            return
        self.compact = compact
        self.set_size_request(COMPACT_PANEL_WIDTH if compact else PANEL_WIDTH, -1)
        context = self.get_style_context()
        if compact:
            context.add_class("compact")
        else:
            context.remove_class("compact")

    def run_command(self, command: str) -> None:
        terminal = self.get_terminal()
        if terminal is not None:
            terminal.run_command(command)

    def sync(self) -> None:
        self.effects.handler_block_by_func(self.on_effects_toggled)
        self.sound.handler_block_by_func(self.on_sound_toggled)
        self.effects.set_active(self.preferences.effects)
        self.sound.set_active(self.preferences.sound)
        self.effects.handler_unblock_by_func(self.on_effects_toggled)
        self.sound.handler_unblock_by_func(self.on_sound_toggled)

    def on_effects_toggled(self, checkbox) -> None:
        self.preferences.effects = checkbox.get_active()
        self.on_preferences_changed()

    def on_sound_toggled(self, checkbox) -> None:
        self.preferences.sound = checkbox.get_active()
        self.on_preferences_changed()


class FieldsDialog(Gtk.Dialog):
    """Asks for the {fields} of a saved command, with a live preview."""

    def __init__(self, parent: Gtk.Window | None, action: QuickAction, memory: dict[str, str]) -> None:
        super().__init__(title=action.label, transient_for=parent, modal=True)
        self.action = action
        self.memory = memory
        self.add_buttons("Cancelar", Gtk.ResponseType.CANCEL, "Executar", Gtk.ResponseType.OK)
        mark_suggested(self)
        self.set_default_response(Gtk.ResponseType.OK)
        self.set_default_size(520, -1)
        grid = Gtk.Grid(column_spacing=12, row_spacing=10, margin=16)
        self.get_content_area().pack_start(grid, True, True, 0)
        self.entries: dict[str, Gtk.Entry] = {}
        self.required: set[str] = set()
        for row, field in enumerate(command_fields(action.command)):
            label = Gtk.Label(label=field.name.replace("_", " ").capitalize(), xalign=0)
            entry = Gtk.Entry(text=memory.get(field.name, ""))
            entry.set_hexpand(True)
            entry.set_activates_default(True)
            if field.required:
                self.required.add(field.name)
                entry.set_placeholder_text("obrigatório")
            else:
                entry.set_placeholder_text(f"padrão: {field.default}" if field.default else "opcional")
            entry.connect("changed", lambda *_: self.update_preview())
            grid.attach(label, 0, row, 1, 1)
            grid.attach(entry, 1, row, 1, 1)
            self.entries[field.name] = entry
        self.preview = Gtk.Label(xalign=0, selectable=True)
        self.preview.set_line_wrap(True)
        self.preview.set_line_wrap_mode(Pango.WrapMode.CHAR)
        self.preview.set_max_width_chars(60)
        self.preview.get_style_context().add_class("monospace")
        grid.attach(self.preview, 0, len(self.entries), 2, 1)
        self.show_all()
        self.update_preview()

    def values(self) -> dict[str, str]:
        return {name: entry.get_text().strip() for name, entry in self.entries.items()}

    def command(self) -> str:
        values = self.values()
        if any(not values[name] for name in self.required):
            return ""
        return fill_command(self.action.command, values)

    def remember(self) -> None:
        self.memory.update({name: value for name, value in self.values().items() if value})

    def update_preview(self) -> None:
        values = self.values()
        missing = [name for name in self.required if not values[name]]
        self.set_response_sensitive(Gtk.ResponseType.OK, not missing)
        self.preview.set_text("$ " + fill_command(self.action.command, values))


class ActionFormDialog(Gtk.Dialog):
    def __init__(self, parent: Gtk.Window, action: QuickAction | None = None) -> None:
        super().__init__(title="Ação rápida", transient_for=parent, modal=True)
        self.action = action
        self.add_buttons("Cancelar", Gtk.ResponseType.CANCEL, "Salvar", Gtk.ResponseType.OK)
        mark_suggested(self)
        grid = Gtk.Grid(column_spacing=12, row_spacing=10, margin=16)
        self.get_content_area().pack_start(grid, True, True, 0)
        self.label_entry = Gtk.Entry(text=action.label if action else "")
        self.command_entry = Gtk.Entry(text=action.command if action else "")
        self.confirm = Gtk.CheckButton(label="Pedir confirmação antes de executar")
        self.confirm.set_active(action.confirm if action else False)
        grid.attach(Gtk.Label(label="Nome", xalign=0), 0, 0, 1, 1)
        grid.attach(self.label_entry, 1, 0, 1, 1)
        grid.attach(Gtk.Label(label="Comando", xalign=0), 0, 1, 1, 1)
        grid.attach(self.command_entry, 1, 1, 1, 1)
        grid.attach(self.confirm, 1, 2, 1, 1)
        self.label_entry.set_hexpand(True)
        self.command_entry.set_placeholder_text("ex.: nmap -sV {alvo}")
        hint = Gtk.Label(
            label="Campos: {alvo} é perguntado ao executar; {porta=80} tem valor padrão. "
            "Os valores são protegidos com aspas automaticamente.",
            xalign=0,
        )
        hint.set_line_wrap(True)
        hint.set_max_width_chars(60)
        hint.get_style_context().add_class("panel-hint")
        grid.attach(hint, 1, 3, 1, 1)
        self.set_default_size(520, -1)
        self.show_all()

    def value(self) -> QuickAction | None:
        label = self.label_entry.get_text().strip()
        command = self.command_entry.get_text().strip()
        if not label or not command:
            return None
        identifier = self.action.identifier if self.action else f"custom-{uuid.uuid4().hex[:10]}"
        return QuickAction(identifier, label, command, self.confirm.get_active())


class ActionEditorDialog(Gtk.Dialog):
    def __init__(self, parent: Gtk.Window, store: ActionStore) -> None:
        super().__init__(title="Editar ações rápidas", transient_for=parent, modal=True)
        self.store = store
        self.actions = store.load()
        self.add_buttons("Cancelar", Gtk.ResponseType.CANCEL, "Salvar", Gtk.ResponseType.OK)
        mark_suggested(self)
        body = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8, margin=12)
        self.get_content_area().pack_start(body, True, True, 0)
        self.listbox = Gtk.ListBox()
        self.listbox.set_selection_mode(Gtk.SelectionMode.SINGLE)
        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_min_content_width(260)
        scroller.set_min_content_height(260)
        self.set_default_size(520, 380)
        scroller.add(self.listbox)
        body.pack_start(scroller, True, True, 0)
        controls = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        for label, callback in (
            ("Adicionar", self.add_action),
            ("Editar", self.edit_action),
            ("Remover", self.remove_action),
            ("Mover ↑", lambda *_: self.move_action(-1)),
            ("Mover ↓", lambda *_: self.move_action(1)),
        ):
            button = Gtk.Button(label=label)
            button.connect("clicked", callback)
            controls.pack_start(button, False, False, 0)
        body.pack_start(controls, False, False, 0)
        self.refresh()
        self.show_all()

    def refresh(self, selected: int = 0) -> None:
        for child in self.listbox.get_children():
            child.destroy()
        for action in self.actions:
            suffix = "  ⚠" if action.confirm else ""
            row = Gtk.ListBoxRow()
            row.add(Gtk.Label(label=action.label + suffix, xalign=0, margin=8))
            self.listbox.add(row)
        self.listbox.show_all()
        row = self.listbox.get_row_at_index(min(selected, len(self.actions) - 1))
        if row is not None:
            self.listbox.select_row(row)

    def selected_index(self) -> int:
        row = self.listbox.get_selected_row()
        return row.get_index() if row is not None else -1

    def add_action(self, _button) -> None:
        dialog = ActionFormDialog(self)
        if dialog.run() == Gtk.ResponseType.OK:
            action = dialog.value()
            if action is not None:
                self.actions.append(action)
                self.refresh(len(self.actions) - 1)
        dialog.destroy()

    def edit_action(self, _button) -> None:
        index = self.selected_index()
        if index < 0:
            return
        dialog = ActionFormDialog(self, self.actions[index])
        if dialog.run() == Gtk.ResponseType.OK:
            action = dialog.value()
            if action is not None:
                self.actions[index] = action
                self.refresh(index)
        dialog.destroy()

    def remove_action(self, _button) -> None:
        index = self.selected_index()
        if index >= 0:
            self.actions.pop(index)
            self.refresh(max(0, index - 1))

    def move_action(self, delta: int) -> None:
        index = self.selected_index()
        target = index + delta
        if index < 0 or not 0 <= target < len(self.actions):
            return
        self.actions[index], self.actions[target] = self.actions[target], self.actions[index]
        self.refresh(target)


class ConnectionEditorDialog(Gtk.Dialog):
    def __init__(self, parent: Gtk.Window, themes: ThemeManager, connection: Connection | None) -> None:
        super().__init__(title="Conexão SSH", transient_for=parent, modal=True)
        self.connection = connection
        self.add_buttons("Cancelar", Gtk.ResponseType.CANCEL, "Salvar", Gtk.ResponseType.OK)
        mark_suggested(self)
        self.set_default_size(520, -1)
        page = FormPage()
        page.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.NEVER)
        self.get_content_area().pack_start(page, True, True, 0)
        self.name_entry = Gtk.Entry(text=connection.name if connection else "")
        self.name_entry.set_placeholder_text("ex.: Produção — banco de dados")
        self.destination = Gtk.Entry(text=connection.destination if connection else "")
        self.destination.set_placeholder_text("usuário@host ou alias do ~/.ssh/config")
        self.port = Gtk.SpinButton.new_with_range(0, 65535, 1)
        self.port.set_value(connection.port or 0 if connection else 0)
        self.identity = Gtk.Entry(text=connection.identity_file if connection else "")
        self.identity.set_placeholder_text("opcional, ex.: ~/.ssh/id_ed25519")
        self.options = Gtk.Entry(text=connection.options if connection else "")
        self.options.set_placeholder_text("opcional, ex.: -J bastiao -A")
        self.theme = Gtk.ComboBoxText()
        self.theme.append("", "Mesmo tema da janela")
        for theme in themes.all():
            self.theme.append(theme.identifier, theme.name)
        self.theme.set_active_id(connection.theme if connection and connection.theme else "")
        self.confirm_switch = Gtk.Switch(active=connection.confirm if connection else False)
        page.heading("CONEXÃO")
        page.field("Nome", self.name_entry)
        page.field("Destino", self.destination)
        page.field("Porta (0 = padrão)", self.port)
        page.field("Chave (identity file)", self.identity)
        page.field("Opções extras do ssh", self.options)
        page.heading("SEGURANÇA VISUAL")
        page.field("Tema da aba", self.theme, "Use um tema chamativo, como Alerta Vermelho, para servidores de produção.")
        page.field("Confirmar antes de conectar", self.confirm_switch)
        page.hint("Senhas nunca são guardadas: o ssh pede a senha ou usa sua chave/agente, como de costume.")
        self.show_all()

    def value(self, identifier: str) -> Connection:
        port = self.port.get_value_as_int()
        connection = Connection(
            identifier=identifier,
            name=" ".join(self.name_entry.get_text().split()),
            destination=self.destination.get_text().strip(),
            port=port or None,
            identity_file=self.identity.get_text().strip(),
            options=self.options.get_text().strip(),
            theme=self.theme.get_active_id() or "",
            confirm=self.confirm_switch.get_active(),
        )
        validate_connection(connection)
        return connection


class SSHManagerDialog(Gtk.Dialog):
    """Saved connections plus hosts from ~/.ssh/config."""

    def __init__(self, parent: Gtk.Window, store: ConnectionStore, themes: ThemeManager) -> None:
        super().__init__(title="Conexões SSH", transient_for=parent, modal=True)
        self.store = store
        self.themes = themes
        self.add_buttons("Fechar", Gtk.ResponseType.CANCEL, "Conectar", Gtk.ResponseType.OK)
        mark_suggested(self)
        self.set_default_size(620, 420)
        body = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8, margin=12)
        self.get_content_area().pack_start(body, True, True, 0)
        self.listbox = Gtk.ListBox()
        self.listbox.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.listbox.connect("row-activated", lambda *_: self.response(Gtk.ResponseType.OK))
        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_min_content_width(320)
        scroller.add(self.listbox)
        body.pack_start(scroller, True, True, 0)
        controls = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        for label, callback in (("Nova…", self.add), ("Editar…", self.edit), ("Remover", self.remove)):
            button = Gtk.Button(label=label)
            button.connect("clicked", lambda *_args, action=callback: action())
            controls.pack_start(button, False, False, 0)
        hint = Gtk.Label(label="Hosts do ~/.ssh/config aparecem automaticamente; edite um para personalizá-lo.", xalign=0)
        hint.set_line_wrap(True)
        hint.set_max_width_chars(22)
        hint.get_style_context().add_class("panel-hint")
        controls.pack_end(hint, False, False, 0)
        body.pack_start(controls, False, False, 0)
        self.connections: list[Connection] = []
        self.refresh()
        self.show_all()

    def refresh(self, select: str | None = None) -> None:
        self.connections = self.store.load()
        for child in self.listbox.get_children():
            child.destroy()
        for connection in self.connections:
            row = Gtk.ListBoxRow()
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, margin=8)
            title = Gtk.Label(xalign=0)
            badge = "  · do ~/.ssh/config" if connection.from_ssh_config else ""
            lock = "⚠ " if connection.confirm else ""
            title.set_markup(f"<b>{GLib.markup_escape_text(lock + connection.name)}</b>{GLib.markup_escape_text(badge)}")
            detail = Gtk.Label(label=connection.command_line(), xalign=0)
            detail.set_ellipsize(Pango.EllipsizeMode.END)
            detail.get_style_context().add_class("panel-hint")
            box.pack_start(title, False, False, 0)
            box.pack_start(detail, False, False, 0)
            row.add(box)
            self.listbox.add(row)
        self.listbox.show_all()
        index = next((i for i, c in enumerate(self.connections) if c.identifier == select), 0)
        row = self.listbox.get_row_at_index(index)
        if row is not None:
            self.listbox.select_row(row)

    def selected_connection(self) -> Connection | None:
        row = self.listbox.get_selected_row()
        return self.connections[row.get_index()] if row is not None and row.get_index() < len(self.connections) else None

    def saved(self) -> list[Connection]:
        return [connection for connection in self.connections if not connection.from_ssh_config]

    def run_editor(self, connection: Connection | None, identifier: str) -> Connection | None:
        editor = ConnectionEditorDialog(self, self.themes, connection)
        result = None
        while editor.run() == Gtk.ResponseType.OK:
            try:
                result = editor.value(identifier)
                break
            except (ConnectionError, ValueError) as error:
                show_error(editor, "Conexão inválida", str(error))
        editor.destroy()
        return result

    def add(self) -> None:
        taken = {connection.identifier for connection in self.connections}
        created = self.run_editor(None, "")
        if created is None:
            return
        created = dataclasses.replace(created, identifier=self.store.unique_identifier(created.name, taken))
        self.persist(self.saved() + [created], created.identifier)

    def edit(self) -> None:
        current = self.selected_connection()
        if current is None:
            return
        taken = {connection.identifier for connection in self.connections}
        base = self.store.promote(current, taken) if current.from_ssh_config else current
        updated = self.run_editor(base, base.identifier)
        if updated is None:
            return
        saved = [updated if item.identifier == updated.identifier else item for item in self.saved()]
        if current.from_ssh_config:
            saved.append(updated)
        self.persist(saved, updated.identifier)

    def remove(self) -> None:
        current = self.selected_connection()
        if current is None:
            return
        if current.from_ssh_config:
            show_error(self, "Host do ~/.ssh/config", "Remova este host editando o seu ~/.ssh/config.")
            return
        if confirm(self, f"Remover “{current.name}”?", "Somente a conexão salva é apagada.", "Remover"):
            self.persist([item for item in self.saved() if item.identifier != current.identifier])

    def persist(self, connections: list[Connection], select: str | None = None) -> None:
        if not self.store.save(connections):
            show_error(self, "Não foi possível salvar", str(self.store.path))
        self.refresh(select)


class CommandPaletteDialog(Gtk.Dialog):
    def __init__(
        self,
        parent: Gtk.Window,
        items: list[tuple[str, str, Callable[[], None]]],
    ) -> None:
        super().__init__(title="Paleta de comandos", transient_for=parent, modal=True)
        self.items = items
        self.selected_callback: Callable[[], None] | None = None
        self.add_button("Fechar", Gtk.ResponseType.CANCEL)
        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=7, margin=12)
        self.get_content_area().pack_start(body, True, True, 0)
        self.entry = Gtk.SearchEntry()
        self.entry.set_placeholder_text("Pesquisar ações, perfis e temas…")
        self.entry.connect("search-changed", lambda *_: self.refresh())
        self.entry.connect("activate", self.activate_first)
        body.pack_start(self.entry, False, False, 0)
        self.listbox = Gtk.ListBox()
        self.listbox.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.listbox.connect("row-activated", self.on_row_activated)
        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_min_content_height(240)
        self.set_default_size(min(620, max(360, parent.get_allocated_width() - 80)), 440)
        scroller.add(self.listbox)
        body.pack_start(scroller, True, True, 0)
        self.refresh()
        self.show_all()
        self.entry.grab_focus()

    def filtered_items(self) -> list[tuple[str, str, Callable[[], None]]]:
        query = self.entry.get_text().strip().casefold()
        return [
            item
            for item in self.items
            if not query or query in f"{item[0]} {item[1]}".casefold()
        ]

    def refresh(self) -> None:
        for child in self.listbox.get_children():
            child.destroy()
        for label, category, callback in self.filtered_items():
            row = Gtk.ListBoxRow()
            row.palette_callback = callback
            content = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10, margin=8)
            title = Gtk.Label(label=label, xalign=0)
            title.set_ellipsize(Pango.EllipsizeMode.END)
            content.pack_start(title, True, True, 0)
            category_label = Gtk.Label(label=category, xalign=1)
            category_label.get_style_context().add_class("palette-category")
            content.pack_end(category_label, False, False, 0)
            row.add(content)
            self.listbox.add(row)
        self.listbox.show_all()
        first = self.listbox.get_row_at_index(0)
        if first is not None:
            self.listbox.select_row(first)

    def activate_first(self, _entry) -> None:
        row = self.listbox.get_selected_row() or self.listbox.get_row_at_index(0)
        if row is not None:
            self.on_row_activated(self.listbox, row)

    def on_row_activated(self, _listbox, row) -> None:
        self.selected_callback = row.palette_callback
        self.response(Gtk.ResponseType.OK)


class BootScreen(Gtk.Box):
    def __init__(self, sound: SoundPlayer, finished: Callable[[], bool]) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.get_style_context().add_class("boot")
        self.sound = sound
        self.finished = finished
        self.alive = True
        self.source_id = 0
        self.connect("destroy", self.on_destroy)
        self.lines = (
            "[  OK  ] Inicializando núcleo visual...",
            "[  OK  ] Carregando interface VTE...",
            "[  OK  ] Restaurando preferências...",
            "[  OK  ] Ativando sessões em abas...",
            "[  OK  ] Sincronizando matriz gráfica...",
            "[ READY ] Acesso autorizado.",
        )
        self.index = 0
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        card.get_style_context().add_class("boot-card")
        card.set_halign(Gtk.Align.CENTER)
        card.set_valign(Gtk.Align.CENTER)
        card.set_vexpand(True)
        logo = Gtk.Label(label="HACKER\nTERMINAL")
        logo.set_justify(Gtk.Justification.CENTER)
        logo.get_style_context().add_class("boot-logo")
        card.pack_start(logo, False, False, 0)
        subtitle = Gtk.Label(label=f"SYSTEM BOOT // LINUX // v{VERSION}")
        subtitle.get_style_context().add_class("boot-subtitle")
        card.pack_start(subtitle, False, False, 0)
        self.progress = Gtk.ProgressBar()
        self.progress.set_margin_top(10)
        card.pack_start(self.progress, False, False, 0)
        self.status = Gtk.Label(label="", xalign=0, yalign=0)
        self.status.set_line_wrap(True)
        self.status.set_size_request(-1, 7 * 18)
        self.status.get_style_context().add_class("boot-status")
        card.pack_start(self.status, False, False, 0)
        self.pack_start(card, True, True, 0)

    def begin(self) -> bool:
        if not self.alive:
            return False
        self.sound.play()
        self.source_id = GLib.timeout_add(220, self.step)
        return False

    def step(self) -> bool:
        if not self.alive:
            self.source_id = 0
            return False
        if self.index < len(self.lines):
            text = self.status.get_text()
            self.status.set_text(f"{text}\n{self.lines[self.index]}" if text else self.lines[self.index])
            self.index += 1
            self.progress.set_fraction(self.index / len(self.lines))
            return True
        self.source_id = GLib.timeout_add(240, self.complete)
        return False

    def complete(self) -> bool:
        self.source_id = 0
        return self.finished() if self.alive else False

    def on_destroy(self, _widget) -> None:
        self.alive = False
        if self.source_id:
            GLib.source_remove(self.source_id)
            self.source_id = 0


class FormPage(Gtk.ScrolledWindow):
    """A scrollable two-column settings page with section headings."""

    def __init__(self) -> None:
        super().__init__()
        self.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.grid = Gtk.Grid(column_spacing=14, row_spacing=10, margin=16)
        self.add(self.grid)
        self.row = 0

    def heading(self, text: str) -> None:
        label = Gtk.Label(label=text, xalign=0)
        label.get_style_context().add_class("dialog-heading")
        self.grid.attach(label, 0, self.row, 2, 1)
        self.row += 1

    def field(self, text: str, widget: Gtk.Widget, tooltip: str | None = None) -> None:
        label = Gtk.Label(label=text, xalign=0)
        label.set_line_wrap(True)
        if tooltip:
            label.set_tooltip_text(tooltip)
            widget.set_tooltip_text(tooltip)
        self.grid.attach(label, 0, self.row, 1, 1)
        widget.set_halign(Gtk.Align.END if isinstance(widget, Gtk.Switch) else Gtk.Align.FILL)
        widget.set_valign(Gtk.Align.CENTER)
        widget.set_hexpand(not isinstance(widget, Gtk.Switch))
        self.grid.attach(widget, 1, self.row, 1, 1)
        self.row += 1

    def full(self, widget: Gtk.Widget, column: int = 0, width: int = 2) -> None:
        self.grid.attach(widget, column, self.row, width, 1)
        self.row += 1

    def hint(self, text: str, column: int = 0, width: int = 2) -> Gtk.Label:
        label = Gtk.Label(label=text, xalign=0)
        label.set_line_wrap(True)
        label.get_style_context().add_class("panel-hint")
        self.full(label, column, width)
        return label


def choice_combo(options: tuple[tuple[str, str], ...], selected: str) -> Gtk.ComboBoxText:
    combo = Gtk.ComboBoxText()
    for identifier, label in options:
        combo.append(identifier, label)
    if not combo.set_active_id(selected):
        combo.set_active(0)
    return combo


class ShortcutCaptureDialog(Gtk.Dialog):
    """Wait for one key combination. Backspace disables, Esc cancels."""

    def __init__(self, parent: Gtk.Window, label: str) -> None:
        super().__init__(title="Definir atalho", transient_for=parent, modal=True)
        self.accelerator: str | None = None
        self.add_button("Cancelar", Gtk.ResponseType.CANCEL)
        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, margin=20)
        title = Gtk.Label(xalign=0)
        title.set_markup(f"<b>{GLib.markup_escape_text(label)}</b>")
        body.pack_start(title, False, False, 0)
        body.pack_start(Gtk.Label(label="Pressione a nova combinação de teclas.", xalign=0), False, False, 0)
        hint = Gtk.Label(label="Backspace desativa o atalho · Esc cancela", xalign=0)
        hint.get_style_context().add_class("panel-hint")
        body.pack_start(hint, False, False, 0)
        self.get_content_area().pack_start(body, True, True, 0)
        self.connect("key-press-event", self.on_key_press)
        self.show_all()

    def on_key_press(self, _dialog, event) -> bool:
        keyval = Gdk.keyval_to_lower(event.keyval)
        mods = event.state & MODIFIER_MASK
        if keyval == Gdk.KEY_Escape and not mods:
            self.response(Gtk.ResponseType.CANCEL)
            return True
        if keyval == Gdk.KEY_BackSpace and not mods:
            self.accelerator = ""
            self.response(Gtk.ResponseType.OK)
            return True
        if not Gtk.accelerator_valid(keyval, mods):
            return True  # a lone modifier; keep waiting
        self.accelerator = accelerator_name(keyval, mods)
        self.response(Gtk.ResponseType.OK)
        return True


class ShortcutsEditor(Gtk.Box):
    def __init__(self, overrides: dict[str, str]) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8, margin=16)
        self.bindings = ShortcutMap(overrides).bindings
        self.buttons: dict[str, Gtk.Button] = {}
        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        grid = Gtk.Grid(column_spacing=12, row_spacing=4)
        for row, action in enumerate(SHORTCUT_ACTIONS):
            label = Gtk.Label(label=action.label, xalign=0)
            label.set_hexpand(True)
            button = Gtk.Button()
            button.set_tooltip_text("Clique para alterar")
            button.connect("clicked", lambda _button, value=action: self.capture(value))
            reset = Gtk.Button.new_from_icon_name("edit-undo-symbolic", Gtk.IconSize.MENU)
            reset.set_relief(Gtk.ReliefStyle.NONE)
            reset.set_tooltip_text("Restaurar o padrão")
            reset.connect("clicked", lambda _button, value=action: self.set_binding(value.identifier, value.default))
            grid.attach(label, 0, row, 1, 1)
            grid.attach(button, 1, row, 1, 1)
            grid.attach(reset, 2, row, 1, 1)
            self.buttons[action.identifier] = button
        scroller.add(grid)
        self.pack_start(scroller, True, True, 0)
        self.warning = Gtk.Label(xalign=0)
        self.warning.set_line_wrap(True)
        self.warning.get_style_context().add_class("panel-hint")
        self.pack_start(self.warning, False, False, 0)
        reset_all = Gtk.Button(label="Restaurar todos os atalhos")
        reset_all.set_halign(Gtk.Align.START)
        reset_all.connect("clicked", lambda *_: self.reset_all())
        self.pack_start(reset_all, False, False, 0)
        self.refresh()

    def capture(self, action) -> None:
        dialog = ShortcutCaptureDialog(self.get_toplevel(), action.label)
        response = dialog.run()
        accelerator = dialog.accelerator
        dialog.destroy()
        if response == Gtk.ResponseType.OK and accelerator is not None:
            self.set_binding(action.identifier, accelerator)

    def set_binding(self, identifier: str, value: str) -> None:
        self.bindings[identifier] = value
        self.refresh()

    def reset_all(self) -> None:
        self.bindings = ShortcutMap().bindings
        self.refresh()

    def overrides(self) -> dict[str, str]:
        return ShortcutMap(self.bindings).overrides()

    def refresh(self) -> None:
        for identifier, button in self.buttons.items():
            button.set_label(accelerator_label(self.bindings[identifier]))
            button.get_child().get_style_context().add_class("shortcut-label")
        conflicts = ShortcutMap(self.bindings).conflicts()
        labels = {action.identifier: action.label for action in SHORTCUT_ACTIONS}
        if conflicts:
            names = ["“" + "” e “".join(labels[item] for item in dict.fromkeys(ids)) + "”" for ids in conflicts.values()]
            self.warning.set_text("Conflito: " + "; ".join(names) + " usam a mesma tecla. Só a primeira ação será executada.")
        else:
            self.warning.set_text("Clique em um atalho para gravar uma nova combinação.")


class ThemeEditorDialog(Gtk.Dialog):
    """Create or edit a user theme with color pickers."""

    LABELS = {
        "background": "Fundo da janela",
        "surface": "Superfícies (cabeçalho, painel)",
        "foreground": "Texto da interface",
        "accent": "Destaque",
        "border": "Bordas",
        "muted": "Texto secundário",
        "danger": "Alerta",
        "terminal_background": "Fundo do terminal",
        "terminal_foreground": "Texto do terminal",
        "cursor": "Cursor",
        "selection_background": "Fundo da seleção",
        "selection_foreground": "Texto da seleção",
        "matrix_color": "Cor da chuva digital",
    }
    ANSI_NAMES = ("Preto", "Vermelho", "Verde", "Amarelo", "Azul", "Magenta", "Ciano", "Branco")

    def __init__(self, parent: Gtk.Window, manager: ThemeManager, base: Theme) -> None:
        editing = not base.builtin
        super().__init__(title="Editar tema" if editing else "Novo tema", transient_for=parent, modal=True)
        self.manager = manager
        self.base = base
        self.editing = editing
        self.add_buttons("Cancelar", Gtk.ResponseType.CANCEL, "Salvar tema", Gtk.ResponseType.OK)
        mark_suggested(self)
        self.set_default_size(560, 620)
        page = FormPage()
        self.get_content_area().pack_start(page, True, True, 0)
        self.name_entry = Gtk.Entry(text=base.name if editing else f"{base.name} (personalizado)")
        self.author_entry = Gtk.Entry(text=base.author if editing else os.environ.get("USER", ""))
        page.heading("IDENTIDADE")
        page.field("Nome", self.name_entry)
        page.field("Autor", self.author_entry)
        self.colors: dict[str, Gtk.ColorButton] = {}
        sections = {"interface": "INTERFACE", "terminal": "TERMINAL", "effects": "EFEITOS"}
        current = None
        for section, _key, attribute in THEME_COLOR_FIELDS:
            if section != current:
                page.heading(sections[section])
                current = section
            button = Gtk.ColorButton.new_with_rgba(self.parse(getattr(base, attribute)))
            button.set_title(self.LABELS[attribute])
            self.colors[attribute] = button
            page.field(self.LABELS[attribute], button)
        self.scanlines = Gtk.SpinButton.new_with_range(0, 1, 0.01)
        self.scanlines.set_digits(2)
        self.scanlines.set_value(base.scanline_opacity)
        page.field("Intensidade das scanlines", self.scanlines)
        self.crt: dict[str, Gtk.Scale] = {}
        page.heading("TELA CRT (com efeitos visuais ligados)")
        for key, label in CRT_LABELS:
            scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 1, 0.05)
            scale.set_digits(2)
            scale.set_value(getattr(base, key))
            scale.set_value_pos(Gtk.PositionType.RIGHT)
            self.crt[key] = scale
            page.field(label, scale)
        self.rain = Gtk.Switch(active=base.rain)
        page.field("Mostrar chuva digital", self.rain)
        self.font_entry = Gtk.Entry(text=base.font or "")
        self.font_entry.set_placeholder_text("Opcional, ex.: Terminus")
        page.field("Fonte sugerida", self.font_entry)
        page.heading("PALETA ANSI")
        ansi_grid = Gtk.Grid(column_spacing=6, row_spacing=4, column_homogeneous=True)
        self.ansi: list[Gtk.ColorButton] = []
        for index, color in enumerate(base.ansi):
            button = Gtk.ColorButton.new_with_rgba(self.parse(color))
            name = self.ANSI_NAMES[index % 8] + (" claro" if index >= 8 else "")
            button.set_title(name)
            button.set_tooltip_text(name)
            ansi_grid.attach(button, index % 8, index // 8 * 2, 1, 1)
            if index < 8:
                caption = Gtk.Label(label=self.ANSI_NAMES[index][:3])
                caption.get_style_context().add_class("swatch-label")
                ansi_grid.attach(caption, index, 2, 1, 1)
            self.ansi.append(button)
        page.full(ansi_grid)
        page.hint("Linha de cima: cores normais · linha do meio: variantes claras.")
        self.show_all()

    @staticmethod
    def parse(value: str) -> Gdk.RGBA:
        color = Gdk.RGBA()
        color.parse(value)
        return color

    @staticmethod
    def hex(button: Gtk.ColorButton) -> str:
        color = button.get_rgba()
        return "#" + "".join(f"{round(channel * 255):02x}" for channel in (color.red, color.green, color.blue))

    def build_theme(self) -> Theme:
        name = self.name_entry.get_text().strip()
        if not name:
            raise ThemeError("informe um nome para o tema")
        identifier = self.base.identifier if self.editing else self.manager.unique_identifier(name)
        values = {attribute: self.hex(button) for attribute, button in self.colors.items()}
        return dataclasses.replace(
            self.base,
            identifier=identifier,
            name=name,
            author=self.author_entry.get_text().strip() or "Desconhecido",
            scanline_opacity=round(self.scanlines.get_value(), 2),
            rain=self.rain.get_active(),
            font=self.font_entry.get_text().strip() or None,
            **{key: round(scale.get_value(), 2) for key, scale in self.crt.items()},
            ansi=tuple(self.hex(button) for button in self.ansi),
            path=None,
            builtin=False,
            **values,
        )


class ProfileEditorDialog(Gtk.Dialog):
    """Create a profile from the current settings, or edit a custom one."""

    def __init__(self, parent: Gtk.Window, manager: ProfileManager, profile: Profile | None) -> None:
        super().__init__(
            title="Editar perfil" if profile else "Novo perfil",
            transient_for=parent,
            modal=True,
        )
        self.manager = manager
        self.profile = profile
        self.add_buttons("Cancelar", Gtk.ResponseType.CANCEL, "Salvar perfil", Gtk.ResponseType.OK)
        mark_suggested(self)
        self.set_default_size(500, -1)
        page = FormPage()
        page.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.NEVER)
        self.get_content_area().pack_start(page, True, True, 0)
        self.name_entry = Gtk.Entry(text=profile.name if profile else "")
        self.name_entry.set_placeholder_text("ex.: Pentest, Projeto X")
        self.name_entry.set_activates_default(True)
        self.set_default_response(Gtk.ResponseType.OK)
        self.description_entry = Gtk.Entry(text=profile.description if profile else "")
        self.directory = Gtk.FileChooserButton(title="Diretório inicial", action=Gtk.FileChooserAction.SELECT_FOLDER)
        start = Path(profile.working_directory).expanduser() if profile else Path.home()
        self.directory.set_filename(str(start if start.is_dir() else Path.home()))
        self.own_actions = Gtk.Switch(active=profile.own_actions if profile else False)
        page.heading("PERFIL")
        page.field("Nome", self.name_entry)
        page.field("Descrição", self.description_entry)
        page.field("Diretório inicial", self.directory)
        page.field(
            "Ações rápidas próprias",
            self.own_actions,
            "O perfil terá sua própria lista de ações, começando com uma cópia da atual.",
        )
        self.update_settings = Gtk.Switch(active=profile is None)
        if profile is not None:
            page.field("Atualizar com as configurações atuais", self.update_settings)
            page.hint("Desligado mantém o tema, a fonte e os demais ajustes salvos no perfil.")
        else:
            page.hint(
                "O perfil guarda o tema, a fonte, o shell, o cursor, a opacidade, os efeitos "
                "e o painel mostrados nas Preferências."
            )
        self.show_all()

    def directory_value(self) -> str:
        chosen = self.directory.get_filename()
        if not chosen:
            return "~"
        path = Path(chosen)
        try:
            return "~/" + str(path.relative_to(Path.home())) if path != Path.home() else "~"
        except ValueError:
            return str(path)

    def save(self, current: Preferences, current_actions: ActionStore) -> Profile:
        name = self.name_entry.get_text().strip()
        if not name:
            raise ProfileError("informe um nome para o perfil")
        identifier = self.profile.identifier if self.profile else self.manager.unique_identifier(name)
        description = self.description_entry.get_text().strip()
        own_actions = self.own_actions.get_active()
        if self.profile is None or self.update_settings.get_active():
            profile = profile_from_preferences(
                identifier, name, description, current, self.directory_value(), own_actions
            )
        else:
            profile = dataclasses.replace(
                self.profile,
                name=name,
                description=description,
                working_directory=self.directory_value(),
                own_actions=own_actions,
                path=None,
            )
        had_actions = self.profile is not None and self.profile.own_actions
        saved = self.manager.save_custom(profile)
        actions_path = self.manager.actions_path(saved.identifier)
        if actions_path is not None and not had_actions and not actions_path.exists():
            # Start the profile's list from the actions in use right now.
            ActionStore(actions_path).save(current_actions.load())
        return saved


class PreferencesDialog(Gtk.Dialog):
    CURSOR_SHAPES = (("block", "Bloco"), ("ibeam", "Barra"), ("underline", "Sublinhado"))
    CURSOR_BLINK = (("system", "Seguir o sistema"), ("on", "Piscar"), ("off", "Fixo"))

    def __init__(
        self,
        parent: Gtk.Window,
        preferences: Preferences,
        theme_manager: ThemeManager,
        profile_manager: ProfileManager,
        action_store: ActionStore | None = None,
    ) -> None:
        super().__init__(title="Preferências", transient_for=parent, modal=True)
        self.action_store = action_store or ActionStore()
        self.preferences = preferences
        self.theme_manager = theme_manager
        self.profile_manager = profile_manager
        self.add_buttons("Cancelar", Gtk.ResponseType.CANCEL, "Salvar", Gtk.ResponseType.OK)
        mark_suggested(self)
        self.set_default_response(Gtk.ResponseType.OK)
        self.set_resizable(True)
        self.set_default_size(min(600, max(400, parent.get_allocated_width() - 60)), 620)
        self.pages = Gtk.Notebook()
        self.pages.set_scrollable(True)
        self.get_content_area().pack_start(self.pages, True, True, 0)

        # --- Geral
        general = FormPage()
        self.scroller = general
        self.profile = Gtk.ComboBoxText()
        self.profile_ids: list[str] = []
        self.refresh_profiles(preferences.profile)
        self.panel = Gtk.Switch(active=preferences.panel_visible)
        self.restore_session = Gtk.Switch(active=preferences.restore_session)
        self.shell = Gtk.Entry(text=preferences.shell)
        self.shell.set_placeholder_text("Automático ($SHELL, zsh ou bash)")
        self.confirm_paste = Gtk.Switch(active=preferences.confirm_paste)
        self.bell_notify = Gtk.Switch(active=preferences.bell_notify)
        general.heading("PERFIL")
        general.field("Perfil", self.profile)
        self.profile_note = general.hint("", column=1, width=1)
        profile_actions = Gtk.FlowBox()
        profile_actions.set_selection_mode(Gtk.SelectionMode.NONE)
        profile_actions.set_halign(Gtk.Align.START)
        profile_actions.set_max_children_per_line(3)
        profile_actions.set_column_spacing(4)
        profile_actions.set_row_spacing(4)
        save_profile = Gtk.Button(label="Salvar como perfil…")
        save_profile.set_tooltip_text("Cria um perfil com as configurações mostradas neste diálogo")
        save_profile.connect("clicked", self.new_profile)
        self.edit_profile_button = Gtk.Button(label="Editar…")
        self.edit_profile_button.connect("clicked", self.edit_profile)
        self.delete_profile_button = Gtk.Button(label="Remover")
        self.delete_profile_button.connect("clicked", self.delete_profile)
        for button in (save_profile, self.edit_profile_button, self.delete_profile_button):
            profile_actions.add(button)
        general.full(profile_actions, column=1, width=1)
        general.heading("SESSÃO")
        general.field("Shell", self.shell, "Comando do shell, com argumentos. Vazio usa o shell de login.")
        self.shell_status = general.hint("", column=1, width=1)
        general.field("Restaurar sessão", self.restore_session)
        general.field("Painel lateral", self.panel)
        general.heading("SEGURANÇA E ALERTAS")
        general.field(
            "Confirmar colagem perigosa",
            self.confirm_paste,
            "Pergunta antes de colar várias linhas ou caracteres de controle.",
        )
        general.field("Avisar quando houver bell", self.bell_notify, "Marca a aba e a janela quando um programa toca o sinal.")
        self.shell_integration = Gtk.Switch(active=preferences.shell_integration)
        general.field(
            "Integração com o shell (zsh e bash)",
            self.shell_integration,
            "Marca cada comando: pular entre prompts, copiar a saída do último comando e avisos com o código de saída. Vale para novos painéis.",
        )
        self.command_marks = Gtk.Switch(active=preferences.command_marks)
        general.field("Marcar comandos na margem", self.command_marks, "Faixa ao lado de cada comando: cor de destaque se deu certo, vermelha se falhou.")
        self.notify_commands = Gtk.Switch(active=preferences.notify_commands)
        general.field(
            "Avisar quando um comando longo terminar",
            self.notify_commands,
            "Notificação do sistema quando um comando termina numa aba que você não está olhando.",
        )
        self.notify_after = Gtk.SpinButton.new_with_range(3, 3600, 1)
        self.notify_after.set_value(preferences.notify_after)
        general.field("Considerar longo a partir de (segundos)", self.notify_after)
        general.heading("TERMINAL SUSPENSO")
        self.dropdown_height = Gtk.SpinButton.new_with_range(25, 90, 5)
        self.dropdown_height.set_value(preferences.dropdown_height)
        general.field("Altura (% da tela)", self.dropdown_height)
        self.dropdown_autohide = Gtk.Switch(active=preferences.dropdown_autohide)
        general.field("Esconder ao perder o foco", self.dropdown_autohide)
        command = launch_command()
        if xfce_available():
            shortcut_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            self.dropdown_key = Gtk.Entry(text=DEFAULT_KEY, width_chars=10)
            self.dropdown_key.set_tooltip_text("Formato GTK: F12, <Super>grave, <Primary><Alt>t…")
            bind_button = Gtk.Button(label="Associar no XFCE")
            bind_button.connect("clicked", lambda *_: self.bind_dropdown_key(command))
            shortcut_row.pack_start(self.dropdown_key, False, False, 0)
            shortcut_row.pack_start(bind_button, False, False, 0)
            current = xfce_binding(DEFAULT_KEY)
            state = "já configurado" if current and "--dropdown" in current else "ainda não configurado"
            general.field("Atalho global", shortcut_row, f"{DEFAULT_KEY}: {state}. O atalho executa: {command}")
        else:
            general.hint(f"Para usar como terminal suspenso, crie um atalho global no seu ambiente gráfico que execute: {command}")
        self.pages.append_page(general, Gtk.Label(label="Geral"))

        # --- Aparência
        appearance = FormPage()
        self.theme = Gtk.ComboBoxText()
        self.theme_ids: list[str] = []
        self.refresh_themes(preferences.theme)
        theme_actions = Gtk.FlowBox()
        theme_actions.set_selection_mode(Gtk.SelectionMode.NONE)
        theme_actions.set_halign(Gtk.Align.START)
        theme_actions.set_max_children_per_line(5)
        theme_actions.set_min_children_per_line(3)
        theme_actions.set_column_spacing(4)
        theme_actions.set_row_spacing(4)
        self.edit_theme_button = Gtk.Button(label="Editar…")
        self.delete_theme_button = Gtk.Button(label="Remover")
        for label, callback in (
            ("Novo…", self.new_theme),
            (None, self.edit_theme),
            (None, self.delete_theme),
            ("Importar…", self.import_theme),
            ("Exportar…", self.export_theme),
        ):
            button = Gtk.Button(label=label) if label else (
                self.edit_theme_button if callback == self.edit_theme else self.delete_theme_button
            )
            button.connect("clicked", callback)
            theme_actions.add(button)
        self.font = Gtk.FontButton()
        chosen = choose_font(preferences.font)
        self.font.set_font_name(f"{chosen.family} {preferences.font_size}")
        self.opacity = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 30, 100, 5)
        self.opacity.set_value(preferences.opacity)
        self.opacity.set_value_pos(Gtk.PositionType.RIGHT)
        self.opacity.set_digits(0)
        self.boot = Gtk.Switch(active=preferences.boot)
        self.effects = Gtk.Switch(active=preferences.effects)
        self.sound = Gtk.Switch(active=preferences.sound)
        appearance.heading("TEMA")
        appearance.field("Tema", self.theme)
        appearance.full(theme_actions, column=1, width=1)
        suggestion = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.font_suggestion = Gtk.Label(xalign=0)
        self.font_suggestion.set_line_wrap(True)
        self.font_suggestion.get_style_context().add_class("panel-hint")
        self.use_suggested_font = Gtk.Button(label="Usar")
        self.use_suggested_font.connect("clicked", self.apply_suggested_font)
        suggestion.pack_start(self.font_suggestion, True, True, 0)
        suggestion.pack_start(self.use_suggested_font, False, False, 0)
        self.font_suggestion.set_no_show_all(True)
        self.use_suggested_font.set_no_show_all(True)
        appearance.full(suggestion, column=1, width=1)
        appearance.field("Fonte", self.font)
        appearance.field("Opacidade do fundo (%)", self.opacity)
        composited = parent.get_screen() is not None and parent.get_screen().is_composited()
        appearance.hint(
            "Transparência ativa." if composited else "A transparência requer um compositor de janelas ativo.",
            column=1,
            width=1,
        )
        appearance.heading("EFEITOS")
        appearance.field("Animação de abertura", self.boot)
        appearance.field("Efeitos visuais", self.effects)
        appearance.hint("A animação de abertura é aplicada na próxima janela.")
        self.pages.append_page(appearance, Gtk.Label(label="Aparência"))

        # --- Terminal
        terminal = FormPage()
        self.cursor_shape = choice_combo(self.CURSOR_SHAPES, preferences.cursor_shape)
        self.cursor_blink = choice_combo(self.CURSOR_BLINK, preferences.cursor_blink)
        self.scrollback = Gtk.SpinButton.new_with_range(1_000, 200_000, 1_000)
        self.scrollback.set_value(preferences.scrollback_lines)
        self.bold_is_bright = Gtk.Switch(active=preferences.bold_is_bright)
        self.copy_on_select = Gtk.Switch(active=preferences.copy_on_select)
        self.scroll_on_output = Gtk.Switch(active=preferences.scroll_on_output)
        self.scroll_on_keystroke = Gtk.Switch(active=preferences.scroll_on_keystroke)
        terminal.heading("CURSOR")
        terminal.field("Formato", self.cursor_shape)
        terminal.field("Piscar", self.cursor_blink)
        terminal.heading("TEXTO E SELEÇÃO")
        terminal.field("Negrito usa cores claras", self.bold_is_bright)
        terminal.field("Copiar ao selecionar", self.copy_on_select)
        terminal.heading("ROLAGEM")
        terminal.field("Linhas do histórico", self.scrollback)
        terminal.field("Rolar ao receber saída", self.scroll_on_output)
        terminal.field("Rolar ao digitar", self.scroll_on_keystroke)
        terminal.hint("Ctrl + roda do mouse também altera o tamanho da fonte.")
        self.pages.append_page(terminal, Gtk.Label(label="Terminal"))

        # --- Som do teclado
        sound_page = FormPage()
        self.key_switch = Gtk.ComboBoxText()
        self.refresh_key_sources(preferences.key_switch)
        self.key_volume = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 5)
        self.key_volume.set_value(preferences.key_volume)
        self.key_volume.set_value_pos(Gtk.PositionType.RIGHT)
        self.key_volume.set_digits(0)
        self.key_release = Gtk.Switch(active=preferences.key_release)
        pack_actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        import_pack = Gtk.Button(label="Importar pacote…")
        import_pack.set_tooltip_text("Pasta de um pacote Mechvibes (config.json) ou com press.wav / release.wav")
        import_pack.connect("clicked", self.import_sound_pack)
        open_packs = Gtk.Button(label="Abrir pasta")
        open_packs.connect("clicked", self.open_packs_folder)
        pack_actions.pack_start(import_pack, False, False, 0)
        pack_actions.pack_start(open_packs, False, False, 0)
        self.key_test = Gtk.Entry()
        self.key_test.set_placeholder_text("Digite aqui para ouvir…")
        self.key_test.connect("key-press-event", self.on_key_test_press)
        self.key_test.connect("key-release-event", self.on_key_test_release)
        sound_page.heading("SOM DO TECLADO")
        sound_page.field("Ativar", self.sound)
        sound_page.field("Switch", self.key_switch)
        self.key_status = sound_page.hint("", column=1, width=1)
        sound_page.field("Volume", self.key_volume)
        sound_page.field("Som ao soltar a tecla", self.key_release, "Toca o retorno da haste (top-out) ao soltar.")
        sound_page.heading("TESTAR")
        sound_page.full(self.key_test)
        sound_page.hint(
            "Os sons tocam na descida e na subida de cada tecla, sem trava entre teclas; "
            "segurar uma tecla não repete o som, como num teclado real."
        )
        sound_page.heading("PACOTES GRAVADOS")
        sound_page.full(pack_actions)
        sound_page.hint(
            "Para o som exato de um teclado real, importe uma gravação: pacotes Mechvibes "
            "(com config.json) ou uma pasta com press.wav, release.wav, space-press.wav etc."
        )
        self.pages.append_page(sound_page, Gtk.Label(label="Som do teclado"))
        engine = KeySoundEngine.shared()
        engine.on_loaded.append(self.update_key_status)
        self.connect("destroy", lambda *_: engine.on_loaded.remove(self.update_key_status)
                     if self.update_key_status in engine.on_loaded else None)
        for widget, signal in (
            (self.key_switch, "changed"),
            (self.key_volume, "value-changed"),
            (self.key_release, "notify::active"),
        ):
            widget.connect(signal, lambda *_: self.preview_key_sound())
        self.preview_key_sound()

        # --- Atalhos
        self.shortcuts_editor = ShortcutsEditor(preferences.shortcuts)
        self.pages.append_page(self.shortcuts_editor, Gtk.Label(label="Atalhos"))

        self.profile_handler = self.profile.connect("changed", self.on_profile_changed)
        self.theme.connect("changed", lambda *_: self.update_theme_buttons())
        self.effects.connect("notify::active", lambda *_: self.update_font_suggestion())
        self.shell.connect("changed", lambda *_: self.update_shell_status())
        self.update_profile_note()
        self.update_theme_buttons()
        self.update_shell_status()
        self.show_all()

    def selected_profile(self) -> str:
        index = self.profile.get_active()
        return self.profile_ids[index] if 0 <= index < len(self.profile_ids) else "developer"

    def bind_dropdown_key(self, command: str) -> None:
        key = self.dropdown_key.get_text().strip()
        keyval, _modifiers = Gtk.accelerator_parse(key)
        if not keyval:
            show_error(self, "Atalho inválido", f"“{key}” não é um atalho do GTK (ex.: F12 ou <Super>grave).")
            return
        key = Gtk.accelerator_name(keyval, _modifiers)
        ok, message = bind_xfce(key, command)
        if not ok:
            show_error(self, "Atalho não configurado", message)
            return
        dialog = Gtk.MessageDialog(
            transient_for=self, modal=True, message_type=Gtk.MessageType.INFO,
            buttons=Gtk.ButtonsType.OK, text="Atalho configurado",
        )
        dialog.format_secondary_text(message)
        dialog.run()
        dialog.destroy()

    def update_profile_note(self) -> None:
        profile = self.profile_manager.get(self.selected_profile())
        note = profile.description or "Perfil personalizado."
        if not profile.builtin:
            note += f"\nDiretório inicial: {profile.working_directory}"
            if profile.own_actions:
                note += " · ações rápidas próprias"
        self.profile_note.set_text(note)
        custom = not profile.builtin
        self.edit_profile_button.set_sensitive(custom)
        self.delete_profile_button.set_sensitive(custom)

    def refresh_profiles(self, selected: str) -> None:
        """Rebuild the profile list without re-applying the selected profile."""
        handler = getattr(self, "profile_handler", None)
        if handler is not None:
            self.profile.handler_block(handler)
        self.profile.remove_all()
        self.profile_ids = []
        active = 0
        for index, profile in enumerate(self.profile_manager.all()):
            self.profile.append_text(profile.name if profile.builtin else f"{profile.name} — personalizado")
            self.profile_ids.append(profile.identifier)
            if profile.identifier == selected:
                active = index
        self.profile.set_active(active)
        if handler is not None:
            self.profile.handler_unblock(handler)

    def new_profile(self, _button) -> None:
        dialog = ProfileEditorDialog(self, self.profile_manager, None)
        self.run_profile_editor(dialog)

    def edit_profile(self, _button) -> None:
        profile = self.profile_manager.get(self.selected_profile())
        if profile.builtin:
            return
        self.run_profile_editor(ProfileEditorDialog(self, self.profile_manager, profile))

    def run_profile_editor(self, dialog: "ProfileEditorDialog") -> None:
        while dialog.run() == Gtk.ResponseType.OK:
            try:
                saved = dialog.save(self.collect(), self.action_store)
            except ProfileError as error:
                show_error(dialog, "Perfil inválido", str(error))
                continue
            self.refresh_profiles(saved.identifier)
            self.update_profile_note()
            break
        dialog.destroy()

    def delete_profile(self, _button) -> None:
        profile = self.profile_manager.get(self.selected_profile())
        if profile.builtin or not confirm(
            self,
            f"Remover o perfil “{profile.name}”?",
            "As configurações e ações rápidas próprias deste perfil serão apagadas.",
            "Remover",
        ):
            return
        try:
            self.profile_manager.delete_custom(profile.identifier)
        except ProfileError as error:
            show_error(self, "Não foi possível remover", str(error))
        self.refresh_profiles("developer")
        self.update_profile_note()

    def update_shell_status(self) -> None:
        value = self.shell.get_text().strip()
        argv = shell_argv(value, warn=False)
        if value and Path(argv[0]).name != Path(shlex_first(value)).name:
            self.shell_status.set_text(f"Não encontrado; será usado {argv[0]}.")
        else:
            self.shell_status.set_text("Executa: " + " ".join(argv))

    def refresh_key_sources(self, selected: str) -> None:
        self.key_switch.remove_all()
        for identifier, label in SYNTH_SWITCHES.items():
            self.key_switch.append(identifier, f"{label} — sintetizado")
        for pack in list_packs():
            self.key_switch.append(f"pack:{pack.identifier}", f"{pack.name} — gravado")
        if not self.key_switch.set_active_id(selected):
            self.key_switch.set_active_id("brown")

    def preview_key_sound(self) -> None:
        source = self.key_switch.get_active_id() or "brown"
        self.key_status.set_text("Carregando…")
        KeySoundEngine.shared().configure(source, int(self.key_volume.get_value()), self.key_release.get_active())
        self.update_key_status()

    def update_key_status(self) -> None:
        engine = KeySoundEngine.shared()
        if not engine.available():
            self.key_status.set_text("Áudio indisponível: instale o GStreamer (python3-gst-1.0).")
        elif engine.loading_key is not None:
            self.key_status.set_text("Carregando…")
        elif engine.last_error:
            self.key_status.set_text(f"Pacote inválido: {engine.last_error}. Usando o som sintetizado.")
        elif engine.bank is not None:
            self.key_status.set_text(f"Pronto: {engine.bank.name}")

    def on_key_test_press(self, _entry, event) -> bool:
        KeySoundEngine.shared().press(event.hardware_keycode, event.keyval)
        return False

    def on_key_test_release(self, _entry, event) -> bool:
        KeySoundEngine.shared().release(event.hardware_keycode, event.keyval)
        return False

    def import_sound_pack(self, _button) -> None:
        chooser = Gtk.FileChooserDialog(
            title="Importar pacote de sons",
            transient_for=self,
            action=Gtk.FileChooserAction.SELECT_FOLDER,
        )
        chooser.add_buttons("Cancelar", Gtk.ResponseType.CANCEL, "Importar", Gtk.ResponseType.OK)
        response = chooser.run()
        folder = chooser.get_filename()
        chooser.destroy()
        if response != Gtk.ResponseType.OK or not folder:
            return
        try:
            identifier = install_sound_pack(Path(folder))
        except PackError as error:
            show_error(self, "Pacote de sons inválido", str(error))
            return
        self.refresh_key_sources(f"pack:{identifier}")

    @staticmethod
    def open_packs_folder(_button) -> None:
        folder = packs_directory()
        try:
            folder.mkdir(parents=True, exist_ok=True)
            Gio.AppInfo.launch_default_for_uri(folder.as_uri(), None)
        except (OSError, GLib.Error) as error:
            LOGGER.warning("não foi possível abrir %s: %s", folder, error)

    def update_font_suggestion(self) -> None:
        theme = self.theme_manager.get(self.selected_theme())
        notes = []
        installed = None
        if theme.font:
            installed = installed_font_families().get(theme.font.casefold())
            if installed:
                notes.append(f"Fonte sugerida: {installed}.")
            else:
                package = FONT_PACKAGES.get(theme.font.casefold())
                hint = f" — instale o pacote {package}" if package else ""
                notes.append(f"Fonte sugerida: {theme.font} (não instalada{hint}).")
        if (theme.curvature or theme.glow or theme.noise) and not self.effects.get_active():
            notes.append("Ligue os Efeitos visuais para o brilho, a curvatura e o ruído da tela.")
        self.font_suggestion.set_text(" ".join(notes))
        self.font_suggestion.set_visible(bool(notes))
        self.use_suggested_font.set_visible(installed is not None)
        self.suggested_font = installed

    def apply_suggested_font(self, _button) -> None:
        if not getattr(self, "suggested_font", None):
            return
        size = Pango.FontDescription(self.font.get_font_name()).get_size() // Pango.SCALE or 12
        self.font.set_font_name(f"{self.suggested_font} {size}")

    def update_theme_buttons(self) -> None:
        self.update_font_suggestion()
        custom = self.theme_manager.is_custom(self.selected_theme())
        self.edit_theme_button.set_label("Editar…" if custom else "Duplicar…")
        self.edit_theme_button.set_tooltip_text(
            "Editar as cores deste tema" if custom else "Criar um tema personalizado a partir deste"
        )
        self.delete_theme_button.set_sensitive(custom)

    def on_profile_changed(self, _combo) -> None:
        profile = self.profile_manager.get(self.selected_profile())
        self.update_profile_note()
        self.refresh_themes(profile.theme)
        family = profile.font if profile.font is not None else self.preferences.font
        self.font.set_font_name(f"{choose_font(family).family} {profile.font_size}")
        if profile.shell is not None or not profile.builtin:
            self.shell.set_text(profile.shell or "")
        if profile.cursor_shape is not None:
            self.cursor_shape.set_active_id(profile.cursor_shape)
        if profile.opacity is not None:
            self.opacity.set_value(profile.opacity)
        self.boot.set_active(profile.boot)
        self.effects.set_active(profile.effects)
        self.sound.set_active(profile.sound)
        self.panel.set_active(profile.panel_visible)

    def refresh_themes(self, selected: str) -> None:
        self.theme.remove_all()
        self.theme_ids = []
        active = 0
        for index, theme in enumerate(self.theme_manager.all()):
            suffix = "" if theme.builtin else " — personalizado"
            self.theme.append_text(theme.name + suffix)
            self.theme_ids.append(theme.identifier)
            if theme.identifier == selected:
                active = index
        self.theme.set_active(active)

    def selected_theme(self) -> str:
        index = self.theme.get_active()
        return self.theme_ids[index] if 0 <= index < len(self.theme_ids) else DEFAULT_THEME

    def open_theme_editor(self, base: Theme) -> None:
        dialog = ThemeEditorDialog(self, self.theme_manager, base)
        while dialog.run() == Gtk.ResponseType.OK:
            try:
                saved = self.theme_manager.save_custom(dialog.build_theme())
            except ThemeError as error:
                self.show_theme_error(str(error))
                continue
            self.refresh_themes(saved.identifier)
            break
        dialog.destroy()

    def new_theme(self, _button) -> None:
        self.open_theme_editor(dataclasses.replace(self.theme_manager.get(self.selected_theme()), builtin=True))

    def edit_theme(self, _button) -> None:
        self.open_theme_editor(self.theme_manager.get(self.selected_theme()))

    def delete_theme(self, _button) -> None:
        theme = self.theme_manager.get(self.selected_theme())
        dialog = Gtk.MessageDialog(
            transient_for=self,
            modal=True,
            message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.NONE,
            text=f"Remover o tema “{theme.name}”?",
        )
        dialog.format_secondary_text("O arquivo do tema será apagado. Exporte-o antes se quiser guardar uma cópia.")
        dialog.add_buttons("Cancelar", Gtk.ResponseType.CANCEL, "Remover", Gtk.ResponseType.OK)
        response = dialog.run()
        dialog.destroy()
        if response != Gtk.ResponseType.OK:
            return
        try:
            self.theme_manager.delete_custom(theme.identifier)
        except ThemeError as error:
            self.show_theme_error(str(error))
        self.refresh_themes(DEFAULT_THEME)

    def import_theme(self, _button) -> None:
        chooser = Gtk.FileChooserDialog(
            title="Importar tema",
            transient_for=self,
            action=Gtk.FileChooserAction.OPEN,
        )
        chooser.add_buttons("Cancelar", Gtk.ResponseType.CANCEL, "Importar", Gtk.ResponseType.OK)
        file_filter = Gtk.FileFilter()
        file_filter.set_name("Tema do Hacker Terminal (*.ini)")
        file_filter.add_pattern("*.ini")
        chooser.add_filter(file_filter)
        if chooser.run() == Gtk.ResponseType.OK:
            try:
                imported = self.theme_manager.import_theme(Path(chooser.get_filename()))
                self.refresh_themes(imported.identifier)
            except ThemeError as error:
                self.show_theme_error(str(error))
        chooser.destroy()

    def export_theme(self, _button) -> None:
        chooser = Gtk.FileChooserDialog(
            title="Exportar tema",
            transient_for=self,
            action=Gtk.FileChooserAction.SAVE,
        )
        chooser.add_buttons("Cancelar", Gtk.ResponseType.CANCEL, "Exportar", Gtk.ResponseType.OK)
        chooser.set_do_overwrite_confirmation(True)
        chooser.set_current_name(f"{self.selected_theme()}.ini")
        if chooser.run() == Gtk.ResponseType.OK:
            try:
                self.theme_manager.export_theme(self.selected_theme(), Path(chooser.get_filename()))
            except ThemeError as error:
                self.show_theme_error(str(error))
        chooser.destroy()

    def show_theme_error(self, message: str) -> None:
        dialog = Gtk.MessageDialog(
            transient_for=self,
            modal=True,
            message_type=Gtk.MessageType.ERROR,
            buttons=Gtk.ButtonsType.CLOSE,
            text="Tema inválido",
        )
        dialog.format_secondary_text(message)
        dialog.run()
        dialog.destroy()

    def apply(self) -> None:
        self.apply_to(self.preferences)

    def collect(self) -> Preferences:
        """The settings currently shown in the dialog, without saving them."""
        snapshot = dataclasses.replace(self.preferences, shortcuts=dict(self.preferences.shortcuts))
        self.apply_to(snapshot)
        return snapshot

    def apply_to(self, target: Preferences) -> None:
        target.profile = self.selected_profile()
        target.theme = self.selected_theme()
        description = Pango.FontDescription(self.font.get_font_name())
        target.font = description.get_family()
        size = description.get_size() // Pango.SCALE
        if size:
            target.font_size = size
        target.scrollback_lines = self.scrollback.get_value_as_int()
        target.boot = self.boot.get_active()
        target.effects = self.effects.get_active()
        target.sound = self.sound.get_active()
        target.key_switch = self.key_switch.get_active_id() or "brown"
        target.key_volume = int(self.key_volume.get_value())
        target.key_release = self.key_release.get_active()
        target.panel_visible = self.panel.get_active()
        target.restore_session = self.restore_session.get_active()
        target.shell = self.shell.get_text().strip()
        target.confirm_paste = self.confirm_paste.get_active()
        target.bell_notify = self.bell_notify.get_active()
        target.notify_commands = self.notify_commands.get_active()
        target.shell_integration = self.shell_integration.get_active()
        target.command_marks = self.command_marks.get_active()
        target.notify_after = self.notify_after.get_value_as_int()
        target.dropdown_height = self.dropdown_height.get_value_as_int()
        target.dropdown_autohide = self.dropdown_autohide.get_active()
        target.opacity = int(self.opacity.get_value())
        target.cursor_shape = self.cursor_shape.get_active_id() or "block"
        target.cursor_blink = self.cursor_blink.get_active_id() or "system"
        target.bold_is_bright = self.bold_is_bright.get_active()
        target.copy_on_select = self.copy_on_select.get_active()
        target.scroll_on_output = self.scroll_on_output.get_active()
        target.scroll_on_keystroke = self.scroll_on_keystroke.get_active()
        target.shortcuts = self.shortcuts_editor.overrides()
        target.normalize()


class HackerTerminal(Gtk.ApplicationWindow):
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
        self.open_server = OpenServer(self.open_file_from_pane)
        self.open_socket = self.open_server.start()
        self.saved_session = (
            self.session_store.load()
            if self.preferences.restore_session and not self.config.command
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
        self.boot_sound = self.build_sounds()
        self.configure_key_sound()

        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE, transition_duration=240)
        self.add(self.stack)
        self.boot = BootScreen(self.boot_sound, self.enter_terminal)
        self.stack.add_named(self.boot, "boot")
        self.workspace = self.build_workspace()
        self.stack.add_named(self.workspace, "terminal")
        self.stack.set_visible_child_name("boot" if self.preferences.boot else "terminal")
        self.set_toolbar_sensitive(not self.preferences.boot)
        self.show_all()
        if self.preferences.boot:
            GLib.timeout_add(100, self.boot.begin)
        else:
            self.enter_terminal()
        self.status_source_id = GLib.timeout_add_seconds(3, self.refresh_status)
        self.command_source_id = 0
        self.update_command_watch()
        self.autosave_source_id = GLib.timeout_add_seconds(SESSION_AUTOSAVE_SECONDS, self.autosave_session)

    def build_header(self) -> Gtk.HeaderBar:
        self.header = Gtk.HeaderBar(title="Hacker Terminal")
        self.header.set_has_subtitle(True)
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

    def focus_other_pane(self) -> None:
        frame = self.active_frame()
        panes = self.leaves(frame.get_child()) if frame is not None else []
        active = self.get_active_terminal()
        if len(panes) > 1 and active in panes:
            target = panes[(panes.index(active) + 1) % len(panes)]
            target.terminal.grab_focus()

    def split_horizontal(self) -> None:
        self.split_active(Gtk.Orientation.HORIZONTAL)

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
        opacity = self.preferences.opacity / 100 if self.translucent else 1.0
        self.css_provider.load_from_data(self.active_theme.css(opacity))
        settings = Gtk.Settings.get_default()
        if settings is not None:
            settings.set_property("gtk-application-prefer-dark-theme", self.active_theme.dark)

    def autosave_session(self) -> bool:
        """Persist the layout periodically so a crash or kill does not lose it."""
        if self.closing_window:
            self.autosave_source_id = 0
            return False
        if self.stack.get_visible_child_name() == "terminal" and self.notebook.get_n_pages():
            self.save_session()
        return True

    def configure_key_sound(self) -> None:
        if self.preferences.sound:
            KeySoundEngine.shared().configure(
                self.preferences.key_switch, self.preferences.key_volume, self.preferences.key_release
            )

    def build_sounds(self) -> SoundPlayer:
        cache_setting = os.environ.get("XDG_CACHE_HOME")
        cache_home = Path(cache_setting).expanduser() if cache_setting else Path.home() / ".cache"
        sound_dir = cache_home / APP_NAME
        self.sound_tempdir: tempfile.TemporaryDirectory[str] | None = None
        try:
            sound_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        except OSError:
            self.sound_tempdir = tempfile.TemporaryDirectory(prefix=f"{APP_NAME}-")
            sound_dir = Path(self.sound_tempdir.name)
        boot = make_tone(sound_dir / "boot.wav", [(196, 0.09), (294, 0.09), (392, 0.12), (587, 0.20)])
        return SoundPlayer(boot, 0.34)

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

        statusbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        statusbar.get_style_context().add_class("statusbar-row")
        self.status_badge = Gtk.Label(label="")
        self.status_badge.get_style_context().add_class("status-badge")
        self.status_badge.set_no_show_all(True)
        statusbar.pack_start(self.status_badge, False, False, 0)
        self.status_context = Gtk.Label(label="", xalign=0)
        self.status_context.set_ellipsize(Pango.EllipsizeMode.START)
        self.status_context.get_style_context().add_class("status-context")
        statusbar.pack_start(self.status_context, True, True, 0)
        self.status = Gtk.Label(label="0 SESSÕES", xalign=1)
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
        GLib.idle_add(self.restore_active_terminal_focus)
        return False

    def restore_active_terminal_focus(self) -> bool:
        if self.closing_window or self.stack.get_visible_child_name() != "terminal":
            return False
        pane = self.get_active_terminal()
        if pane is None:
            return False
        if pane.search_bar.get_reveal_child() and pane.search_bar.entry.is_focus():
            return False
        pane.terminal.grab_focus()
        return False

    def enter_terminal(self) -> bool:
        self.stack.set_visible_child_name("terminal")
        self.set_toolbar_sensitive(True)
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

    def rebuild_layout(self, frame: Gtk.Frame, pane: TerminalPane, node, directories) -> None:
        """Replay a saved split tree; ``pane`` already shows its first leaf."""
        if not isinstance(node, list):
            return
        kind, first, second = node[:3]
        ratio = node[3] if len(node) == 4 else 0.5
        orientation = Gtk.Orientation.HORIZONTAL if kind == "horizontal" else Gtk.Orientation.VERTICAL
        second_pane = self.split_pane(frame, pane, orientation, directories[self.first_leaf(second)], ratio)
        self.rebuild_layout(frame, pane, first, directories)
        self.rebuild_layout(frame, second_pane, second, directories)

    @staticmethod
    def first_leaf(node) -> int:
        while isinstance(node, list):
            node = node[1]
        return node

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
        label.set_max_width_chars(18)
        label.set_width_chars(8)
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

    # ------------------------------------------------------------ viewer

    def active_viewer(self):
        page = self.notebook.get_current_page()
        widget = self.notebook.get_nth_page(page) if page >= 0 else None
        return widget if widget in self.viewers else None

    def pane_by_id(self, pane_id: str | None) -> TerminalPane | None:
        return next((pane for pane in self.terminals() if pane.pane_id == pane_id), None)

    def open_file_from_pane(self, path: Path, pane_id: str | None) -> None:
        self.open_file(path, self.pane_by_id(pane_id) or self.get_active_terminal())

    def open_file(self, path: Path, origin: TerminalPane | None = None) -> None:
        """Show an image or spreadsheet in a viewer tab next to its terminal."""
        if self.closing_window:
            return
        if kind_of(path) is None:
            self.show_info(f"O visualizador abre imagens e planilhas (CSV, TSV, XLSX, ODS).\n\n{path.name} não é um desses formatos.")
            return
        for viewer in self.viewers:
            if viewer.path == path:
                viewer.load()
                self.notebook.set_current_page(self.notebook.page_num(viewer))
                return
        from .viewer import FileViewer  # imported on first use only

        viewer = FileViewer(path, self.close_viewer)
        self.viewers[viewer] = origin
        icon = "image-x-generic-symbolic" if viewer.kind == "image" else "x-office-spreadsheet-symbolic"
        tab_box, label = self.make_tab_label(path.name, icon, lambda: self.close_viewer(viewer))
        label.set_tooltip_text(str(path))
        frame = self.frame_for_pane(origin) if origin is not None else None
        position = self.notebook.page_num(frame) + 1 if frame is not None else -1
        page = self.notebook.insert_page(viewer, tab_box, position)
        self.notebook.set_tab_reorderable(viewer, True)
        viewer.show_all()
        self.notebook.set_current_page(page)
        viewer.grab_focus()
        self.update_status()

    def close_viewer(self, viewer) -> None:
        origin = self.viewers.pop(viewer, None)
        page = self.notebook.page_num(viewer)
        if page >= 0:
            self.notebook.remove_page(page)
        viewer.destroy()
        frame = self.frame_for_pane(origin) if origin is not None else None
        if frame is not None:
            self.notebook.set_current_page(self.notebook.page_num(frame))
            origin.terminal.grab_focus()
        self.update_status()

    def choose_file_to_view(self, origin: TerminalPane | None = None) -> None:
        origin = origin or self.get_active_terminal()
        chooser = Gtk.FileChooserDialog(title="Visualizar arquivo", transient_for=self, action=Gtk.FileChooserAction.OPEN)
        chooser.add_buttons("Cancelar", Gtk.ResponseType.CANCEL, "Visualizar", Gtk.ResponseType.OK)
        supported = Gtk.FileFilter()
        supported.set_name("Imagens e planilhas")
        for pattern in ("*.png", "*.jpg", "*.jpeg", "*.gif", "*.webp", "*.svg", "*.bmp", "*.tif", "*.tiff",
                        "*.avif", "*.ico", "*.csv", "*.tsv", "*.xlsx", "*.xlsm", "*.ods"):
            supported.add_pattern(pattern)
            supported.add_pattern(pattern.upper())
        chooser.add_filter(supported)
        if origin is not None:
            chooser.set_current_folder(str(origin.current_working_directory()))
        response = chooser.run()
        filename = chooser.get_filename()
        chooser.destroy()
        if response == Gtk.ResponseType.OK and filename:
            self.open_file(Path(filename), origin)

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

    # ---------------------------------------------------- long commands

    def update_command_watch(self) -> None:
        """Poll /proc once a second, only while the feature is on."""
        wanted = self.preferences.notify_commands and not self.closing_window
        if wanted and not self.command_source_id:
            self.command_source_id = GLib.timeout_add_seconds(1, self.poll_commands)
        elif not wanted and self.command_source_id:
            GLib.source_remove(self.command_source_id)
            self.command_source_id = 0

    def poll_commands(self) -> bool:
        if self.closing_window or not self.preferences.notify_commands:
            self.command_source_id = 0
            return False
        now = time.monotonic()
        for pane in self.terminals():
            try:
                finished = pane.poll_command(now)
                # Panes with shell integration report exact results themselves.
                if finished is not None and not pane.integrated and finished[1] >= self.preferences.notify_after:
                    self.on_command_finished(pane, *finished)
            except Exception:  # noqa: BLE001 - one pane must not stop the watch
                LOGGER.exception("falha ao verificar comandos de um painel")
        return True

    def on_command_finished(
        self, pane: TerminalPane, name: str, duration: float, status: int | None = None, command: str = ""
    ) -> None:
        if self.is_active() and pane is self.get_active_terminal():
            return  # the user watched it finish
        label = self.tab_labels.get(pane)
        if label is not None:
            label.get_parent().get_style_context().add_class("tab-done")
        if not self.is_active():
            self.set_urgency_hint(True)
        tab = label.get_text() if label is not None else "Terminal"
        if pane.custom_name and pane.custom_name not in tab:
            tab = f"{tab} › {pane.custom_name}"
        if status is None:
            title, verb = "Comando concluído", "terminou"
        elif status == 0:
            title, verb = "✓ Comando concluído", "terminou com sucesso"
        else:
            title, verb = f"✗ Comando falhou (código {status})", "falhou"
        shown = command if command and len(command) <= 60 else (command[:59] + "…" if command else name)
        notification = Gio.Notification.new(title)
        notification.set_body(f"{shown} {verb} após {format_duration(duration)} — aba “{tab}”")
        notification.set_icon(Gio.ThemedIcon.new(APP_NAME))
        notification.set_default_action_and_target("app.focus-pane", GLib.Variant.new_string(pane.pane_id))
        application = self.get_application()
        if application is not None:
            application.send_notification(f"command-{pane.pane_id}", notification)
        LOGGER.info("comando concluído: %s (%s)", name, format_duration(duration))

    def focus_pane(self, pane_id: str) -> bool:
        pane = self.pane_by_id(pane_id)
        if pane is None:
            return False
        frame = self.frame_for_pane(pane)
        if frame is not None:
            self.notebook.set_current_page(self.notebook.page_num(frame))
        self.present()
        pane.terminal.grab_focus()
        return True

    # ------------------------------------------------- saving and recording

    def on_output_action(self, pane: TerminalPane, action: str) -> None:
        if action == "save":
            self.save_output_dialog(pane)
        elif action == "record":
            self.toggle_recording(pane)
        elif action == "copy-last":
            self.copy_last_output(pane)
        elif action == "broadcast":
            self.toggle_broadcast(self.frame_for_pane(pane))
        elif action == "rename":
            self.rename_pane(pane)

    def rename_pane(self, pane: TerminalPane | None = None) -> None:
        pane = pane or self.get_active_terminal()
        if pane is None:
            return
        dialog = Gtk.Dialog(title="Renomear painel", transient_for=self, modal=True)
        dialog.add_buttons("Cancelar", Gtk.ResponseType.CANCEL, "Renomear", Gtk.ResponseType.OK)
        mark_suggested(dialog)
        dialog.set_default_response(Gtk.ResponseType.OK)
        entry = Gtk.Entry(text=pane.custom_name, activates_default=True, max_length=40)
        entry.set_placeholder_text("ex.: servidor web, logs, build — vazio remove o nome")
        box = dialog.get_content_area()
        box.set_spacing(8)
        box.set_border_width(14)
        box.pack_start(entry, False, False, 0)
        dialog.set_default_size(420, -1)
        dialog.show_all()
        if dialog.run() == Gtk.ResponseType.OK:
            pane.set_custom_name(entry.get_text())
            self.save_session()
        dialog.destroy()
        pane.terminal.grab_focus()

    def copy_last_output(self, pane: TerminalPane | None = None) -> None:
        pane = pane or self.get_active_terminal()
        if pane is None:
            return
        if not pane.integrated:
            self.show_toast("Sem integração com o shell neste painel (zsh e bash com o shell padrão).")
            return
        copied = pane.copy_last_output()
        if copied is None:
            self.show_toast("Nenhum comando concluído ainda neste painel.")
            return
        mark, lines = copied
        self.show_toast(f"Saída de “{mark.command[:40]}” copiada ({lines} linha{'s' if lines != 1 else ''})")

    def jump_to_prompt(self, direction: int) -> None:
        pane = self.get_active_terminal()
        if pane is None:
            return
        if not pane.integrated:
            self.show_toast("Sem integração com o shell neste painel (zsh e bash com o shell padrão).")
        elif not pane.jump_to_prompt(direction):
            self.show_toast("Não há prompt " + ("anterior." if direction < 0 else "seguinte."))

    def on_shell_command_done(self, pane: TerminalPane, mark) -> None:
        """Exact result reported by the shell hooks (replaces /proc polling)."""
        if pane is self.get_active_terminal():
            self.update_status()
        if not self.preferences.notify_commands or mark.duration < self.preferences.notify_after:
            return
        self.on_command_finished(pane, mark.command.split()[0] if mark.command.split() else "comando",
                                 mark.duration, mark.exit_status, mark.command)

    def output_file_chooser(self, title: str, action_label: str, pane: TerminalPane) -> Path | None:
        chooser = Gtk.FileChooserDialog(title=title, transient_for=self, action=Gtk.FileChooserAction.SAVE)
        chooser.add_buttons("Cancelar", Gtk.ResponseType.CANCEL, action_label, Gtk.ResponseType.OK)
        chooser.set_do_overwrite_confirmation(True)
        chooser.set_current_folder(str(pane.current_working_directory()))
        chooser.set_current_name(time.strftime("terminal-%Y%m%d-%H%M%S.txt"))
        for name, pattern in (("Texto (*.txt)", "*.txt"), ("HTML com cores (*.html)", "*.html")):
            file_filter = Gtk.FileFilter()
            file_filter.set_name(name)
            file_filter.add_pattern(pattern)
            chooser.add_filter(file_filter)
        hint = Gtk.Label(label="Use a extensão .html para manter as cores.", xalign=0)
        hint.get_style_context().add_class("panel-hint")
        chooser.set_extra_widget(hint)
        response = chooser.run()
        filename = chooser.get_filename()
        chooser.destroy()
        return Path(filename) if response == Gtk.ResponseType.OK and filename else None

    def save_output_dialog(self, pane: TerminalPane | None = None) -> None:
        pane = pane or self.get_active_terminal()
        if pane is None:
            return
        path = self.output_file_chooser("Salvar saída do terminal", "Salvar", pane)
        if path is None:
            return
        try:
            lines = pane.save_output(path)
        except OSError as error:
            show_error(self, "Não foi possível salvar", str(error))
            return
        self.show_toast(f"{lines} linhas salvas em {shorten_home(path)}")

    def toggle_recording(self, pane: TerminalPane | None = None) -> None:
        pane = pane or self.get_active_terminal()
        if pane is None:
            return
        if pane.recorder is not None:
            recorder = pane.stop_recording()
            note = f" ({recorder.lost_rows} linhas perdidas: histórico excedido)" if recorder and recorder.lost_rows else ""
            self.show_toast(f"Gravação salva em {shorten_home(recorder.path)}{note}")
        else:
            path = self.output_file_chooser("Gravar saída do terminal", "Gravar", pane)
            if path is None:
                return
            try:
                pane.start_recording(path)
            except OSError as error:
                show_error(self, "Não foi possível gravar", str(error))
                return
        self.update_recording_marks()

    def update_recording_marks(self) -> None:
        for pane, label in self.tab_labels.items():
            frame = self.frame_for_pane(pane)
            recording = any(item.recorder is not None for item in self.page_panes.get(frame, []))
            context = label.get_parent().get_style_context()
            if recording:
                context.add_class("tab-recording")
            else:
                context.remove_class("tab-recording")
        self.update_status()

    def show_toast(self, message: str) -> None:
        """A short message in the status bar, without a dialog to dismiss."""
        self.toast_text = message
        self.update_status()
        if getattr(self, "toast_source", 0):
            GLib.source_remove(self.toast_source)
        self.toast_source = GLib.timeout_add_seconds(6, self.clear_toast)

    def clear_toast(self) -> bool:
        self.toast_text = ""
        self.toast_source = 0
        if not self.closing_window:
            self.update_status()
        return False

    # ------------------------------------------------------------ drop-down

    def setup_dropdown(self) -> None:
        self.set_title("Hacker Terminal (suspenso)")
        self.set_decorated(False)
        self.set_keep_above(True)
        self.set_skip_taskbar_hint(True)
        self.set_skip_pager_hint(True)
        self.stick()
        self.get_style_context().add_class("dropdown")
        self.connect("focus-out-event", self.on_dropdown_focus_out)

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
        x, y, width, height = dropdown_geometry(self.dropdown_area(), self.preferences.dropdown_height)
        self.resize(width, height)
        self.move(x, y)
        self.show()
        self.move(x, y)
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

    # ----------------------------------------------------------------- SSH

    def show_ssh_manager(self) -> None:
        dialog = SSHManagerDialog(self, self.connection_store, self.theme_manager)
        response = dialog.run()
        chosen = dialog.selected_connection() if response == Gtk.ResponseType.OK else None
        dialog.destroy()
        if chosen is not None:
            self.connect_ssh(chosen)

    def connect_ssh(self, connection: Connection) -> TerminalPane | None:
        if connection.confirm and not confirm(
            self,
            f"Conectar a “{connection.name}”?",
            f"Esta conexão está marcada para confirmação.\n\n{connection.command_line()}",
            "Conectar",
        ):
            return None
        self.new_tab(working_directory=Path.home())
        pane = self.get_active_terminal()
        if pane is None:
            return None
        pane.title_prefix = f"🔒 {connection.name}"
        theme = self.theme_manager.themes.get(connection.theme) if connection.theme else None
        if theme is not None:
            pane.theme_override = theme
            pane.apply_preferences(self.active_theme)
        self.on_terminal_title_changed(pane, connection.destination)
        # Typed into the user's own shell: a failed connection stays visible
        # and leaving the host returns to the local shell.
        if pane.shell_running:
            pane.run_command(connection.command_line())
        else:
            pane.pending_input = connection.command_line()
        return pane

    # ----------------------------------------------------------- broadcast

    def toggle_broadcast(self, frame: Gtk.Frame | None = None) -> None:
        frame = frame or self.active_frame()
        if frame is None:
            return
        if frame in self.broadcast_frames:
            self.broadcast_frames.discard(frame)
            self.show_toast("Transmissão desligada: cada painel recebe só a própria digitação.")
        else:
            panes = self.page_panes.get(frame, [])
            if len(panes) < 2:
                self.show_toast("Divida a aba (Ctrl+Shift+D ou E) para transmitir a digitação a vários painéis.")
                return
            self.broadcast_frames.add(frame)
            self.show_toast(f"Transmitindo: o que você digitar vai para os {len(panes)} painéis desta aba.")
        self.update_broadcast(frame)

    def update_broadcast(self, frame: Gtk.Frame) -> None:
        panes = self.page_panes.get(frame, [])
        if len(panes) < 2:
            self.broadcast_frames.discard(frame)
        active = frame in self.broadcast_frames
        for pane in panes:
            pane.broadcast_peers = [peer for peer in panes if peer is not pane] if active else []
        context = frame.get_style_context()
        if active:
            context.add_class("broadcast")
        else:
            context.remove_class("broadcast")
        label = self.tab_labels.get(panes[0]) if panes else None
        if label is not None:
            box_context = label.get_parent().get_style_context()
            if active:
                box_context.add_class("tab-broadcast")
            else:
                box_context.remove_class("tab-broadcast")
        self.update_status()

    def on_pane_bell(self, pane: TerminalPane) -> None:
        if self.is_active() and pane is self.get_active_terminal():
            pane.bell_pending = False
            return
        if not self.is_active():
            self.set_urgency_hint(True)
        label = self.tab_labels.get(pane)
        if label is not None:
            label.get_parent().get_style_context().add_class("tab-bell")

    def clear_bell(self, pane: TerminalPane | None) -> None:
        self.set_urgency_hint(False)
        if pane is None:
            return
        pane.bell_pending = False
        label = self.tab_labels.get(pane)
        frame = self.frame_for_pane(pane)
        others = [item for item in self.page_panes.get(frame, []) if item is not pane and item.bell_pending]
        if label is not None and not others:
            label.get_parent().get_style_context().remove_class("tab-bell")
        if label is not None:
            label.get_parent().get_style_context().remove_class("tab-done")
        application = self.get_application()
        if application is not None:
            application.withdraw_notification(f"command-{pane.pane_id}")

    def update_pane_highlight(self, frame: Gtk.Frame) -> None:
        panes = self.page_panes.get(frame, [])
        active = self.active_panes.get(frame)
        for item in panes:
            context = item.get_style_context()
            if len(panes) > 1 and item is not active:
                context.add_class("pane-inactive")
            else:
                context.remove_class("pane-inactive")

    def split_active(
        self,
        orientation: Gtk.Orientation,
        working_directory: Path | None = None,
    ) -> TerminalPane | None:
        frame = self.active_frame()
        pane = self.get_active_terminal()
        if frame is None or pane is None or self.config.command:
            return None
        if len(self.page_panes.get(frame, [])) >= MAX_PANES_PER_TAB:
            self.show_info(f"Cada aba comporta até {MAX_PANES_PER_TAB} painéis. Abra uma nova aba com Ctrl+Shift+T.")
            return None
        return self.split_pane(frame, pane, orientation, working_directory or pane.current_working_directory())

    def split_pane(
        self, frame: Gtk.Frame, pane: TerminalPane, orientation: Gtk.Orientation, directory: Path,
        ratio: float = 0.5,
    ) -> TerminalPane:
        """Replace ``pane`` by a split holding it and a new pane."""
        allocation = pane.get_allocation()
        parent = pane.get_parent()
        new_pane = self.create_terminal((), directory)
        split = Gtk.Paned(orientation=orientation)
        if isinstance(parent, Gtk.Paned):
            first_slot = parent.get_child1() is pane
            parent.remove(pane)
            if first_slot:
                parent.pack1(split, resize=True, shrink=True)
            else:
                parent.pack2(split, resize=True, shrink=True)
        else:
            frame.remove(pane)
            frame.add(split)
        split.pack1(pane, resize=True, shrink=True)
        split.pack2(new_pane, resize=True, shrink=True)
        self.page_panes[frame].append(new_pane)
        self.active_panes[frame] = new_pane
        self.tab_labels[new_pane] = self.tab_labels[pane]
        frame.show_all()
        size = allocation.width if orientation == Gtk.Orientation.HORIZONTAL else allocation.height
        if size > 1:
            split.set_position(round(size * ratio))
        else:
            self.position_when_allocated(split, ratio)
        self.update_pane_highlight(frame)
        new_pane.spawn()
        self.update_broadcast(frame)
        return new_pane

    @staticmethod
    def position_when_allocated(split: Gtk.Paned, ratio: float = 0.5) -> None:
        """Apply the split ratio once the paned has a real size (restored layouts).

        Until then the ratio stays on the paned, so saving a tab that was
        never shown keeps its sizes instead of forgetting them.
        """
        split.pending_ratio = ratio

        def on_allocate(widget, allocation) -> None:
            size = allocation.width if widget.get_orientation() == Gtk.Orientation.HORIZONTAL else allocation.height
            if size <= 1:
                return
            widget.disconnect(handler[0])

            def apply() -> bool:
                widget.set_position(round(size * ratio))
                widget.pending_ratio = None
                return False

            # Changing the position inside size-allocate would re-queue a resize.
            GLib.idle_add(apply)

        handler = [split.connect("size-allocate", on_allocate)]

    @staticmethod
    def leaves(widget: Gtk.Widget) -> list[TerminalPane]:
        """Panes of a split tree, left-to-right / top-to-bottom."""
        if isinstance(widget, TerminalPane):
            return [widget]
        if isinstance(widget, Gtk.Paned):
            return [*HackerTerminal.leaves(widget.get_child1()), *HackerTerminal.leaves(widget.get_child2())]
        return []

    @staticmethod
    def layout_of(widget: Gtk.Widget, order: list[TerminalPane]):
        if isinstance(widget, Gtk.Paned):
            kind = "horizontal" if widget.get_orientation() == Gtk.Orientation.HORIZONTAL else "vertical"
            node = [kind, HackerTerminal.layout_of(widget.get_child1(), order),
                    HackerTerminal.layout_of(widget.get_child2(), order)]
            allocation = widget.get_allocation()
            size = allocation.width if kind == "horizontal" else allocation.height
            pending = getattr(widget, "pending_ratio", None)
            if pending is not None:
                node.append(pending)
            elif size > 1:
                ratio = widget.get_position() / size
                node.append(round(min(0.95, max(0.05, ratio)), 3))
            return node
        return order.index(widget)

    def close_active_pane(self, force: bool = False) -> bool:
        viewer = self.active_viewer()
        if viewer is not None:
            self.close_viewer(viewer)
            return True
        pane = self.get_active_terminal()
        frame = self.active_frame()
        if pane is None or frame is None:
            return False
        if not force and pane.has_active_process() and not self.confirm_close("Há um processo ativo nesta aba."):
            return False
        panes = self.page_panes.get(frame, [])
        if len(panes) == 1:
            return self.close_page(frame, force=force)
        pane.prepare_close()
        split = pane.get_parent()
        sibling = split.get_child2() if split.get_child1() is pane else split.get_child1()
        holder = split.get_parent()
        first_slot = isinstance(holder, Gtk.Paned) and holder.get_child1() is split
        split.remove(pane)
        split.remove(sibling)
        if isinstance(holder, Gtk.Paned):
            holder.remove(split)
            if first_slot:
                holder.pack1(sibling, resize=True, shrink=True)
            else:
                holder.pack2(sibling, resize=True, shrink=True)
        else:
            frame.remove(split)
            frame.add(sibling)
        split.destroy()
        self.tab_labels.pop(pane, None)
        pane.destroy()
        panes.remove(pane)
        survivor = self.leaves(sibling)[0]
        self.active_panes[frame] = survivor
        self.update_broadcast(frame)
        frame.show_all()
        self.update_pane_highlight(frame)
        survivor.terminal.grab_focus()
        self.update_status()
        return True

    def close_page(self, frame: Gtk.Frame | None = None, force: bool = False) -> bool:
        frame = frame or self.active_frame()
        if frame is None:
            return False
        panes = self.page_panes.get(frame, [])
        active = [pane for pane in panes if pane.has_active_process()]
        if not force and active and not self.confirm_close("Há processos ativos nesta aba."):
            return False
        for pane in panes:
            pane.prepare_close()
            self.tab_labels.pop(pane, None)
        page = self.notebook.page_num(frame)
        if page >= 0:
            self.notebook.remove_page(page)
        self.page_panes.pop(frame, None)
        self.active_panes.pop(frame, None)
        self.broadcast_frames.discard(frame)
        frame.destroy()
        for viewer, origin in list(self.viewers.items()):
            if origin in panes:
                self.viewers[viewer] = None  # its terminal is gone
        self.update_status()
        if not self.page_panes:
            # Viewers alone do not keep the window open.
            for viewer in list(self.viewers):
                self.close_viewer(viewer)
            self.session_store.clear()
            self.closing_window = True
            self.close()
        return True

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
            compact = title if len(title) <= 28 else title[:27] + "…"
            label.set_text(compact)
            label.set_tooltip_text(title)
        if pane is self.get_active_terminal():
            self.header.set_subtitle(title)
            self.set_title(f"{title} — Hacker Terminal")

    def on_switch_page(self, _notebook, page, _number) -> None:
        pane = self.active_panes.get(page) if isinstance(page, Gtk.Frame) else None
        if pane is not None:
            GLib.idle_add(pane.terminal.grab_focus)
        elif page in self.viewers:
            GLib.idle_add(page.grab_focus)
        GLib.idle_add(lambda: self.update_status() and False)

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
        if self.panel_auto_hidden and self.preferences.panel_visible:
            # Narrow windows hide the panel automatically; peeking does not
            # change the saved preference.
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
            self.action_panel.sync()
            self.apply_panel_visibility()
        self.update_status()

    def apply_panel_visibility(self) -> None:
        if self.action_panel is None:
            return
        visible = self.preferences.panel_visible and (not self.panel_auto_hidden or self.panel_peek)
        self.action_panel.set_no_show_all(not visible)
        self.action_panel.set_visible(visible)

    def update_status(self) -> None:
        count = len(self.page_panes)
        panes = len(self.terminals())
        pane_status = f" • {panes} {'PAINEL' if panes == 1 else 'PAINÉIS'}"
        parts = [f"{count} {'SESSÃO' if count == 1 else 'SESSÕES'}{pane_status}"]
        terminal = self.get_active_terminal()
        directory_text = ""
        viewer = self.active_viewer()
        if viewer is not None:
            directory_text = shorten_home(viewer.path)
        if self.viewers:
            parts.append(f"{len(self.viewers)} {'VISUALIZAÇÃO' if len(self.viewers) == 1 else 'VISUALIZAÇÕES'}")
        frame = self.active_frame()
        if frame is not None and frame in self.broadcast_frames:
            parts.insert(0, f"⇉ TRANSMITINDO PARA {len(self.page_panes.get(frame, []))}")
        recording = sum(1 for pane in self.terminals() if pane.recorder is not None)
        if recording:
            parts.insert(0, "● GRAVANDO" if recording == 1 else f"● GRAVANDO {recording}")
        if terminal is not None:
            directory = terminal.current_working_directory()
            directory_text = shorten_home(directory)
            last = next((mark for mark in reversed(terminal.prompts) if mark.finished), None)
            if last is not None and last.exit_status not in (None, 0):
                parts.append(f"✗ SAÍDA {last.exit_status}")
            context = detect_project_context(directory)
            if context.branch:
                parts.append(f"GIT {context.branch}")
            if context.environment:
                parts.append(f"ENV {context.environment}")
        text = " • ".join(parts)
        if self.status.get_text() != text:
            self.status.set_text(text)
        if getattr(self, "toast_text", ""):
            directory_text = self.toast_text
        if self.status_context.get_text() != directory_text:
            self.status_context.set_text(directory_text)
            self.status_context.set_tooltip_text(directory_text or None)
        badge = self.active_theme.name.upper()
        if self.status_badge.get_text() != badge:
            self.status_badge.set_text(badge)
        self.status_badge.show()
        subtitle = (terminal.title if terminal is not None else "") or directory_text
        if self.header.get_subtitle() != subtitle:
            self.header.set_subtitle(subtitle)

    def refresh_status(self) -> bool:
        if self.closing_window:
            return False
        self.update_status()
        return True

    def on_window_destroy(self, _window) -> None:
        self.open_server.stop()
        context = GLib.MainContext.default()
        for attribute in ("status_source_id", "autosave_source_id", "command_source_id", "toast_source"):
            source = getattr(self, attribute, 0)
            # A callback that raised was already dropped by GLib; removing it
            # again would warn, so only remove sources that still exist.
            if source and context.find_source_by_id(source) is not None:
                GLib.source_remove(source)
            setattr(self, attribute, 0)

    def set_toolbar_sensitive(self, sensitive: bool) -> None:
        for button in self.toolbar_buttons:
            button.set_sensitive(sensitive)

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
        if self.stack.get_visible_child_name() != "terminal":
            return False
        identifier = self.shortcuts.match(event.keyval, event.state)
        if identifier is None:
            return False
        self.run_shortcut_action(identifier)
        return True


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
    ) -> None:
        if dropdown:
            # Unique: running --dropdown again reaches this instance over
            # D-Bus and toggles its window instead of opening another.
            super().__init__(application_id=APP_ID + ".Dropdown", flags=Gio.ApplicationFlags.DEFAULT_FLAGS)
        else:
            super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.NON_UNIQUE)
        self.dropdown = dropdown
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

    def do_shutdown(self) -> None:
        if KeySoundEngine._instance is not None:
            KeySoundEngine._instance.shutdown()
        Gtk.Application.do_shutdown(self)

    def do_activate(self) -> None:
        if self.dropdown:
            existing = next((w for w in self.get_windows() if isinstance(w, HackerTerminal)), None)
            if existing is not None:
                existing.toggle_dropdown()
                return
        window = HackerTerminal(
            self,
            self.config,
            self.store,
            self.action_store,
            self.session_store,
            self.theme_manager,
            self.profile_manager,
            self.css_provider,
            dropdown=self.dropdown,
        )
        if self.dropdown:
            window.toggle_dropdown()
        else:
            window.present()
