"""Image and spreadsheet viewer tabs next to their terminal."""

from __future__ import annotations

from pathlib import Path

from ..documents import kind_of
from ..runtime import Gtk
from ..terminal import TerminalPane


class ViewerMixin:
    """Part of HackerTerminal: image and spreadsheet viewer tabs next to their terminal."""

    def active_viewer(self):
        page = self.notebook.get_current_page()
        widget = self.notebook.get_nth_page(page) if page >= 0 else None
        return widget if widget in self.viewers else None

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
        from ..viewer import FileViewer  # imported on first use only

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
