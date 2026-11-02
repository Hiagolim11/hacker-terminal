"""A read-only overlay that lists the keyboard shortcuts in effect.

Opened with F1 (or the command palette). It reads the live bindings, so it
shows whatever the user has customised, plus a few fixed gestures that are not
part of the configurable set (tab jumps, Ctrl+click).
"""
from __future__ import annotations

from ..runtime import Gdk, Gtk
from ..shortcuts import SHORTCUT_ACTIONS, accelerator_label

# Fixed gestures that are not configurable shortcuts, shown for discoverability.
EXTRA_GESTURES = (
    ("Ir para a aba 1 a 8", "Alt + 1…8"),
    ("Ir para a última aba", "Alt + 9"),
    ("Abrir link ou arquivo sob o cursor", "Ctrl + clique"),
    ("Menu da aba", "Botão direito na aba"),
)


class ShortcutsHelp(Gtk.Dialog):
    def __init__(self, parent: Gtk.Window | None, bindings: dict[str, str]) -> None:
        super().__init__(title="Atalhos de teclado", transient_for=parent, modal=False)
        self.set_default_size(480, 580)
        self.get_style_context().add_class("shortcuts-help")
        self.add_button("Fechar", Gtk.ResponseType.CLOSE)
        self.connect("response", lambda *_: self.destroy())
        self.connect("key-press-event", self._on_key)

        content = self.get_content_area()
        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        grid = Gtk.Grid(row_spacing=10, column_spacing=20)
        grid.set_margin_top(18)
        grid.set_margin_bottom(18)
        grid.set_margin_start(20)
        grid.set_margin_end(20)

        row = 0
        for action in SHORTCUT_ACTIONS:
            accelerator = accelerator_label(bindings.get(action.identifier, ""))
            if not accelerator:
                continue  # the user disabled this one
            self._row(grid, row, action.label, accelerator)
            row += 1
        row = self._heading(grid, row, "Gestos")
        for label, keys in EXTRA_GESTURES:
            self._row(grid, row, label, keys)
            row += 1

        scroller.add(grid)
        content.pack_start(scroller, True, True, 0)
        self.show_all()

    def _row(self, grid: Gtk.Grid, row: int, name: str, keys: str) -> None:
        label = Gtk.Label(label=name, xalign=0)
        label.set_hexpand(True)
        label.set_line_wrap(True)
        keys_label = Gtk.Label(label=keys, xalign=1)
        keys_label.get_style_context().add_class("shortcut-keys")
        keys_label.set_selectable(True)
        grid.attach(label, 0, row, 1, 1)
        grid.attach(keys_label, 1, row, 1, 1)

    def _heading(self, grid: Gtk.Grid, row: int, text: str) -> int:
        heading = Gtk.Label(xalign=0)
        heading.set_markup(f"<b>{text}</b>")
        heading.set_margin_top(12)
        grid.attach(heading, 0, row, 2, 1)
        return row + 1

    def _on_key(self, _widget, event) -> bool:
        if event.keyval == Gdk.KEY_Escape:
            self.destroy()
            return True
        return False


__all__ = ["ShortcutsHelp"]
