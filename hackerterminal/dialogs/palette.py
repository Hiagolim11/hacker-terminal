"""The command palette."""

from __future__ import annotations

from typing import Callable

from ..runtime import Gtk, Pango


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
