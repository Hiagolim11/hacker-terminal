"""The Preferences dialog."""

from __future__ import annotations

import logging
import dataclasses
import shlex
import shutil
from pathlib import Path

from ..actions import ActionStore
from ..background import FIT_LABELS
from ..config import Preferences
from ..constants import DEFAULT_THEME
from .common import FormPage, choice_combo, confirm, mark_suggested, show_error
from .editors import ProfileEditorDialog, ShortcutsEditor, ThemeEditorDialog
from ..dropdown import (
    DEFAULT_KEY,
    bind_xfce,
    launch_command,
    unbind_xfce,
    xfce_available,
    xfce_binding,
    xfce_dropdown_key,
)
from ..fonts import choose_font, installed_font_families
from ..keysound import KeySoundEngine, PackError, SYNTH_SWITCHES, list_packs, load_pack, packs_directory
from ..profiles import ProfileError, ProfileManager, slugify
from ..runtime import GLib, Gio, Gtk, Pango
from ..terminal import shell_argv
from ..themes import Theme, ThemeError, ThemeManager

LOGGER = logging.getLogger(__name__)


MAX_PACK_BYTES = 100 * 1024 * 1024


def install_sound_pack(source: Path) -> str:
    """Validate a sound pack and copy it into the user's pack folder."""
    if packs_directory() in source.resolve().parents:
        return source.name
    total = sum(item.stat().st_size for item in source.rglob("*") if item.is_file())
    if total > MAX_PACK_BYTES:
        raise PackError("o pacote tem mais de 100 MB")
    load_pack(source)  # raises PackError for anything unusable
    base = slugify(source.name) or "pacote"
    destination = packs_directory() / base
    counter = 2
    while destination.exists():
        destination = packs_directory() / f"{base}-{counter}"
        counter += 1
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(
            source,
            destination,
            ignore=lambda folder, names: [name for name in names if (Path(folder) / name).is_symlink()],
        )
    except OSError as error:
        raise PackError(f"não foi possível copiar o pacote: {error}") from error
    return destination.name




# Debian/Kali packages for fonts suggested by the built-in themes.
FONT_PACKAGES = {"terminus": "fonts-terminus-otb", "ibm 3270": "fonts-3270"}


def shlex_first(command: str) -> str:
    try:
        parts = shlex.split(command)
    except ValueError:
        return command
    return parts[0] if parts else ""


class PreferencesDialog(Gtk.Dialog):
    CURSOR_SHAPES = (("block", "Bloco"), ("ibeam", "Barra"), ("underline", "Sublinhado"))
    CURSOR_BLINK = (("system", "Seguir o sistema"), ("on", "Piscar"), ("off", "Fixo"))

    def __init__(
        self,
        parent: Gtk.Window,
        preferences: Preferences,
        theme_manager: ThemeManager,
        profile_manager: ProfileManager,
        action_store: ActionStore | None = None,
    ) -> None:
        super().__init__(title="Preferências", transient_for=parent, modal=True)
        self.action_store = action_store or ActionStore()
        self.preferences = preferences
        self.theme_manager = theme_manager
        self.profile_manager = profile_manager
        self.add_buttons("Cancelar", Gtk.ResponseType.CANCEL, "Salvar", Gtk.ResponseType.OK)
        mark_suggested(self)
        self.set_default_response(Gtk.ResponseType.OK)
        self.set_resizable(True)
        self.set_default_size(min(600, max(400, parent.get_allocated_width() - 60)), 620)
        self.pages = Gtk.Notebook()
        self.pages.set_scrollable(True)
        self.get_content_area().pack_start(self.pages, True, True, 0)

        # --- Geral
        general = FormPage()
        self.scroller = general
        self.profile = Gtk.ComboBoxText()
        self.profile_ids: list[str] = []
        self.refresh_profiles(preferences.profile)
        self.panel = Gtk.Switch(active=preferences.panel_visible)
        self.restore_session = Gtk.Switch(active=preferences.restore_session)
        self.shell = Gtk.Entry(text=preferences.shell)
        self.shell.set_placeholder_text("Automático ($SHELL, zsh ou bash)")
        self.confirm_paste = Gtk.Switch(active=preferences.confirm_paste)
        self.bell_notify = Gtk.Switch(active=preferences.bell_notify)
        general.heading("Perfil")
        general.field("Perfil", self.profile)
        self.profile_note = general.hint("", column=1, width=1)
        profile_actions = Gtk.FlowBox()
        profile_actions.set_selection_mode(Gtk.SelectionMode.NONE)
        profile_actions.set_halign(Gtk.Align.START)
        profile_actions.set_max_children_per_line(3)
        profile_actions.set_column_spacing(4)
        profile_actions.set_row_spacing(4)
        save_profile = Gtk.Button(label="Salvar como perfil…")
        save_profile.set_tooltip_text("Cria um perfil com as configurações mostradas neste diálogo")
        save_profile.connect("clicked", self.new_profile)
        self.edit_profile_button = Gtk.Button(label="Editar…")
        self.edit_profile_button.connect("clicked", self.edit_profile)
        self.delete_profile_button = Gtk.Button(label="Remover")
        self.delete_profile_button.connect("clicked", self.delete_profile)
        for button in (save_profile, self.edit_profile_button, self.delete_profile_button):
            profile_actions.add(button)
        general.full(profile_actions, column=1, width=1)
        general.heading("Sessão")
        general.field("Shell", self.shell, "Comando do shell, com argumentos. Vazio usa o shell de login.")
        self.shell_status = general.hint("", column=1, width=1)
        general.field("Restaurar sessão", self.restore_session)
        general.field("Painel lateral", self.panel)
        general.heading("Segurança e alertas")
        general.field(
            "Confirmar colagem perigosa",
            self.confirm_paste,
            "Pergunta antes de colar várias linhas ou caracteres de controle.",
        )
        general.field("Avisar quando houver bell", self.bell_notify, "Marca a aba e a janela quando um programa toca o sinal.")
        self.shell_integration = Gtk.Switch(active=preferences.shell_integration)
        general.field(
            "Integração com o shell (zsh e bash)",
            self.shell_integration,
            "Marca cada comando: pular entre prompts, copiar a saída do último comando e avisos com o código de saída. Vale para novos painéis.",
        )
        self.command_marks = Gtk.Switch(active=preferences.command_marks)
        general.field("Marcar comandos na margem", self.command_marks, "Faixa ao lado de cada comando: cor de destaque se deu certo, vermelha se falhou.")
        self.command_history = Gtk.Switch(active=preferences.command_history)
        general.field(
            "Guardar histórico de comandos", self.command_history,
            "Ctrl+Shift+H busca os comandos de todas as abas. Fica só neste computador (permissão 0600); "
            "comandos digitados com um espaço no início não são guardados.",
        )
        self.notify_commands = Gtk.Switch(active=preferences.notify_commands)
        general.field(
            "Avisar quando um comando longo terminar",
            self.notify_commands,
            "Notificação do sistema quando um comando termina numa aba que você não está olhando.",
        )
        self.notify_after = Gtk.SpinButton.new_with_range(3, 3600, 1)
        self.notify_after.set_value(preferences.notify_after)
        general.field("Considerar longo a partir de (segundos)", self.notify_after)
        general.heading("Terminal suspenso")
        self.dropdown_height = Gtk.SpinButton.new_with_range(25, 90, 5)
        self.dropdown_height.set_value(preferences.dropdown_height)
        general.field("Altura (% da tela)", self.dropdown_height)
        self.dropdown_autohide = Gtk.Switch(active=preferences.dropdown_autohide)
        general.field("Esconder ao perder o foco", self.dropdown_autohide)
        self.dropdown_command = launch_command()
        test_button = Gtk.Button(label="Testar agora")
        test_button.set_tooltip_text("Abre ou esconde o terminal suspenso, como o atalho faria")
        test_button.connect("clicked", lambda *_: self.test_dropdown())
        if xfce_available():
            # Full width and wrapping, so it stays usable in a narrow window.
            self.dropdown_status = Gtk.Label(xalign=0)
            self.dropdown_status.set_line_wrap(True)
            general.full(self.dropdown_status)
            # Two short rows: they fit the dialog's narrowest width as well.
            key_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            key_box.pack_start(Gtk.Label(label="Tecla"), False, False, 0)
            self.dropdown_key = Gtk.Entry(text=xfce_dropdown_key() or DEFAULT_KEY, width_chars=12)
            self.dropdown_key.set_tooltip_text("Formato GTK: F12, <Super>grave, <Primary><Alt>t…")
            self.dropdown_key.connect("changed", lambda *_: self.schedule_dropdown_status())
            self.dropdown_key.connect("activate", lambda *_: self.bind_dropdown_key())
            key_box.pack_start(self.dropdown_key, False, False, 0)
            self.dropdown_bind = Gtk.Button(label="Ativar atalho")
            self.dropdown_bind.connect("clicked", lambda *_: self.bind_dropdown_key())
            self.dropdown_unbind = Gtk.Button(label="Desativar")
            self.dropdown_unbind.connect("clicked", lambda *_: self.unbind_dropdown_key())
            key_box.pack_start(self.dropdown_bind, False, False, 0)
            actions_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            actions_box.pack_start(self.dropdown_unbind, False, False, 0)
            actions_box.pack_start(test_button, False, False, 0)
            for row in (key_box, actions_box):
                row.set_halign(Gtk.Align.START)
                general.full(row)
            self.dropdown_status_source = 0
            self.update_dropdown_status()
            self.connect("destroy", lambda *_: self.cancel_dropdown_status())
        else:
            general.hint(
                "Crie um atalho global no seu ambiente gráfico (por exemplo, F12) que execute o comando abaixo."
            )
            general.full(test_button)
        command_label = Gtk.Label(label=f"Comando: {self.dropdown_command}", xalign=0, selectable=True)
        command_label.set_line_wrap(True)
        command_label.set_line_wrap_mode(Pango.WrapMode.CHAR)
        command_label.get_style_context().add_class("panel-hint")
        general.full(command_label)
        self.pages.append_page(general, Gtk.Label(label="Geral"))

        # --- Aparência
        appearance = FormPage()
        self.theme = Gtk.ComboBoxText()
        self.theme_ids: list[str] = []
        self.refresh_themes(preferences.theme)
        theme_actions = Gtk.FlowBox()
        theme_actions.set_selection_mode(Gtk.SelectionMode.NONE)
        theme_actions.set_halign(Gtk.Align.START)
        theme_actions.set_max_children_per_line(5)
        theme_actions.set_min_children_per_line(3)
        theme_actions.set_column_spacing(4)
        theme_actions.set_row_spacing(4)
        self.edit_theme_button = Gtk.Button(label="Editar…")
        self.delete_theme_button = Gtk.Button(label="Remover")
        for label, callback in (
            ("Novo…", self.new_theme),
            (None, self.edit_theme),
            (None, self.delete_theme),
            ("Importar…", self.import_theme),
            ("Exportar…", self.export_theme),
        ):
            button = Gtk.Button(label=label) if label else (
                self.edit_theme_button if callback == self.edit_theme else self.delete_theme_button
            )
            button.connect("clicked", callback)
            theme_actions.add(button)
        self.font = Gtk.FontButton()
        chosen = choose_font(preferences.font)
        self.font.set_font_name(f"{chosen.family} {preferences.font_size}")
        self.opacity = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 30, 100, 5)
        self.opacity.set_value(preferences.opacity)
        self.opacity.set_value_pos(Gtk.PositionType.RIGHT)
        self.opacity.set_digits(0)
        self.effects = Gtk.Switch(active=preferences.effects)
        self.sound = Gtk.Switch(active=preferences.sound)
        appearance.heading("Tema")
        appearance.field("Tema", self.theme)
        appearance.full(theme_actions, column=1, width=1)
        suggestion = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.font_suggestion = Gtk.Label(xalign=0)
        self.font_suggestion.set_line_wrap(True)
        self.font_suggestion.get_style_context().add_class("panel-hint")
        self.use_suggested_font = Gtk.Button(label="Usar")
        self.use_suggested_font.connect("clicked", self.apply_suggested_font)
        suggestion.pack_start(self.font_suggestion, True, True, 0)
        suggestion.pack_start(self.use_suggested_font, False, False, 0)
        self.font_suggestion.set_no_show_all(True)
        self.use_suggested_font.set_no_show_all(True)
        appearance.full(suggestion, column=1, width=1)
        appearance.field("Fonte", self.font)
        appearance.field("Opacidade da janela (%)", self.opacity)
        composited = parent.get_screen() is not None and parent.get_screen().is_composited()
        appearance.hint(
            "Transparência ativa." if composited else "A transparência requer um compositor de janelas ativo.",
            column=1,
            width=1,
        )
        appearance.heading("Imagem de fundo")
        self.background_path = preferences.background_image
        self.background_chooser = Gtk.FileChooserButton(title="Escolher imagem de fundo", action=Gtk.FileChooserAction.OPEN)
        images = Gtk.FileFilter()
        images.set_name("Imagens")
        images.add_pixbuf_formats()
        self.background_chooser.add_filter(images)
        if self.background_path and Path(self.background_path).expanduser().is_file():
            self.background_chooser.set_filename(str(Path(self.background_path).expanduser()))
        self.background_chooser.connect("file-set", self.on_background_chosen)
        remove_background = Gtk.Button(label="Remover")
        remove_background.connect("clicked", lambda *_: self.on_background_chosen(None))
        background_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        background_row.pack_start(self.background_chooser, True, True, 0)
        background_row.pack_start(remove_background, False, False, 0)
        appearance.field("Imagem", background_row)
        self.background_opacity = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 5, 90, 5)
        self.background_opacity.set_value(preferences.background_opacity)
        self.background_opacity.set_value_pos(Gtk.PositionType.RIGHT)
        self.background_opacity.set_digits(0)
        self.background_opacity.connect("format-value", lambda _scale, value: f"{value:.0f}%")
        appearance.field("Opacidade da imagem", self.background_opacity)
        self.background_fit = choice_combo(FIT_LABELS, preferences.background_fit)
        appearance.field("Encaixe", self.background_fit)
        appearance.hint(
            "A imagem fica atrás do texto, em todos os painéis. Entre 15% e 30% ela aparece "
            "sem atrapalhar a leitura.",
            column=1,
            width=1,
        )
        self.update_background_controls()
        appearance.heading("Efeitos")
        appearance.field("Efeitos visuais", self.effects)
        self.pages.append_page(appearance, Gtk.Label(label="Aparência"))

        # --- Terminal
        terminal = FormPage()
        self.cursor_shape = choice_combo(self.CURSOR_SHAPES, preferences.cursor_shape)
        self.cursor_blink = choice_combo(self.CURSOR_BLINK, preferences.cursor_blink)
        self.scrollback = Gtk.SpinButton.new_with_range(1_000, 200_000, 1_000)
        self.scrollback.set_value(preferences.scrollback_lines)
        self.bold_is_bright = Gtk.Switch(active=preferences.bold_is_bright)
        self.copy_on_select = Gtk.Switch(active=preferences.copy_on_select)
        self.scroll_on_output = Gtk.Switch(active=preferences.scroll_on_output)
        self.scroll_on_keystroke = Gtk.Switch(active=preferences.scroll_on_keystroke)
        terminal.heading("Cursor")
        terminal.field("Formato", self.cursor_shape)
        terminal.field("Piscar", self.cursor_blink)
        terminal.heading("Texto e seleção")
        terminal.field("Negrito usa cores claras", self.bold_is_bright)
        terminal.field("Copiar ao selecionar", self.copy_on_select)
        terminal.heading("Rolagem")
        terminal.field("Linhas do histórico", self.scrollback)
        terminal.field("Rolar ao receber saída", self.scroll_on_output)
        terminal.field("Rolar ao digitar", self.scroll_on_keystroke)
        terminal.hint("Ctrl + roda do mouse também altera o tamanho da fonte.")
        self.pages.append_page(terminal, Gtk.Label(label="Terminal"))

        # --- Som do teclado
        sound_page = FormPage()
        self.key_switch = Gtk.ComboBoxText()
        self.refresh_key_sources(preferences.key_switch)
        self.key_volume = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 5)
        self.key_volume.set_value(preferences.key_volume)
        self.key_volume.set_value_pos(Gtk.PositionType.RIGHT)
        self.key_volume.set_digits(0)
        self.key_release = Gtk.Switch(active=preferences.key_release)
        pack_actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        import_pack = Gtk.Button(label="Importar pacote…")
        import_pack.set_tooltip_text("Pasta de um pacote Mechvibes (config.json) ou com press.wav / release.wav")
        import_pack.connect("clicked", self.import_sound_pack)
        open_packs = Gtk.Button(label="Abrir pasta")
        open_packs.connect("clicked", self.open_packs_folder)
        pack_actions.pack_start(import_pack, False, False, 0)
        pack_actions.pack_start(open_packs, False, False, 0)
        self.key_test = Gtk.Entry()
        self.key_test.set_placeholder_text("Digite aqui para ouvir…")
        self.key_test.connect("key-press-event", self.on_key_test_press)
        self.key_test.connect("key-release-event", self.on_key_test_release)
        sound_page.heading("Som do teclado")
        sound_page.field("Ativar", self.sound)
        sound_page.field("Switch", self.key_switch)
        self.key_status = sound_page.hint("", column=1, width=1)
        sound_page.field("Volume", self.key_volume)
        sound_page.field("Som ao soltar a tecla", self.key_release, "Toca o retorno da haste (top-out) ao soltar.")
        sound_page.heading("Testar")
        sound_page.full(self.key_test)
        sound_page.hint(
            "Os sons tocam na descida e na subida de cada tecla, sem trava entre teclas; "
            "segurar uma tecla não repete o som, como num teclado real."
        )
        sound_page.heading("Pacotes gravados")
        sound_page.full(pack_actions)
        sound_page.hint(
            "Para o som exato de um teclado real, importe uma gravação: pacotes Mechvibes "
            "(com config.json) ou uma pasta com press.wav, release.wav, space-press.wav etc."
        )
        self.pages.append_page(sound_page, Gtk.Label(label="Som do teclado"))
        engine = KeySoundEngine.shared()
        engine.on_loaded.append(self.update_key_status)
        self.connect("destroy", lambda *_: engine.on_loaded.remove(self.update_key_status)
                     if self.update_key_status in engine.on_loaded else None)
        for widget, signal in (
            (self.key_switch, "changed"),
            (self.key_volume, "value-changed"),
            (self.key_release, "notify::active"),
        ):
            widget.connect(signal, lambda *_: self.preview_key_sound())
        self.preview_key_sound()

        # --- Atalhos
        self.shortcuts_editor = ShortcutsEditor(preferences.shortcuts)
        self.pages.append_page(self.shortcuts_editor, Gtk.Label(label="Atalhos"))

        self.profile_handler = self.profile.connect("changed", self.on_profile_changed)
        self.theme.connect("changed", lambda *_: self.update_theme_buttons())
        self.effects.connect("notify::active", lambda *_: self.update_font_suggestion())
        self.shell.connect("changed", lambda *_: self.update_shell_status())
        self.update_profile_note()
        self.update_theme_buttons()
        self.update_shell_status()
        self.show_all()

    def selected_profile(self) -> str:
        index = self.profile.get_active()
        return self.profile_ids[index] if 0 <= index < len(self.profile_ids) else "developer"

    def dropdown_key_name(self) -> str | None:
        keyval, modifiers = Gtk.accelerator_parse(self.dropdown_key.get_text().strip())
        return Gtk.accelerator_name(keyval, modifiers) if keyval else None

    def cancel_dropdown_status(self) -> None:
        if self.dropdown_status_source:
            GLib.source_remove(self.dropdown_status_source)
            self.dropdown_status_source = 0

    def schedule_dropdown_status(self) -> None:
        # Debounced: each check asks xfconf, no need to do it per keystroke.
        if self.dropdown_status_source:
            GLib.source_remove(self.dropdown_status_source)
        self.dropdown_status_source = GLib.timeout_add(300, self.update_dropdown_status)

    def update_dropdown_status(self) -> bool:
        self.dropdown_status_source = 0
        key = self.dropdown_key_name()
        active_key = xfce_dropdown_key()
        context = self.dropdown_status.get_style_context()
        for name in ("status-ok", "status-warning"):
            context.remove_class(name)
        if key is None:
            text, style = "⚠ Tecla inválida. Exemplos: F12, <Super>grave, <Primary><Alt>t", "status-warning"
            bind_ok = False
        elif active_key == key:
            text, style = f"✓ Ativo — aperte {key} para abrir e esconder o terminal suspenso.", "status-ok"
            bind_ok = False
        elif (used_by := xfce_binding(key)) and "--dropdown" not in used_by:
            text, style = f"⚠ {key} já é usado por “{used_by}”. Escolha outra tecla.", "status-warning"
            bind_ok = False
        elif active_key:
            text, style = f"✓ Ativo em {active_key}. Clique em Ativar atalho para trocar para {key}.", "status-ok"
            bind_ok = True
        else:
            text, style = f"○ Ainda não ativo — clique em Ativar atalho para usar {key}.", None
            bind_ok = True
        self.dropdown_status.set_text(text)
        if style:
            context.add_class(style)
        self.dropdown_bind.set_sensitive(bind_ok)
        self.dropdown_unbind.set_sensitive(active_key is not None)
        return False

    def bind_dropdown_key(self) -> None:
        key = self.dropdown_key_name()
        if key is None:
            self.update_dropdown_status()
            return
        previous = xfce_dropdown_key()
        ok, message = bind_xfce(key, self.dropdown_command)
        if not ok:
            show_error(self, "Atalho não ativado", message)
        elif previous and previous != key:
            unbind_xfce(previous)  # one key at a time
        self.update_dropdown_status()

    def unbind_dropdown_key(self) -> None:
        active = xfce_dropdown_key()
        if active is not None:
            ok, message = unbind_xfce(active)
            if not ok:
                show_error(self, "Atalho não removido", message)
        self.update_dropdown_status()

    def test_dropdown(self) -> None:
        try:
            Gio.Subprocess.new(shlex.split(self.dropdown_command), Gio.SubprocessFlags.NONE)
        except GLib.Error as error:
            show_error(self, "Não foi possível abrir o terminal suspenso", error.message)

    def update_profile_note(self) -> None:
        profile = self.profile_manager.get(self.selected_profile())
        note = profile.description or "Perfil personalizado."
        if not profile.builtin:
            note += f"\nDiretório inicial: {profile.working_directory}"
            if profile.own_actions:
                note += " · ações rápidas próprias"
        self.profile_note.set_text(note)
        custom = not profile.builtin
        self.edit_profile_button.set_sensitive(custom)
        self.delete_profile_button.set_sensitive(custom)

    def refresh_profiles(self, selected: str) -> None:
        """Rebuild the profile list without re-applying the selected profile."""
        handler = getattr(self, "profile_handler", None)
        if handler is not None:
            self.profile.handler_block(handler)
        self.profile.remove_all()
        self.profile_ids = []
        active = 0
        for index, profile in enumerate(self.profile_manager.all()):
            self.profile.append_text(profile.name if profile.builtin else f"{profile.name} — personalizado")
            self.profile_ids.append(profile.identifier)
            if profile.identifier == selected:
                active = index
        self.profile.set_active(active)
        if handler is not None:
            self.profile.handler_unblock(handler)

    def new_profile(self, _button) -> None:
        dialog = ProfileEditorDialog(self, self.profile_manager, None)
        self.run_profile_editor(dialog)

    def edit_profile(self, _button) -> None:
        profile = self.profile_manager.get(self.selected_profile())
        if profile.builtin:
            return
        self.run_profile_editor(ProfileEditorDialog(self, self.profile_manager, profile))

    def run_profile_editor(self, dialog: "ProfileEditorDialog") -> None:
        while dialog.run() == Gtk.ResponseType.OK:
            try:
                saved = dialog.save(self.collect(), self.action_store)
            except ProfileError as error:
                show_error(dialog, "Perfil inválido", str(error))
                continue
            self.refresh_profiles(saved.identifier)
            self.update_profile_note()
            break
        dialog.destroy()

    def delete_profile(self, _button) -> None:
        profile = self.profile_manager.get(self.selected_profile())
        if profile.builtin or not confirm(
            self,
            f"Remover o perfil “{profile.name}”?",
            "As configurações e ações rápidas próprias deste perfil serão apagadas.",
            "Remover",
        ):
            return
        try:
            self.profile_manager.delete_custom(profile.identifier)
        except ProfileError as error:
            show_error(self, "Não foi possível remover", str(error))
        self.refresh_profiles("developer")
        self.update_profile_note()

    def update_shell_status(self) -> None:
        value = self.shell.get_text().strip()
        argv = shell_argv(value, warn=False)
        if value and Path(argv[0]).name != Path(shlex_first(value)).name:
            self.shell_status.set_text(f"Não encontrado; será usado {argv[0]}.")
        else:
            self.shell_status.set_text("Executa: " + " ".join(argv))

    def refresh_key_sources(self, selected: str) -> None:
        self.key_switch.remove_all()
        for identifier, label in SYNTH_SWITCHES.items():
            self.key_switch.append(identifier, f"{label} — sintetizado")
        for pack in list_packs():
            self.key_switch.append(f"pack:{pack.identifier}", f"{pack.name} — gravado")
        if not self.key_switch.set_active_id(selected):
            self.key_switch.set_active_id("brown")

    def preview_key_sound(self) -> None:
        source = self.key_switch.get_active_id() or "brown"
        self.key_status.set_text("Carregando…")
        KeySoundEngine.shared().configure(source, int(self.key_volume.get_value()), self.key_release.get_active())
        self.update_key_status()

    def update_key_status(self) -> None:
        engine = KeySoundEngine.shared()
        if not engine.available():
            self.key_status.set_text("Áudio indisponível: instale o GStreamer (python3-gst-1.0).")
        elif engine.loading_key is not None:
            self.key_status.set_text("Carregando…")
        elif engine.last_error:
            self.key_status.set_text(f"Pacote inválido: {engine.last_error}. Usando o som sintetizado.")
        elif engine.bank is not None:
            self.key_status.set_text(f"Pronto: {engine.bank.name}")

    def on_key_test_press(self, _entry, event) -> bool:
        KeySoundEngine.shared().press(event.hardware_keycode, event.keyval)
        return False

    def on_key_test_release(self, _entry, event) -> bool:
        KeySoundEngine.shared().release(event.hardware_keycode, event.keyval)
        return False

    def import_sound_pack(self, _button) -> None:
        chooser = Gtk.FileChooserDialog(
            title="Importar pacote de sons",
            transient_for=self,
            action=Gtk.FileChooserAction.SELECT_FOLDER,
        )
        chooser.add_buttons("Cancelar", Gtk.ResponseType.CANCEL, "Importar", Gtk.ResponseType.OK)
        response = chooser.run()
        folder = chooser.get_filename()
        chooser.destroy()
        if response != Gtk.ResponseType.OK or not folder:
            return
        try:
            identifier = install_sound_pack(Path(folder))
        except PackError as error:
            show_error(self, "Pacote de sons inválido", str(error))
            return
        self.refresh_key_sources(f"pack:{identifier}")

    @staticmethod
    def open_packs_folder(_button) -> None:
        folder = packs_directory()
        try:
            folder.mkdir(parents=True, exist_ok=True)
            Gio.AppInfo.launch_default_for_uri(folder.as_uri(), None)
        except (OSError, GLib.Error) as error:
            LOGGER.warning("não foi possível abrir %s: %s", folder, error)

    def update_font_suggestion(self) -> None:
        theme = self.theme_manager.get(self.selected_theme())
        notes = []
        installed = None
        if theme.font:
            installed = installed_font_families().get(theme.font.casefold())
            if installed:
                notes.append(f"Fonte sugerida: {installed}.")
            else:
                package = FONT_PACKAGES.get(theme.font.casefold())
                hint = f" — instale o pacote {package}" if package else ""
                notes.append(f"Fonte sugerida: {theme.font} (não instalada{hint}).")
        if (theme.curvature or theme.glow or theme.noise) and not self.effects.get_active():
            notes.append("Ligue os Efeitos visuais para o brilho, a curvatura e o ruído da tela.")
        self.font_suggestion.set_text(" ".join(notes))
        self.font_suggestion.set_visible(bool(notes))
        self.use_suggested_font.set_visible(installed is not None)
        self.suggested_font = installed

    def apply_suggested_font(self, _button) -> None:
        if not getattr(self, "suggested_font", None):
            return
        size = Pango.FontDescription(self.font.get_font_name()).get_size() // Pango.SCALE or 12
        self.font.set_font_name(f"{self.suggested_font} {size}")

    def update_theme_buttons(self) -> None:
        self.update_font_suggestion()
        custom = self.theme_manager.is_custom(self.selected_theme())
        self.edit_theme_button.set_label("Editar…" if custom else "Duplicar…")
        self.edit_theme_button.set_tooltip_text(
            "Editar as cores deste tema" if custom else "Criar um tema personalizado a partir deste"
        )
        self.delete_theme_button.set_sensitive(custom)

    def on_profile_changed(self, _combo) -> None:
        profile = self.profile_manager.get(self.selected_profile())
        self.update_profile_note()
        self.refresh_themes(profile.theme)
        family = profile.font if profile.font is not None else self.preferences.font
        self.font.set_font_name(f"{choose_font(family).family} {profile.font_size}")
        if profile.shell is not None or not profile.builtin:
            self.shell.set_text(profile.shell or "")
        if profile.cursor_shape is not None:
            self.cursor_shape.set_active_id(profile.cursor_shape)
        if profile.opacity is not None:
            self.opacity.set_value(profile.opacity)
        self.effects.set_active(profile.effects)
        self.sound.set_active(profile.sound)
        self.panel.set_active(profile.panel_visible)

    def refresh_themes(self, selected: str) -> None:
        self.theme.remove_all()
        self.theme_ids = []
        active = 0
        for index, theme in enumerate(self.theme_manager.all()):
            suffix = "" if theme.builtin else " — personalizado"
            self.theme.append_text(theme.name + suffix)
            self.theme_ids.append(theme.identifier)
            if theme.identifier == selected:
                active = index
        self.theme.set_active(active)

    def selected_theme(self) -> str:
        index = self.theme.get_active()
        return self.theme_ids[index] if 0 <= index < len(self.theme_ids) else DEFAULT_THEME

    def open_theme_editor(self, base: Theme) -> None:
        dialog = ThemeEditorDialog(self, self.theme_manager, base)
        while dialog.run() == Gtk.ResponseType.OK:
            try:
                saved = self.theme_manager.save_custom(dialog.build_theme())
            except ThemeError as error:
                self.show_theme_error(str(error))
                continue
            self.refresh_themes(saved.identifier)
            break
        dialog.destroy()

    def new_theme(self, _button) -> None:
        self.open_theme_editor(dataclasses.replace(self.theme_manager.get(self.selected_theme()), builtin=True))

    def edit_theme(self, _button) -> None:
        self.open_theme_editor(self.theme_manager.get(self.selected_theme()))

    def delete_theme(self, _button) -> None:
        theme = self.theme_manager.get(self.selected_theme())
        dialog = Gtk.MessageDialog(
            transient_for=self,
            modal=True,
            message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.NONE,
            text=f"Remover o tema “{theme.name}”?",
        )
        dialog.format_secondary_text("O arquivo do tema será apagado. Exporte-o antes se quiser guardar uma cópia.")
        dialog.add_buttons("Cancelar", Gtk.ResponseType.CANCEL, "Remover", Gtk.ResponseType.OK)
        response = dialog.run()
        dialog.destroy()
        if response != Gtk.ResponseType.OK:
            return
        try:
            self.theme_manager.delete_custom(theme.identifier)
        except ThemeError as error:
            self.show_theme_error(str(error))
        self.refresh_themes(DEFAULT_THEME)

    def import_theme(self, _button) -> None:
        chooser = Gtk.FileChooserDialog(
            title="Importar tema",
            transient_for=self,
            action=Gtk.FileChooserAction.OPEN,
        )
        chooser.add_buttons("Cancelar", Gtk.ResponseType.CANCEL, "Importar", Gtk.ResponseType.OK)
        file_filter = Gtk.FileFilter()
        file_filter.set_name("Tema do Hacker Terminal (*.ini)")
        file_filter.add_pattern("*.ini")
        chooser.add_filter(file_filter)
        if chooser.run() == Gtk.ResponseType.OK:
            try:
                imported = self.theme_manager.import_theme(Path(chooser.get_filename()))
                self.refresh_themes(imported.identifier)
            except ThemeError as error:
                self.show_theme_error(str(error))
        chooser.destroy()

    def export_theme(self, _button) -> None:
        chooser = Gtk.FileChooserDialog(
            title="Exportar tema",
            transient_for=self,
            action=Gtk.FileChooserAction.SAVE,
        )
        chooser.add_buttons("Cancelar", Gtk.ResponseType.CANCEL, "Exportar", Gtk.ResponseType.OK)
        chooser.set_do_overwrite_confirmation(True)
        chooser.set_current_name(f"{self.selected_theme()}.ini")
        if chooser.run() == Gtk.ResponseType.OK:
            try:
                self.theme_manager.export_theme(self.selected_theme(), Path(chooser.get_filename()))
            except ThemeError as error:
                self.show_theme_error(str(error))
        chooser.destroy()

    def show_theme_error(self, message: str) -> None:
        dialog = Gtk.MessageDialog(
            transient_for=self,
            modal=True,
            message_type=Gtk.MessageType.ERROR,
            buttons=Gtk.ButtonsType.CLOSE,
            text="Tema inválido",
        )
        dialog.format_secondary_text(message)
        dialog.run()
        dialog.destroy()

    def apply(self) -> None:
        self.apply_to(self.preferences)

    def collect(self) -> Preferences:
        """The settings currently shown in the dialog, without saving them."""
        snapshot = dataclasses.replace(self.preferences, shortcuts=dict(self.preferences.shortcuts))
        self.apply_to(snapshot)
        return snapshot

    def on_background_chosen(self, chooser) -> None:
        if chooser is None:
            self.background_path = ""
            self.background_chooser.unselect_all()
        else:
            self.background_path = chooser.get_filename() or ""
        self.update_background_controls()

    def update_background_controls(self) -> None:
        has_image = bool(self.background_path)
        self.background_opacity.set_sensitive(has_image)
        self.background_fit.set_sensitive(has_image)

    def apply_to(self, target: Preferences) -> None:
        target.profile = self.selected_profile()
        target.theme = self.selected_theme()
        description = Pango.FontDescription(self.font.get_font_name())
        target.font = description.get_family()
        size = description.get_size() // Pango.SCALE
        if size:
            target.font_size = size
        target.scrollback_lines = self.scrollback.get_value_as_int()
        target.effects = self.effects.get_active()
        target.sound = self.sound.get_active()
        target.key_switch = self.key_switch.get_active_id() or "brown"
        target.key_volume = int(self.key_volume.get_value())
        target.key_release = self.key_release.get_active()
        target.panel_visible = self.panel.get_active()
        target.restore_session = self.restore_session.get_active()
        target.shell = self.shell.get_text().strip()
        target.confirm_paste = self.confirm_paste.get_active()
        target.bell_notify = self.bell_notify.get_active()
        target.notify_commands = self.notify_commands.get_active()
        target.shell_integration = self.shell_integration.get_active()
        target.command_marks = self.command_marks.get_active()
        target.command_history = self.command_history.get_active()
        target.notify_after = self.notify_after.get_value_as_int()
        target.dropdown_height = self.dropdown_height.get_value_as_int()
        target.dropdown_autohide = self.dropdown_autohide.get_active()
        target.opacity = int(self.opacity.get_value())
        target.background_image = self.background_path
        target.background_opacity = int(self.background_opacity.get_value())
        target.background_fit = self.background_fit.get_active_id() or "cover"
        target.cursor_shape = self.cursor_shape.get_active_id() or "block"
        target.cursor_blink = self.cursor_blink.get_active_id() or "system"
        target.bold_is_bright = self.bold_is_bright.get_active()
        target.copy_on_select = self.copy_on_select.get_active()
        target.scroll_on_output = self.scroll_on_output.get_active()
        target.scroll_on_keystroke = self.scroll_on_keystroke.get_active()
        target.shortcuts = self.shortcuts_editor.overrides()
        target.normalize()
