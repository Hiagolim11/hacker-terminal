"""The side panel with quick actions and toggles."""

from __future__ import annotations

from typing import Callable

from ..actions import ActionStore, QuickAction, fields as command_fields
from ..config import Preferences
from ..dialogs.actions import FieldsDialog
from ..runtime import Gtk, Pango
from ..terminal import TerminalPane


PANEL_WIDTH = 220


COMPACT_PANEL_WIDTH = 178


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
