"""Editors for shortcuts, themes and profiles."""

from __future__ import annotations

import dataclasses
import os
from pathlib import Path

from ..actions import ActionStore
from ..config import Preferences
from .common import FormPage, mark_suggested
from ..profiles import Profile, ProfileError, ProfileManager, profile_from_preferences
from ..runtime import GLib, Gdk, Gtk
from ..shortcuts import MODIFIER_MASK, SHORTCUT_ACTIONS, ShortcutMap, accelerator_label, accelerator_name
from ..themes import THEME_COLOR_FIELDS, Theme, ThemeError, ThemeManager


CRT_LABELS = (
    ("glow", "Brilho do fósforo"),
    ("vignette", "Vinheta"),
    ("noise", "Ruído estático"),
    ("flicker", "Cintilação"),
    ("curvature", "Curvatura da tela"),
)


class ShortcutCaptureDialog(Gtk.Dialog):
    """Wait for one key combination. Backspace disables, Esc cancels."""

    def __init__(self, parent: Gtk.Window, label: str) -> None:
        super().__init__(title="Definir atalho", transient_for=parent, modal=True)
        self.accelerator: str | None = None
        self.add_button("Cancelar", Gtk.ResponseType.CANCEL)
        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, margin=20)
        title = Gtk.Label(xalign=0)
        title.set_markup(f"<b>{GLib.markup_escape_text(label)}</b>")
        body.pack_start(title, False, False, 0)
        body.pack_start(Gtk.Label(label="Pressione a nova combinação de teclas.", xalign=0), False, False, 0)
        hint = Gtk.Label(label="Backspace desativa o atalho · Esc cancela", xalign=0)
        hint.get_style_context().add_class("panel-hint")
        body.pack_start(hint, False, False, 0)
        self.get_content_area().pack_start(body, True, True, 0)
        self.connect("key-press-event", self.on_key_press)
        self.show_all()

    def on_key_press(self, _dialog, event) -> bool:
        keyval = Gdk.keyval_to_lower(event.keyval)
        mods = event.state & MODIFIER_MASK
        if keyval == Gdk.KEY_Escape and not mods:
            self.response(Gtk.ResponseType.CANCEL)
            return True
        if keyval == Gdk.KEY_BackSpace and not mods:
            self.accelerator = ""
            self.response(Gtk.ResponseType.OK)
            return True
        if not Gtk.accelerator_valid(keyval, mods):
            return True  # a lone modifier; keep waiting
        self.accelerator = accelerator_name(keyval, mods)
        self.response(Gtk.ResponseType.OK)
        return True


class ShortcutsEditor(Gtk.Box):
    def __init__(self, overrides: dict[str, str]) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8, margin=16)
        self.bindings = ShortcutMap(overrides).bindings
        self.buttons: dict[str, Gtk.Button] = {}
        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        grid = Gtk.Grid(column_spacing=12, row_spacing=4)
        for row, action in enumerate(SHORTCUT_ACTIONS):
            label = Gtk.Label(label=action.label, xalign=0)
            label.set_hexpand(True)
            button = Gtk.Button()
            button.set_tooltip_text("Clique para alterar")
            button.connect("clicked", lambda _button, value=action: self.capture(value))
            reset = Gtk.Button.new_from_icon_name("edit-undo-symbolic", Gtk.IconSize.MENU)
            reset.set_relief(Gtk.ReliefStyle.NONE)
            reset.set_tooltip_text("Restaurar o padrão")
            reset.connect("clicked", lambda _button, value=action: self.set_binding(value.identifier, value.default))
            grid.attach(label, 0, row, 1, 1)
            grid.attach(button, 1, row, 1, 1)
            grid.attach(reset, 2, row, 1, 1)
            self.buttons[action.identifier] = button
        scroller.add(grid)
        self.pack_start(scroller, True, True, 0)
        self.warning = Gtk.Label(xalign=0)
        self.warning.set_line_wrap(True)
        self.warning.get_style_context().add_class("panel-hint")
        self.pack_start(self.warning, False, False, 0)
        reset_all = Gtk.Button(label="Restaurar todos os atalhos")
        reset_all.set_halign(Gtk.Align.START)
        reset_all.connect("clicked", lambda *_: self.reset_all())
        self.pack_start(reset_all, False, False, 0)
        self.refresh()

    def capture(self, action) -> None:
        dialog = ShortcutCaptureDialog(self.get_toplevel(), action.label)
        response = dialog.run()
        accelerator = dialog.accelerator
        dialog.destroy()
        if response == Gtk.ResponseType.OK and accelerator is not None:
            self.set_binding(action.identifier, accelerator)

    def set_binding(self, identifier: str, value: str) -> None:
        self.bindings[identifier] = value
        self.refresh()

    def reset_all(self) -> None:
        self.bindings = ShortcutMap().bindings
        self.refresh()

    def overrides(self) -> dict[str, str]:
        return ShortcutMap(self.bindings).overrides()

    def refresh(self) -> None:
        for identifier, button in self.buttons.items():
            button.set_label(accelerator_label(self.bindings[identifier]))
            button.get_child().get_style_context().add_class("shortcut-label")
        conflicts = ShortcutMap(self.bindings).conflicts()
        labels = {action.identifier: action.label for action in SHORTCUT_ACTIONS}
        if conflicts:
            names = ["“" + "” e “".join(labels[item] for item in dict.fromkeys(ids)) + "”" for ids in conflicts.values()]
            self.warning.set_text("Conflito: " + "; ".join(names) + " usam a mesma tecla. Só a primeira ação será executada.")
        else:
            self.warning.set_text("Clique em um atalho para gravar uma nova combinação.")


class ThemeEditorDialog(Gtk.Dialog):
    """Create or edit a user theme with color pickers."""

    LABELS = {
        "background": "Fundo da janela",
        "surface": "Superfícies (cabeçalho, painel)",
        "foreground": "Texto da interface",
        "accent": "Destaque",
        "border": "Bordas",
        "muted": "Texto secundário",
        "danger": "Alerta",
        "terminal_background": "Fundo do terminal",
        "terminal_foreground": "Texto do terminal",
        "cursor": "Cursor",
        "selection_background": "Fundo da seleção",
        "selection_foreground": "Texto da seleção",
        "matrix_color": "Cor da chuva digital",
    }
    ANSI_NAMES = ("Preto", "Vermelho", "Verde", "Amarelo", "Azul", "Magenta", "Ciano", "Branco")

    def __init__(self, parent: Gtk.Window, manager: ThemeManager, base: Theme) -> None:
        editing = not base.builtin
        super().__init__(title="Editar tema" if editing else "Novo tema", transient_for=parent, modal=True)
        self.manager = manager
        self.base = base
        self.editing = editing
        self.add_buttons("Cancelar", Gtk.ResponseType.CANCEL, "Salvar tema", Gtk.ResponseType.OK)
        mark_suggested(self)
        self.set_default_size(560, 620)
        page = FormPage()
        self.get_content_area().pack_start(page, True, True, 0)
        self.name_entry = Gtk.Entry(text=base.name if editing else f"{base.name} (personalizado)")
        self.author_entry = Gtk.Entry(text=base.author if editing else os.environ.get("USER", ""))
        page.heading("Identidade")
        page.field("Nome", self.name_entry)
        page.field("Autor", self.author_entry)
        self.colors: dict[str, Gtk.ColorButton] = {}
        sections = {"interface": "Interface", "terminal": "Terminal", "effects": "Efeitos"}
        current = None
        for section, _key, attribute in THEME_COLOR_FIELDS:
            if section != current:
                page.heading(sections[section])
                current = section
            button = Gtk.ColorButton.new_with_rgba(self.parse(getattr(base, attribute)))
            button.set_title(self.LABELS[attribute])
            self.colors[attribute] = button
            page.field(self.LABELS[attribute], button)
        self.scanlines = Gtk.SpinButton.new_with_range(0, 1, 0.01)
        self.scanlines.set_digits(2)
        self.scanlines.set_value(base.scanline_opacity)
        page.field("Intensidade das scanlines", self.scanlines)
        self.crt: dict[str, Gtk.Scale] = {}
        page.heading("Tela CRT (com efeitos visuais ligados)")
        for key, label in CRT_LABELS:
            scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 1, 0.05)
            scale.set_digits(2)
            scale.set_value(getattr(base, key))
            scale.set_value_pos(Gtk.PositionType.RIGHT)
            self.crt[key] = scale
            page.field(label, scale)
        self.rain = Gtk.Switch(active=base.rain)
        page.field("Mostrar chuva digital", self.rain)
        self.font_entry = Gtk.Entry(text=base.font or "")
        self.font_entry.set_placeholder_text("Opcional, ex.: Terminus")
        page.field("Fonte sugerida", self.font_entry)
        page.heading("Paleta ANSI")
        ansi_grid = Gtk.Grid(column_spacing=6, row_spacing=4, column_homogeneous=True)
        self.ansi: list[Gtk.ColorButton] = []
        for index, color in enumerate(base.ansi):
            button = Gtk.ColorButton.new_with_rgba(self.parse(color))
            name = self.ANSI_NAMES[index % 8] + (" claro" if index >= 8 else "")
            button.set_title(name)
            button.set_tooltip_text(name)
            ansi_grid.attach(button, index % 8, index // 8 * 2, 1, 1)
            if index < 8:
                caption = Gtk.Label(label=self.ANSI_NAMES[index][:3])
                caption.get_style_context().add_class("swatch-label")
                ansi_grid.attach(caption, index, 2, 1, 1)
            self.ansi.append(button)
        page.full(ansi_grid)
        page.hint("Linha de cima: cores normais · linha do meio: variantes claras.")
        self.show_all()

    @staticmethod
    def parse(value: str) -> Gdk.RGBA:
        color = Gdk.RGBA()
        color.parse(value)
        return color

    @staticmethod
    def hex(button: Gtk.ColorButton) -> str:
        color = button.get_rgba()
        return "#" + "".join(f"{round(channel * 255):02x}" for channel in (color.red, color.green, color.blue))

    def build_theme(self) -> Theme:
        name = self.name_entry.get_text().strip()
        if not name:
            raise ThemeError("informe um nome para o tema")
        identifier = self.base.identifier if self.editing else self.manager.unique_identifier(name)
        values = {attribute: self.hex(button) for attribute, button in self.colors.items()}
        return dataclasses.replace(
            self.base,
            identifier=identifier,
            name=name,
            author=self.author_entry.get_text().strip() or "Desconhecido",
            scanline_opacity=round(self.scanlines.get_value(), 2),
            rain=self.rain.get_active(),
            font=self.font_entry.get_text().strip() or None,
            **{key: round(scale.get_value(), 2) for key, scale in self.crt.items()},
            ansi=tuple(self.hex(button) for button in self.ansi),
            path=None,
            builtin=False,
            **values,
        )


class ProfileEditorDialog(Gtk.Dialog):
    """Create a profile from the current settings, or edit a custom one."""

    def __init__(self, parent: Gtk.Window, manager: ProfileManager, profile: Profile | None) -> None:
        super().__init__(
            title="Editar perfil" if profile else "Novo perfil",
            transient_for=parent,
            modal=True,
        )
        self.manager = manager
        self.profile = profile
        self.add_buttons("Cancelar", Gtk.ResponseType.CANCEL, "Salvar perfil", Gtk.ResponseType.OK)
        mark_suggested(self)
        self.set_default_size(500, -1)
        page = FormPage()
        page.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.NEVER)
        self.get_content_area().pack_start(page, True, True, 0)
        self.name_entry = Gtk.Entry(text=profile.name if profile else "")
        self.name_entry.set_placeholder_text("ex.: Pentest, Projeto X")
        self.name_entry.set_activates_default(True)
        self.set_default_response(Gtk.ResponseType.OK)
        self.description_entry = Gtk.Entry(text=profile.description if profile else "")
        self.directory = Gtk.FileChooserButton(title="Diretório inicial", action=Gtk.FileChooserAction.SELECT_FOLDER)
        start = Path(profile.working_directory).expanduser() if profile else Path.home()
        self.directory.set_filename(str(start if start.is_dir() else Path.home()))
        self.own_actions = Gtk.Switch(active=profile.own_actions if profile else False)
        page.heading("Perfil")
        page.field("Nome", self.name_entry)
        page.field("Descrição", self.description_entry)
        page.field("Diretório inicial", self.directory)
        page.field(
            "Ações rápidas próprias",
            self.own_actions,
            "O perfil terá sua própria lista de ações, começando com uma cópia da atual.",
        )
        self.update_settings = Gtk.Switch(active=profile is None)
        if profile is not None:
            page.field("Atualizar com as configurações atuais", self.update_settings)
            page.hint("Desligado mantém o tema, a fonte e os demais ajustes salvos no perfil.")
        else:
            page.hint(
                "O perfil guarda o tema, a fonte, o shell, o cursor, a opacidade, os efeitos "
                "e o painel mostrados nas Preferências."
            )
        self.show_all()

    def directory_value(self) -> str:
        chosen = self.directory.get_filename()
        if not chosen:
            return "~"
        path = Path(chosen)
        try:
            return "~/" + str(path.relative_to(Path.home())) if path != Path.home() else "~"
        except ValueError:
            return str(path)

    def save(self, current: Preferences, current_actions: ActionStore) -> Profile:
        name = self.name_entry.get_text().strip()
        if not name:
            raise ProfileError("informe um nome para o perfil")
        identifier = self.profile.identifier if self.profile else self.manager.unique_identifier(name)
        description = self.description_entry.get_text().strip()
        own_actions = self.own_actions.get_active()
        if self.profile is None or self.update_settings.get_active():
            profile = profile_from_preferences(
                identifier, name, description, current, self.directory_value(), own_actions
            )
        else:
            profile = dataclasses.replace(
                self.profile,
                name=name,
                description=description,
                working_directory=self.directory_value(),
                own_actions=own_actions,
                path=None,
            )
        had_actions = self.profile is not None and self.profile.own_actions
        saved = self.manager.save_custom(profile)
        actions_path = self.manager.actions_path(saved.identifier)
        if actions_path is not None and not had_actions and not actions_path.exists():
            # Start the profile's list from the actions in use right now.
            ActionStore(actions_path).save(current_actions.load())
        return saved
