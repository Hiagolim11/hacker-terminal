"""The command palette."""

from __future__ import annotations

from typing import Callable

from ..runtime import GLib, Gtk, Pango

PREVIEW_DELAY_MS = 90  # holding an arrow key does not restyle every row it passes

# (label, category, callback) or (label, category, callback, preview): a
# preview value (a theme id) is shown live while its row is selected.
PaletteItem = tuple


class CommandPaletteDialog(Gtk.Dialog):
    def __init__(
        self,
        parent: Gtk.Window,
        items: list[PaletteItem],
        on_preview: Callable[[str | None], None] | None = None,
    ) -> None:
        super().__init__(title="Paleta de comandos", transient_for=parent, modal=True)
        self.items = items
        self.on_preview = on_preview
        self.previewing: str | None = None
        self.preview_source = 0
        self.selected_callback: Callable[[], None] | None = None
        self.connect("destroy", lambda *_: self.cancel_preview_timer())
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
        self.listbox.connect("row-selected", self.on_row_selected)
        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_min_content_height(240)
        self.set_default_size(min(620, max(360, parent.get_allocated_width() - 80)), 440)
        scroller.add(self.listbox)
        body.pack_start(scroller, True, True, 0)
        self.refresh()
        self.show_all()
        self.entry.grab_focus()

    def filtered_items(self) -> list[PaletteItem]:
        query = self.entry.get_text().strip().casefold()
        return [
            item
            for item in self.items
            if not query or query in f"{item[0]} {item[1]}".casefold()
        ]

    def refresh(self) -> None:
        for child in self.listbox.get_children():
            child.destroy()
        for item in self.filtered_items():
            label, category, callback = item[:3]
            row = Gtk.ListBoxRow()
            row.palette_callback = callback
            row.palette_preview = item[3] if len(item) > 3 else None
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

    # ------------------------------------------------------------ preview
    def on_row_selected(self, _listbox, row) -> None:
        if self.on_preview is None:
            return
        wanted = getattr(row, "palette_preview", None) if row is not None else None
        self.cancel_preview_timer()
        if wanted != self.previewing:
            self.preview_source = GLib.timeout_add(PREVIEW_DELAY_MS, self.show_preview, wanted)

    def show_preview(self, wanted: str | None) -> bool:
        self.preview_source = 0
        self.previewing = wanted
        self.on_preview(wanted)  # None: back to the current theme
        return False

    def cancel_preview_timer(self) -> None:
        if self.preview_source:
            GLib.source_remove(self.preview_source)
            self.preview_source = 0

    def on_row_activated(self, _listbox, row) -> None:
        self.selected_callback = row.palette_callback
        self.response(Gtk.ResponseType.OK)
