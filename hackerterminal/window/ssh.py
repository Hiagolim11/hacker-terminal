"""Opening saved SSH connections and setting up key access in tabs."""

from __future__ import annotations

from pathlib import Path

from .. import passwords
from ..connections import Connection
from ..dialogs.common import confirm, show_error
from ..dialogs.ssh import KEY_SETUP_RESPONSE, SSHManagerDialog
from ..runtime import Gtk
from ..terminal import TerminalPane, host_files


class SshMixin:
    """Part of HackerTerminal: opening saved SSH connections and setting up key access in tabs."""

    def show_ssh_manager(self) -> None:
        dialog = SSHManagerDialog(self, self.connection_store, self.theme_manager)
        response = dialog.run()
        chosen = dialog.selected_connection()
        dialog.destroy()
        if chosen is None:
            return
        if response == Gtk.ResponseType.OK:
            self.connect_ssh(chosen)
        elif response == KEY_SETUP_RESPONSE:
            self.setup_ssh_key(chosen)

    def ssh_tab(self, connection: Connection, prefix: str, command: str) -> TerminalPane | None:
        """A tab named after the connection, with its theme, that types ``command``."""
        self.new_tab(working_directory=Path.home())
        pane = self.get_active_terminal()
        if pane is None:
            return None
        pane.title_prefix = f"{prefix} {connection.name}"
        theme = self.theme_manager.themes.get(connection.theme) if connection.theme else None
        if theme is not None:
            pane.theme_override = theme
            pane.apply_preferences(self.active_theme)
        self.on_terminal_title_changed(pane, connection.destination)
        # Typed into the user's own shell: a failed connection stays visible
        # and leaving the host returns to the local shell.
        if pane.shell_running:
            pane.run_command(command)
        else:
            pane.pending_input = command
        return pane

    def setup_ssh_key(self, connection: Connection) -> TerminalPane | None:
        tools = host_files("bin")
        if tools is None or not (tools / "ht-copy-key").is_file():
            show_error(self, "Ferramenta ausente", "ht-copy-key não foi encontrado na instalação.")
            return None
        return self.ssh_tab(connection, "🔑", connection.key_setup_command(tools / "ht-copy-key"))

    def connect_ssh(self, connection: Connection) -> TerminalPane | None:
        if connection.confirm and not confirm(
            self,
            f"Conectar a “{connection.name}”?",
            f"Esta conexão está marcada para confirmação.\n\n{connection.command_line()}",
            "Conectar",
        ):
            return None
        askpass = None
        tools = host_files("bin")
        if (
            not connection.from_ssh_config
            and tools is not None
            and (tools / "ht-askpass").is_file()
            and passwords.has_password(connection.identifier)
        ):
            askpass = tools / "ht-askpass"
        return self.ssh_tab(connection, "🔒", connection.command_line(askpass))
