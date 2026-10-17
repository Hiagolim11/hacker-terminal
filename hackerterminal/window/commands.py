"""Finished commands: alerts, shell integration jumps and the history."""

from __future__ import annotations

import logging
import time

from ..constants import APP_NAME
from ..dialogs.history import HistoryDialog
from ..runtime import GLib, Gio, Gtk
from ..terminal import TerminalPane, format_duration

LOGGER = logging.getLogger(__name__)


class CommandsMixin:
    """Part of HackerTerminal: finished commands: alerts, shell integration jumps and the history."""

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
        if self.preferences.command_history:
            # Only informative places: a pane's name or an SSH connection.
            place = pane.custom_name or pane.title_prefix
            self.history_store.add(mark.command, mark.exit_status, mark.duration,
                                   str(pane.current_working_directory()), place)
        if not self.preferences.notify_commands or mark.duration < self.preferences.notify_after:
            return
        self.on_command_finished(pane, mark.command.split()[0] if mark.command.split() else "comando",
                                 mark.duration, mark.exit_status, mark.command)

    def show_command_history(self, pane: TerminalPane | None = None) -> None:
        pane = pane or self.get_active_terminal()
        dialog = HistoryDialog(self, self.history_store, self.preferences.command_history and pane is not None
                               and pane.config.preferences.shell_integration)
        response = dialog.run()
        chosen = dialog.selected_command()
        dialog.destroy()
        if response == Gtk.ResponseType.OK and chosen and pane is not None and pane.shell_running:
            # Typed without Enter: the user reviews (or edits) before running.
            pane.terminal.feed_child(chosen.encode())
            pane.terminal.grab_focus()
