"""The SSH connection manager and connection editor."""

from __future__ import annotations

from .. import passwords
from ..connections import (
    Connection,
    ConnectionError,
    ConnectionStore,
    unique_identifier as unique_connection_id,
    validate as validate_connection,
)
from .common import FormPage, confirm, mark_suggested, show_error
from ..runtime import GLib, Gtk, Pango
from ..themes import ThemeManager


class ConnectionEditorDialog(Gtk.Dialog):
    def __init__(self, parent: Gtk.Window, themes: ThemeManager, connection: Connection | None) -> None:
        super().__init__(title="Conexão SSH", transient_for=parent, modal=True)
        self.connection = connection
        self.add_buttons("Cancelar", Gtk.ResponseType.CANCEL, "Salvar", Gtk.ResponseType.OK)
        mark_suggested(self)
        self.set_default_size(520, -1)
        page = FormPage()
        page.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.NEVER)
        self.get_content_area().pack_start(page, True, True, 0)
        self.name_entry = Gtk.Entry(text=connection.name if connection else "")
        self.name_entry.set_placeholder_text("ex.: Produção — banco de dados")
        self.destination = Gtk.Entry(text=connection.destination if connection else "")
        self.destination.set_placeholder_text("usuário@host ou alias do ~/.ssh/config")
        self.port = Gtk.SpinButton.new_with_range(0, 65535, 1)
        self.port.set_value(connection.port or 0 if connection else 0)
        self.identity = Gtk.Entry(text=connection.identity_file if connection else "")
        self.identity.set_placeholder_text("opcional, ex.: ~/.ssh/id_ed25519")
        self.options = Gtk.Entry(text=connection.options if connection else "")
        self.options.set_placeholder_text("opcional, ex.: -J bastiao -A")
        self.theme = Gtk.ComboBoxText()
        self.theme.append("", "Mesmo tema da janela")
        for theme in themes.all():
            self.theme.append(theme.identifier, theme.name)
        self.theme.set_active_id(connection.theme if connection and connection.theme else "")
        self.confirm_switch = Gtk.Switch(active=connection.confirm if connection else False)
        page.heading("CONEXÃO")
        page.field("Nome", self.name_entry)
        page.field("Destino", self.destination)
        page.field("Porta (0 = padrão)", self.port)
        page.field("Chave (identity file)", self.identity)
        page.field("Opções extras do ssh", self.options)
        page.heading("SEGURANÇA VISUAL")
        page.field("Tema da aba", self.theme, "Use um tema chamativo, como Alerta Vermelho, para servidores de produção.")
        page.field("Confirmar antes de conectar", self.confirm_switch)
        page.heading("SENHA")
        self.password: Gtk.Entry | None = None
        self.forget_password: Gtk.CheckButton | None = None
        saved = connection is not None and not connection.from_ssh_config and passwords.has_password(connection.identifier)
        if passwords.available():
            self.password = Gtk.Entry(visibility=False, input_purpose=Gtk.InputPurpose.PASSWORD)
            self.password.set_placeholder_text(
                "salva no chaveiro — digite para trocar" if saved else "opcional — guardada no chaveiro do sistema"
            )
            page.field("Senha do servidor", self.password)
            if saved:
                self.forget_password = Gtk.CheckButton(label="Esquecer a senha salva")
                page.full(self.forget_password)
            page.hint(
                "A senha fica criptografada no chaveiro do sistema (aberto pelo seu login), nunca nos arquivos do "
                "terminal, e só responde à pergunta de senha deste servidor. Mais seguro ainda: use "
                "“Acesso por chave…” no gerenciador e não guarde senha nenhuma."
            )
        else:
            page.hint("Para guardar senhas no chaveiro, instale o pacote gir1.2-secret-1. Ou use “Acesso por chave…”.")
        self.show_all()

    def password_change(self) -> tuple[str, str]:
        """("keep", ""), ("set", password) or ("forget", "")."""
        if self.forget_password is not None and self.forget_password.get_active():
            return "forget", ""
        typed = self.password.get_text() if self.password is not None else ""
        return ("set", typed) if typed else ("keep", "")

    def value(self, identifier: str | None, taken: set[str] = frozenset()) -> Connection:
        """The connection typed in; a new one (identifier None) gets a free id from its name."""
        port = self.port.get_value_as_int()
        name = " ".join(self.name_entry.get_text().split())
        connection = Connection(
            identifier=identifier or unique_connection_id(name, taken),
            name=name,
            destination=self.destination.get_text().strip(),
            port=port or None,
            identity_file=self.identity.get_text().strip(),
            options=self.options.get_text().strip(),
            theme=self.theme.get_active_id() or "",
            confirm=self.confirm_switch.get_active(),
        )
        validate_connection(connection)
        return connection


KEY_SETUP_RESPONSE = 1


class SSHManagerDialog(Gtk.Dialog):
    """Saved connections plus hosts from ~/.ssh/config."""

    def __init__(self, parent: Gtk.Window, store: ConnectionStore, themes: ThemeManager) -> None:
        super().__init__(title="Conexões SSH", transient_for=parent, modal=True)
        self.store = store
        self.themes = themes
        self.add_buttons("Fechar", Gtk.ResponseType.CANCEL, "Conectar", Gtk.ResponseType.OK)
        mark_suggested(self)
        self.set_default_size(620, 420)
        body = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8, margin=12)
        self.get_content_area().pack_start(body, True, True, 0)
        self.listbox = Gtk.ListBox()
        self.listbox.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.listbox.connect("row-activated", lambda *_: self.response(Gtk.ResponseType.OK))
        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_min_content_width(320)
        scroller.add(self.listbox)
        body.pack_start(scroller, True, True, 0)
        controls = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        buttons = (
            ("Nova…", self.add), ("Editar…", self.edit), ("Remover", self.remove),
            ("Acesso por chave…", self.request_key_setup),
        )
        for label, callback in buttons:
            button = Gtk.Button(label=label)
            button.connect("clicked", lambda *_args, action=callback: action())
            controls.pack_start(button, False, False, 0)
        hint = Gtk.Label(label="Hosts do ~/.ssh/config aparecem automaticamente; edite um para personalizá-lo.", xalign=0)
        hint.set_line_wrap(True)
        hint.set_max_width_chars(22)
        hint.get_style_context().add_class("panel-hint")
        controls.pack_end(hint, False, False, 0)
        body.pack_start(controls, False, False, 0)
        self.connections: list[Connection] = []
        self.refresh()
        self.show_all()

    def refresh(self, select: str | None = None) -> None:
        self.connections = self.store.load()
        for child in self.listbox.get_children():
            child.destroy()
        for connection in self.connections:
            row = Gtk.ListBoxRow()
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, margin=8)
            title = Gtk.Label(xalign=0)
            badge = "  · do ~/.ssh/config" if connection.from_ssh_config else ""
            lock = "⚠ " if connection.confirm else ""
            if not connection.from_ssh_config and passwords.has_password(connection.identifier):
                badge += "  · 🔑 senha no chaveiro"
            title.set_markup(f"<b>{GLib.markup_escape_text(lock + connection.name)}</b>{GLib.markup_escape_text(badge)}")
            detail = Gtk.Label(label=connection.command_line(), xalign=0)
            detail.set_ellipsize(Pango.EllipsizeMode.END)
            detail.get_style_context().add_class("panel-hint")
            box.pack_start(title, False, False, 0)
            box.pack_start(detail, False, False, 0)
            row.add(box)
            self.listbox.add(row)
        self.listbox.show_all()
        index = next((i for i, c in enumerate(self.connections) if c.identifier == select), 0)
        row = self.listbox.get_row_at_index(index)
        if row is not None:
            self.listbox.select_row(row)

    def selected_connection(self) -> Connection | None:
        row = self.listbox.get_selected_row()
        return self.connections[row.get_index()] if row is not None and row.get_index() < len(self.connections) else None

    def saved(self) -> list[Connection]:
        return [connection for connection in self.connections if not connection.from_ssh_config]

    def run_editor(self, connection: Connection | None, identifier: str | None) -> Connection | None:
        editor = ConnectionEditorDialog(self, self.themes, connection)
        taken = {item.identifier for item in self.connections}
        result = None
        while editor.run() == Gtk.ResponseType.OK:
            try:
                result = editor.value(identifier, taken)
                break
            except (ConnectionError, ValueError) as error:
                show_error(editor, "Conexão inválida", str(error))
        change, secret = editor.password_change()
        editor.destroy()
        if result is not None:
            if change == "set" and not passwords.store(result.identifier, result.name, secret):
                show_error(self, "Senha não guardada", "O chaveiro do sistema não está disponível ou recusou a senha.")
            elif change == "forget":
                passwords.forget(result.identifier)
        return result

    def add(self) -> None:
        created = self.run_editor(None, None)
        if created is not None:
            self.persist(self.saved() + [created], created.identifier)

    def edit(self) -> None:
        current = self.selected_connection()
        if current is None:
            return
        taken = {connection.identifier for connection in self.connections}
        base = self.store.promote(current, taken) if current.from_ssh_config else current
        updated = self.run_editor(base, base.identifier)
        if updated is None:
            return
        saved = [updated if item.identifier == updated.identifier else item for item in self.saved()]
        if current.from_ssh_config:
            saved.append(updated)
        self.persist(saved, updated.identifier)

    def request_key_setup(self) -> None:
        if self.selected_connection() is not None:
            self.response(KEY_SETUP_RESPONSE)

    def remove(self) -> None:
        current = self.selected_connection()
        if current is None:
            return
        if current.from_ssh_config:
            show_error(self, "Host do ~/.ssh/config", "Remova este host editando o seu ~/.ssh/config.")
            return
        if confirm(self, f"Remover “{current.name}”?", "A conexão e a senha salva dela são apagadas.", "Remover"):
            passwords.forget(current.identifier)
            self.persist([item for item in self.saved() if item.identifier != current.identifier])

    def persist(self, connections: list[Connection], select: str | None = None) -> None:
        if not self.store.save(connections):
            show_error(self, "Não foi possível salvar", str(self.store.path))
        self.refresh(select)
