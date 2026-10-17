"""The command history dialog."""

from __future__ import annotations

import time
from pathlib import Path

from .common import confirm, mark_suggested, relative_time, shorten_home
from ..history import HistoryStore, search as search_history
from ..runtime import GLib, Gdk, Gtk, Pango
from ..terminal import format_duration


class HistoryDialog(Gtk.Dialog):
    """Search the commands run in every tab; "Usar" types one back, without Enter."""

    COLUMNS = ("Resultado", "Comando", "Quando", "Duração", "Onde")

    def __init__(self, parent: Gtk.Window, store: HistoryStore, recording: bool) -> None:
        super().__init__(title="Histórico de comandos", transient_for=parent, modal=True)
        self.store = store
        self.entries = store.load()
        self.add_buttons("Fechar", Gtk.ResponseType.CANCEL, "Usar no terminal", Gtk.ResponseType.OK)
        mark_suggested(self)
        self.set_default_response(Gtk.ResponseType.OK)
        self.set_default_size(min(900, max(520, parent.get_allocated_width() - 60)), 520)
        box = self.get_content_area()
        box.set_spacing(8)
        box.set_border_width(12)
        top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.search = Gtk.SearchEntry(placeholder_text="Buscar por comando, pasta ou aba (ex.: nmap 10.0.0)")
        self.search.connect("search-changed", lambda *_: self.refresh())
        self.search.connect("activate", lambda *_: self.response(Gtk.ResponseType.OK))
        self.only_failed = Gtk.CheckButton(label="Só falhas")
        self.only_failed.connect("toggled", lambda *_: self.refresh())
        self.repeated = Gtk.CheckButton(label="Mostrar repetidos")
        self.repeated.connect("toggled", lambda *_: self.refresh())
        top.pack_start(self.search, True, True, 0)
        top.pack_start(self.only_failed, False, False, 0)
        top.pack_start(self.repeated, False, False, 0)
        box.pack_start(top, False, False, 0)
        # result text, command, when, duration, where, failed?, full tooltip
        self.model = Gtk.ListStore(str, str, str, str, str, bool, str)
        self.view = Gtk.TreeView(model=self.model, headers_visible=True, enable_search=False)
        self.view.set_tooltip_column(6)
        self.view.connect("row-activated", lambda *_: self.response(Gtk.ResponseType.OK))
        for index, title in enumerate(self.COLUMNS):
            renderer = Gtk.CellRendererText()
            column = Gtk.TreeViewColumn(title, renderer, text=index)
            if index == 0:
                column.set_cell_data_func(renderer, self.paint_result)
            if index == 1:
                renderer.set_property("family", "monospace")
                renderer.set_property("ellipsize", Pango.EllipsizeMode.END)
                column.set_expand(True)
            if index == 4:
                renderer.set_property("ellipsize", Pango.EllipsizeMode.START)  # keep the folder's end
                column.set_min_width(180)
            column.set_resizable(True)
            self.view.append_column(column)
        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scroller.add(self.view)
        box.pack_start(scroller, True, True, 0)
        bottom = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.summary = Gtk.Label(xalign=0)
        self.summary.set_line_wrap(True)
        self.summary.get_style_context().add_class("panel-hint")
        copy_button = Gtk.Button(label="Copiar")
        copy_button.connect("clicked", lambda *_: self.copy_selected())
        clear_button = Gtk.Button(label="Limpar histórico…")
        clear_button.connect("clicked", lambda *_: self.clear_history())
        bottom.pack_start(self.summary, True, True, 0)
        bottom.pack_end(clear_button, False, False, 0)
        bottom.pack_end(copy_button, False, False, 0)
        box.pack_start(bottom, False, False, 0)
        self.notice = "" if recording else (
            "O histórico só registra comandos com a integração com o shell e o histórico ligados "
            "(Preferências → Geral). "
        )
        self.refresh()
        self.show_all()
        self.search.grab_focus()

    def paint_result(self, _column, renderer, model, iterator, _data) -> None:
        failed = model[iterator][5]
        renderer.set_property("foreground", "#e5484d" if failed else None)
        renderer.set_property("weight", Pango.Weight.BOLD if failed else Pango.Weight.NORMAL)

    def refresh(self) -> None:
        matches = search_history(
            self.entries, self.search.get_text(), self.only_failed.get_active(), not self.repeated.get_active()
        )
        self.model.clear()
        now = time.time()
        for entry in matches:
            if entry.status is None:
                result = "—"
            else:
                result = "✓" if entry.status == 0 else f"✗ {entry.status}"
            folder = shorten_home(Path(entry.directory)) if entry.directory else ""
            where = " · ".join(part for part in (entry.place, folder) if part)
            tooltip = f"{entry.command}\n{folder}"
            self.model.append([
                result, entry.command, relative_time(entry.finished_at, now),
                "< 1 s" if entry.duration < 1 else format_duration(entry.duration),
                where, entry.failed, GLib.markup_escape_text(tooltip.strip()),
            ])
        if len(self.model):
            self.view.get_selection().select_path(Gtk.TreePath.new_first())
        failures = sum(1 for entry in self.entries if entry.failed)
        self.summary.set_text(
            f"{self.notice}{len(matches)} de {len(self.entries)} comandos • {failures} falharam. "
            "Comandos digitados com um espaço no início não são guardados."
        )
        self.set_response_sensitive(Gtk.ResponseType.OK, bool(len(self.model)))

    def selected_command(self) -> str | None:
        model, iterator = self.view.get_selection().get_selected()
        return model[iterator][1] if iterator is not None else None

    def copy_selected(self) -> None:
        command = self.selected_command()
        if command:
            Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).set_text(command, -1)

    def clear_history(self) -> None:
        if confirm(self, "Limpar o histórico de comandos?", "Todos os comandos guardados serão apagados.", "Limpar"):
            self.store.clear()
            self.entries = []
            self.refresh()
