"""Pane context actions: saving and recording output, renaming, toasts."""

from __future__ import annotations

import time
from pathlib import Path

from ..dialogs.common import mark_suggested, shorten_home, show_error
from ..runtime import GLib, Gtk
from ..terminal import TerminalPane


class OutputMixin:
    """Part of HackerTerminal: pane context actions: saving and recording output, renaming, toasts."""

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
        elif action == "history":
            self.show_command_history(pane)

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
