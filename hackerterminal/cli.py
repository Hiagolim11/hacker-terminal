"""Command-line interface and application bootstrap."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from .actions import ActionStore
from .config import AppConfig, ConfigStore, Preferences, env_enabled
from .constants import APP_NAME, VERSION
from .fonts import choose_font
from .launcher import separate_requested
from .logs import log_path, setup_logging
from .profiles import ProfileManager
from .runtime import Gdk, Gtk, Vte
from .session import SessionStore
from .shortcuts import SHORTCUT_ACTIONS, ShortcutMap, accelerator_label
from .terminal import resolve_shell
from .themes import ThemeManager
from .ui import HackerTerminalApp


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Terminal profissional nativo em GTK/VTE")
    parser.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    parser.add_argument("--diagnose", action="store_true", help="verifica configuração e dependências e sai")
    parser.add_argument("--debug", action="store_true", help="registra mensagens detalhadas no terminal e no log")
    parser.add_argument("--list-shortcuts", action="store_true", help="lista os atalhos de teclado em uso e sai")
    parser.add_argument("--font", metavar="FAMILIA", help="família de fonte instalada")
    parser.add_argument("--font-size", type=int, metavar="6-32", help="tamanho da fonte nesta janela")
    parser.add_argument("--theme", metavar="ID", help="tema usado nesta janela")
    parser.add_argument("--list-themes", action="store_true", help="lista os temas disponíveis e sai")
    parser.add_argument("--profile", metavar="ID", help="aplica um perfil nesta janela")
    parser.add_argument("--list-profiles", action="store_true", help="lista os perfis disponíveis e sai")
    parser.add_argument("--no-boot", action="store_true", help="pula a animação inicial")
    parser.add_argument("--no-effects", action="store_true", help="desativa chuva digital e scanlines")
    parser.add_argument("--no-sound", action="store_true", help="desativa os efeitos sonoros")
    parser.add_argument("--no-panel", action="store_true", help="inicia com o painel lateral oculto")
    parser.add_argument(
        "--separate",
        action="store_true",
        help="abre a janela num processo próprio (por padrão as janelas compartilham um processo)",
    )
    parser.add_argument(
        "--dropdown",
        action="store_true",
        help="abre ou esconde o terminal suspenso (estilo Quake); associe a um atalho global",
    )
    parser.add_argument(
        "--working-directory",
        metavar="DIRETORIO",
        help="diretório inicial da sessão (padrão: pasta pessoal)",
    )
    parser.add_argument(
        "-e",
        "--execute",
        nargs=argparse.REMAINDER,
        metavar="COMANDO",
        help="executa um comando em vez do shell de login",
    )
    return parser


def diagnose(
    store: ConfigStore,
    themes: ThemeManager,
    preferences: Preferences,
    requested_font: str | None = None,
) -> int:
    requested = requested_font or os.environ.get("HACKER_TERMINAL_FONT") or preferences.font
    choice = choose_font(requested)
    print(f"Hacker Terminal {VERSION}")
    print(f"GTK: {Gtk.get_major_version()}.{Gtk.get_minor_version()}.{Gtk.get_micro_version()}")
    print(f"VTE: {Vte.get_major_version()}.{Vte.get_minor_version()}.{Vte.get_micro_version()}")
    print(f"Fonte selecionada: {choice.family}")
    print(f"Powerline: {'OK' if choice.has_powerline else 'NAO DISPONIVEL'}")
    print(f"Nerd Font: {'OK' if choice.has_nerd_symbols else 'NAO DISPONIVEL'}")
    print(f"Shell: {resolve_shell()}")
    print(f"Configuração: {store.path}")
    print(f"Tema: {themes.get(preferences.theme).name} ({themes.get(preferences.theme).identifier})")
    print(f"Temas disponíveis: {len(themes.all())}")
    print(f"Log: {log_path()}")
    from .terminal import HAS_TERMPROPS
    integration = "disponível (zsh e bash)" if HAS_TERMPROPS else "indisponível (requer VTE 0.78 ou mais novo)"
    print(f"Integração com o shell: {integration}")
    shortcuts = ShortcutMap(preferences.shortcuts)
    for error in themes.errors:
        print(f"Aviso de tema: {error}", file=sys.stderr)
    profiles = ProfileManager()
    print(f"Perfil: {profiles.get(preferences.profile).name} ({preferences.profile})")
    for error in profiles.errors:
        print(f"Aviso de perfil: {error}", file=sys.stderr)
    for error in shortcuts.errors:
        print(f"Aviso de atalho: {error}", file=sys.stderr)
    for identifiers in shortcuts.conflicts().values():
        print(f"Aviso de atalho: conflito entre {', '.join(dict.fromkeys(identifiers))}", file=sys.stderr)
    if requested_font and choice.family.casefold() != requested_font.casefold():
        print(f"Aviso: a fonte solicitada '{requested_font}' não está instalada.", file=sys.stderr)
        return 1
    if not choice.has_powerline:
        print("Aviso: instale uma Nerd Font para renderizar prompts Powerline por completo.", file=sys.stderr)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    setup_logging(args.debug)
    store = ConfigStore()
    action_store = ActionStore()
    session_store = SessionStore()
    themes = ThemeManager()
    profiles = ProfileManager()
    if args.list_themes:
        for theme in themes.all():
            source = "interno" if theme.builtin else "personalizado"
            print(f"{theme.identifier}\t{theme.name}\t{source}")
        return 0
    if args.list_shortcuts:
        bindings = ShortcutMap(store.load().shortcuts).bindings
        for action in SHORTCUT_ACTIONS:
            print(f"{action.identifier}\t{accelerator_label(bindings[action.identifier])}\t{action.label}")
        return 0
    if args.list_profiles:
        for profile in profiles.all():
            source = "interno" if profile.builtin else "personalizado"
            print(f"{profile.identifier}\t{profile.name}\t{source}\t{profile.description}")
        return 0
    preferences = store.load()
    if args.profile:
        if args.profile not in profiles.profiles:
            parser.error(f"perfil desconhecido: {args.profile} (use --list-profiles)")
        profiles.apply(args.profile, preferences)
    if args.theme:
        if args.theme not in themes.themes:
            parser.error(f"tema desconhecido: {args.theme} (use --list-themes)")
        preferences.theme = args.theme
    if args.diagnose:
        return diagnose(store, themes, preferences, args.font)
    if args.font:
        preferences.font = args.font
    if args.font_size is not None:
        if not 6 <= args.font_size <= 32:
            parser.error("--font-size deve estar entre 6 e 32")
        preferences.font_size = args.font_size
    preferences.boot = preferences.boot and not args.no_boot and env_enabled("HACKER_TERMINAL_BOOT")
    preferences.effects = preferences.effects and not args.no_effects and env_enabled("HACKER_TERMINAL_EFFECTS")
    preferences.sound = preferences.sound and not args.no_sound and env_enabled("HACKER_TERMINAL_SOUND")
    preferences.panel_visible = preferences.panel_visible and not args.no_panel
    # Options that change a window's look need their own process: the theme
    # CSS applies to every window of a process.
    separate = (
        args.separate or separate_requested() or any((
            args.theme, args.profile, args.font, args.font_size is not None,
            args.no_effects, args.no_sound, args.no_panel,
        ))
    )
    if args.dropdown:
        # Pops up instantly and keeps its own tabs, apart from the main window.
        preferences.boot = False
        session_store = SessionStore(session_store.path.with_name("session-dropdown.json"))
    preferences.normalize()
    working_directory = (
        Path(args.working_directory).expanduser().resolve()
        if args.working_directory
        else profiles.working_directory(preferences.profile)
    )
    if not working_directory.is_dir():
        parser.error(f"diretório inicial inexistente: {working_directory}")
    if args.execute is not None and not args.execute:
        parser.error("-e/--execute requer um comando")
    config = AppConfig(preferences, tuple(args.execute or ()), working_directory)
    provider = Gtk.CssProvider()
    provider.load_from_data(themes.get(preferences.theme).css())
    Gtk.Window.set_default_icon_name(APP_NAME)
    settings = Gtk.Settings.get_default()
    if settings is not None:
        settings.set_property("gtk-application-prefer-dark-theme", themes.get(preferences.theme).dark)
    screen = Gdk.Screen.get_default()
    if screen is not None:
        # One above APPLICATION: VTE installs its own padding at that priority on
        # the widget, which would otherwise win; the user's gtk.css (800) still does.
        Gtk.StyleContext.add_provider_for_screen(screen, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1)
    return HackerTerminalApp(
        config,
        store,
        action_store,
        session_store,
        themes,
        profiles,
        provider,
        dropdown=args.dropdown,
        separate=separate,
    # Only the shared instance takes a command line; the others would read
    # leftover arguments as files to open and quit.
    ).run([sys.argv[0], *(sys.argv[1:] if argv is None else argv)] if not (separate or args.dropdown) else [sys.argv[0]])
