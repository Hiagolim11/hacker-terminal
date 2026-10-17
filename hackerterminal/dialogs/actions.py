"""Quick actions: the list editor, the action form and the {fields} form."""

from __future__ import annotations

import uuid

from ..actions import ActionStore, QuickAction, fields as command_fields, fill as fill_command
from .common import mark_suggested
from ..runtime import Gtk, Pango


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
