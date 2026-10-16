"""Validated built-in and user-installable color themes."""

from __future__ import annotations

import configparser
import os
import re
import tempfile
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from .config import default_config_path
from .constants import DEFAULT_THEME

THEME_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,47}$")
HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")


def slugify(text: str) -> str:
    """ASCII identifier from a display name: "Laboratório Ágil" -> "laboratorio-agil"."""
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", ascii_text.casefold()).strip("-")[:40]


class ThemeError(ValueError):
    """Raised when a theme cannot be parsed or validated."""


@dataclass(frozen=True)
class Theme:
    identifier: str
    name: str
    author: str
    background: str
    surface: str
    foreground: str
    accent: str
    border: str
    muted: str
    danger: str
    terminal_background: str
    terminal_foreground: str
    cursor: str
    selection_background: str
    selection_foreground: str
    matrix_color: str
    scanline_opacity: float
    ansi: tuple[str, ...]
    path: Path | None = None
    builtin: bool = False
    # CRT look (all optional; 0 disables). Drawn only with visual effects on.
    glow: float = 0.0        # phosphor light emitted from the screen
    vignette: float = 0.0    # darker screen edges
    noise: float = 0.0       # animated static
    flicker: float = 0.0     # brightness flicker
    curvature: float = 0.0   # rounded tube corners and inner bezel shadow
    rain: bool = True        # digital rain
    font: str | None = None  # suggested font family

    @property
    def dark(self) -> bool:
        """Dark themes ask GTK for its dark variant (menus, dialogs, scrollbars)."""
        return luminance(self.background) < 0.35

    @property
    def high_contrast(self) -> bool:
        """Never dim text in themes made for maximum legibility."""
        return contrast_ratio(self.terminal_foreground, self.terminal_background) >= 18

    @property
    def animated(self) -> bool:
        return self.rain or self.noise > 0 or self.flicker > 0

    @property
    def tube_padding(self) -> int:
        """Inner terminal padding that keeps text clear of the tube corners."""
        return round(4 + 10 * self.curvature) if self.curvature else 2

    @property
    def tube_radius(self) -> float:
        # A corner arc of radius r stays off the first glyph at (p, p) while
        # r < (2 + sqrt 2) * p, so 3 * padding is always safe.
        return 3.0 * self.tube_padding if self.curvature else 0.0

    def css(self, opacity: float = 1.0) -> bytes:
        """Create GTK CSS using the theme's validated colors.

        ``opacity`` below 1 makes the window and terminal backgrounds
        translucent; it only has a visible effect under a compositor.
        """
        opacity = max(0.0, min(1.0, opacity))
        window_background = _rgba(self.background, opacity)
        terminal_background = _rgba(self.terminal_background, opacity)
        accent_soft = _mix(self.accent, self.surface, 0.18)
        accent_faint = _mix(self.accent, self.background, 0.10)
        raised = _mix(self.foreground, self.surface, 0.05)
        return f"""
window, .app-root {{ background-color: {window_background}; color: {self.foreground}; }}
.app-root {{ background-color: transparent; }}
tooltip, tooltip.background {{
  background-color: {self.surface}; color: {self.foreground};
  border: 1px solid {self.border}; border-radius: 6px;
}}
tooltip label {{ color: {self.foreground}; }}

headerbar {{
  background-image: none; background-color: {self.surface}; color: {self.foreground};
  border-bottom: 1px solid {self.border}; box-shadow: none; min-height: 40px; padding: 0 6px;
}}
headerbar .title {{ font-weight: 700; color: {self.foreground}; }}
headerbar .subtitle {{ color: {self.muted}; font-family: monospace; font-size: 10px; opacity: 1; }}
headerbar button.titlebutton {{ color: {self.muted}; background-image: none; box-shadow: none; }}
headerbar button.titlebutton:hover {{ color: {self.foreground}; background-color: {raised}; }}
.header-group {{ margin: 0 2px; }}
.header-action {{
  color: {self.muted}; background-image: none; background-color: transparent;
  border: 1px solid transparent; border-radius: 6px; box-shadow: none; text-shadow: none;
  min-width: 30px; min-height: 28px; padding: 0 4px; -gtk-icon-shadow: none;
}}
.header-action:hover {{ color: {self.foreground}; background-color: {raised}; border-color: {self.border}; }}
.header-action:active, .header-action:checked {{ color: {self.accent}; background-color: {accent_soft}; }}
.header-action:disabled {{ opacity: 0.35; }}
.header-separator {{ background-color: {self.border}; min-width: 1px; margin: 9px 4px; }}

.workspace {{ padding: 6px; }}
.statusbar-row {{
  background-color: {self.surface}; border-top: 1px solid {self.border}; padding: 3px 10px;
}}
.status, .status-context {{ color: {self.muted}; font-family: monospace; font-size: 10px; }}
.status-context {{ color: {self.foreground}; }}
.status-badge {{
  color: {self.accent}; background-color: {accent_faint}; border: 1px solid {accent_soft};
  border-radius: 9px; padding: 0 7px; font-family: monospace; font-size: 10px; font-weight: 700;
}}

.terminal-frame {{
  background-color: {terminal_background}; border: 1px solid {self.border};
  border-radius: 8px; padding: 6px 2px 4px 8px;
}}
.terminal-frame paned > separator {{
  background-color: transparent; background-image: image({self.border}); background-size: 1px 1px;
  border: 0; min-width: 1px; min-height: 1px;
}}
.terminal-frame paned > separator:hover {{ background-image: image({self.accent}); }}
.terminal-frame paned.horizontal > separator {{
  background-repeat: repeat-y; background-position: center; margin: 0 -4px; padding: 0 4px;
}}
.terminal-frame paned.vertical > separator {{
  background-repeat: repeat-x; background-position: center; margin: -4px 0; padding: 4px 0;
}}
.terminal-frame paned.horizontal > .terminal-pane {{ margin: 0 6px; }}
.terminal-frame paned.vertical > .terminal-pane {{ margin: 4px 0; }}
.pane-inactive {{ opacity: {1.0 if self.high_contrast else 0.62}; }}
vte-terminal {{ background-color: transparent; color: {self.terminal_foreground}; padding: {self.tube_padding}px; }}

notebook {{ background-color: transparent; }}
notebook > header {{ background-color: transparent; border: 0; box-shadow: none; padding: 0 0 6px 0; }}
notebook > header > tabs {{ margin: 0; }}
notebook > header tab {{
  background-color: {self.surface}; color: {self.muted}; border: 1px solid {self.border};
  border-radius: 7px; padding: 3px 4px 3px 10px; margin: 0 4px 0 0; min-height: 22px; box-shadow: none;
}}
notebook > header tab:hover {{ color: {self.foreground}; background-color: {raised}; }}
notebook > header tab:checked {{
  background-color: {self.terminal_background}; color: {self.foreground};
  border-color: {self.border}; box-shadow: inset 0 -2px {self.accent};
}}
notebook > header tab label {{ font-size: 11px; }}
notebook > header > arrow {{ color: {self.muted}; }}
.viewer {{ background-color: {terminal_background}; border: 1px solid {self.border}; border-radius: 8px; }}
.viewer-bar {{
  background-color: {self.surface}; border-bottom: 1px solid {self.border};
  border-radius: 8px 8px 0 0; padding: 3px 6px;
}}
.viewer-title {{ color: {self.foreground}; font-weight: 700; }}
.viewer-info {{ color: {self.muted}; font-family: monospace; font-size: 10px; }}
.viewer-button {{
  color: {self.muted}; background-image: none; background-color: transparent;
  border: 1px solid transparent; border-radius: 6px; box-shadow: none; min-width: 26px; min-height: 24px;
}}
.viewer-button:hover {{ color: {self.foreground}; background-color: {raised}; border-color: {self.border}; }}
.viewer-canvas, .viewer-canvas viewport {{ background-color: {terminal_background}; }}
.viewer-table {{ background-color: {terminal_background}; color: {self.terminal_foreground}; font-size: 11px; }}
.viewer-table:selected {{ background-color: {accent_soft}; color: {self.foreground}; }}
.viewer-table header button {{
  background-image: none; background-color: {self.surface}; color: {self.muted};
  border-color: {self.border}; box-shadow: none; font-family: monospace; font-size: 10px; padding: 2px 6px;
}}
.viewer-sheets > header {{ background-color: {self.surface}; border-top: 1px solid {self.border}; padding: 2px 4px; }}
.tab-recording label {{ color: {self.danger}; }}
.tab-recording label:first-child {{ font-weight: 700; }}
.terminal-frame.broadcast {{ border: 2px solid {self.danger}; }}
window.dropdown {{ border-bottom: 2px solid {self.accent}; }}
.pane-name {{ background: {self.surface}; color: {self.accent}; padding: 2px 10px; font-size: 0.85em; font-weight: 700; border-bottom: 1px solid {self.border}; }}
.pane-inactive .pane-name {{ color: {self.muted}; font-weight: 400; }}
.tab-broadcast label {{ color: {self.danger}; font-weight: 700; }}
.tab-done label {{ color: {self.accent}; font-weight: 700; }}
.tab-bell label {{ color: {self.danger}; font-weight: 700; }}
.shortcut-label {{ font-family: monospace; color: {self.accent}; }}
.shortcut-row {{ padding: 2px 0; }}
.swatch-label {{ color: {self.muted}; font-size: 10px; }}
.tab-close {{
  color: {self.muted}; background-image: none; background-color: transparent;
  border: 0; border-radius: 5px; box-shadow: none; min-width: 18px; min-height: 18px; padding: 0;
}}
.tab-close:hover {{ color: {self.danger}; background-color: {self.background}; }}

scrollbar, scrollbar trough {{ background-color: transparent; border: 0; }}
scrollbar.vertical {{ min-width: 8px; }}
scrollbar slider {{
  background-color: {self.border}; border: 2px solid transparent; border-radius: 6px;
  min-width: 5px; min-height: 34px;
}}
scrollbar slider:hover {{ background-color: {self.muted}; }}
scrollbar slider:active {{ background-color: {self.accent}; }}

.search-bar {{
  background-color: {self.surface}; border: 1px solid {self.border}; border-radius: 7px;
  padding: 5px 6px; margin: 6px 6px 2px 0;
}}
.search-entry, entry {{
  color: {self.foreground}; background-color: {self.background}; background-image: none;
  border: 1px solid {self.border}; border-radius: 6px; padding: 4px 8px; box-shadow: none;
  caret-color: {self.accent};
}}
.search-entry:focus, entry:focus {{ border-color: {self.accent}; box-shadow: 0 0 0 1px {accent_soft}; }}
.search-button {{
  color: {self.muted}; background-image: none; background-color: transparent;
  border: 1px solid transparent; border-radius: 6px; box-shadow: none; min-width: 26px; padding: 2px;
}}
.search-button:hover {{ color: {self.foreground}; background-color: {self.border}; }}

.panel {{ background-color: {self.surface}; border: 1px solid {self.border}; border-radius: 8px; margin-left: 6px; }}
.panel-inner {{ padding: 14px 10px 12px 10px; }}
.panel-title {{ color: {self.accent}; font-weight: 700; font-size: 10px; letter-spacing: 1px; }}
.panel-section {{ color: {self.muted}; font-weight: 600; font-size: 10px; letter-spacing: 1px; }}
.panel-hint {{ color: {self.muted}; font-size: 10px; }}
.action-button {{
  color: {self.foreground}; background-image: none; background-color: transparent;
  border: 1px solid transparent; border-radius: 6px; padding: 7px 9px;
  box-shadow: none; text-shadow: none; font-size: 12px;
}}
.action-button:hover {{ background-color: {self.background}; border-color: {self.border}; }}
.action-button:active {{ background-color: {accent_soft}; }}
.action-button:focus {{ border-color: {accent_soft}; }}
.action-button .action-dot {{ color: {self.accent}; font-family: monospace; }}
.action-button .action-warning {{ color: {self.danger}; font-size: 10px; }}
.panel-link {{ color: {self.accent}; }}
.panel.compact .panel-inner {{ padding: 10px 6px; }}
.panel.compact .action-button {{ padding: 5px 7px; font-size: 11px; }}
checkbutton {{ color: {self.foreground}; font-size: 11px; padding: 3px 2px; }}
checkbutton check {{
  background-image: none; background-color: {self.background}; border: 1px solid {self.border};
  border-radius: 4px; min-width: 14px; min-height: 14px; margin-right: 6px; -gtk-icon-shadow: none;
}}
checkbutton check:hover {{ border-color: {self.accent}; }}
checkbutton check:checked {{ background-color: {self.accent}; border-color: {self.accent}; color: {self.background}; }}

menu, .menu, .context-menu {{
  background-color: {self.surface}; color: {self.foreground}; border: 1px solid {self.border};
  border-radius: 6px; padding: 4px;
}}
menu menuitem {{ padding: 6px 12px; border-radius: 4px; }}
menu menuitem:hover {{ background-color: {accent_soft}; color: {self.foreground}; }}

dialog .dialog-vbox, dialog > box, dialog list, dialog scrolledwindow {{ background-color: {self.background}; color: {self.foreground}; }}
dialog notebook, dialog notebook > stack, dialog notebook > stack > box {{ background-color: {self.background}; }}
dialog notebook > header {{ background-color: {self.surface}; border-color: {self.border}; }}
dialog notebook > header tab {{ padding: 4px 12px; }}
scale trough {{ background-image: none; background-color: {self.border}; border: 0; min-height: 4px; border-radius: 3px; }}
scale highlight {{ background-image: none; background-color: {self.accent}; border: 0; border-radius: 3px; }}
scale slider {{ background-image: none; background-color: {self.foreground}; border: 1px solid {self.border}; box-shadow: none; }}
scale value {{ color: {self.muted}; }}
entry selection, selection {{ background-color: {accent_soft}; color: {self.foreground}; }}
dialog list row {{ border-radius: 6px; margin: 1px 4px; }}
dialog list row:selected {{ background-image: none; background-color: {accent_soft}; color: {self.foreground}; }}
dialog list row:hover {{ background-color: {self.surface}; }}
dialog button.suggested-action {{
  background-image: none; background-color: {self.accent}; color: {self.background};
  border-color: {self.accent}; box-shadow: none; text-shadow: none; font-weight: 700;
}}
dialog button.suggested-action:hover {{ background-color: {self.foreground}; border-color: {self.foreground}; }}
.dialog-heading {{ color: {self.accent}; font-weight: 700; font-size: 10px; letter-spacing: 1px; margin-top: 8px; }}
.palette-category {{
  color: {self.muted}; font-size: 10px; background-color: {self.surface};
  border: 1px solid {self.border}; border-radius: 9px; padding: 0 7px;
}}
switch {{ background-image: none; background-color: {self.border}; border: 1px solid {self.border}; border-radius: 12px; }}
switch:checked {{ background-color: {self.accent}; border-color: {self.accent}; }}
switch slider {{ background-image: none; background-color: {self.foreground}; border: 0; border-radius: 10px; box-shadow: none; }}

.boot {{ background-color: {terminal_background}; }}
dialog, messagedialog, filechooser {{ background-color: {self.background}; }}
.boot-card {{ padding: 24px; }}
.boot-logo {{ color: {self.accent}; font-family: monospace; font-weight: 700; font-size: 34px; letter-spacing: 6px; }}
.boot-subtitle {{ color: {self.muted}; font-family: monospace; font-size: 11px; letter-spacing: 3px; }}
.boot-status {{ color: {self.terminal_foreground}; font-family: monospace; font-size: 12px; }}
.boot progressbar trough {{ background-color: {self.surface}; border: 0; border-radius: 3px; min-height: 4px; }}
.boot progressbar progress {{ background-image: none; background-color: {self.accent}; border: 0; border-radius: 3px; min-height: 4px; }}
separator {{ background-color: {self.border}; min-width: 1px; min-height: 1px; }}
""".encode()


class ThemeManager:
    def __init__(self, user_directory: Path | None = None) -> None:
        self.builtin_directory = Path(__file__).with_name("themes")
        self.user_directory = user_directory or default_config_path().parent / "themes"
        self.themes: dict[str, Theme] = {}
        self.errors: list[str] = []
        self.reload()

    def reload(self) -> None:
        self.themes.clear()
        self.errors.clear()
        self._load_directory(self.builtin_directory, builtin=True)
        self._load_directory(self.user_directory, builtin=False)
        if DEFAULT_THEME not in self.themes:
            raise ThemeError(f"o tema interno {DEFAULT_THEME} não foi encontrado")

    def _load_directory(self, directory: Path, builtin: bool) -> None:
        if not directory.is_dir():
            return
        for path in sorted(directory.glob("*.ini")):
            try:
                theme = load_theme(path, builtin)
                self.themes[theme.identifier] = theme
            except ThemeError as error:
                self.errors.append(f"{path.name}: {error}")

    def get(self, identifier: str | None) -> Theme:
        return self.themes.get(identifier or "") or self.themes[DEFAULT_THEME]

    def all(self) -> list[Theme]:
        return sorted(self.themes.values(), key=lambda theme: (not theme.builtin, theme.name.casefold()))

    def import_theme(self, source: Path) -> Theme:
        candidate = load_theme(source, builtin=False)
        self.user_directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        destination = self.user_directory / f"{candidate.identifier}.ini"
        _atomic_copy(source, destination)
        self.reload()
        return self.themes[candidate.identifier]

    def is_custom(self, identifier: str) -> bool:
        theme = self.themes.get(identifier)
        return theme is not None and not theme.builtin

    def unique_identifier(self, name: str) -> str:
        base = slugify(name) or "tema"
        if not base[0].isalnum():
            base = f"tema-{base}"
        candidate = base
        counter = 2
        while candidate in self.themes:
            candidate = f"{base}-{counter}"[:48]
            counter += 1
        return candidate

    def save_custom(self, theme: Theme) -> Theme:
        """Validate and store a user theme, replacing one with the same id."""
        existing = self.themes.get(theme.identifier)
        if existing is not None and existing.builtin:
            raise ThemeError("temas internos não podem ser sobrescritos; salve uma cópia")
        destination = self.user_directory / f"{theme.identifier}.ini"
        text = theme_to_ini(theme)
        self.user_directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        descriptor, name = tempfile.mkstemp(prefix=f".{destination.name}.", dir=self.user_directory)
        temporary = Path(name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(text)
            load_theme(temporary)  # refuse to install anything the loader rejects
            temporary.chmod(0o600)
            temporary.replace(destination)
        except (OSError, ThemeError) as error:
            temporary.unlink(missing_ok=True)
            raise ThemeError(f"não foi possível salvar o tema: {error}") from error
        self.reload()
        return self.themes[theme.identifier]

    def delete_custom(self, identifier: str) -> None:
        theme = self.themes.get(identifier)
        if theme is None or theme.builtin or theme.path is None:
            raise ThemeError("somente temas personalizados podem ser removidos")
        try:
            theme.path.unlink()
        except OSError as error:
            raise ThemeError(f"não foi possível remover o tema: {error}") from error
        self.reload()

    def export_theme(self, identifier: str, destination: Path) -> None:
        theme = self.get(identifier)
        if theme.path is None:
            raise ThemeError("tema sem arquivo de origem")
        _atomic_copy(theme.path, destination)


def luminance(color: str) -> float:
    """WCAG relative luminance of a ``#rrggbb`` color."""
    channels = []
    for index in (1, 3, 5):
        value = int(color[index:index + 2], 16) / 255
        channels.append(value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4)
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


def contrast_ratio(first: str, second: str) -> float:
    """WCAG contrast ratio, from 1 (same color) to 21 (black on white)."""
    lighter, darker = sorted((luminance(first), luminance(second)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


def _rgba(color: str, alpha: float) -> str:
    if alpha >= 1.0:
        return color
    red, green, blue = (int(color[index:index + 2], 16) for index in (1, 3, 5))
    return f"rgba({red}, {green}, {blue}, {alpha:.2f})"


def _mix(color: str, base: str, amount: float) -> str:
    """Blend ``amount`` of ``color`` over ``base``; both are validated ``#rrggbb``."""
    first = [int(color[index:index + 2], 16) for index in (1, 3, 5)]
    second = [int(base[index:index + 2], 16) for index in (1, 3, 5)]
    return "#" + "".join(
        f"{round(top * amount + bottom * (1 - amount)):02x}" for top, bottom in zip(first, second)
    )


THEME_COLOR_FIELDS = (
    ("interface", "background", "background"),
    ("interface", "surface", "surface"),
    ("interface", "foreground", "foreground"),
    ("interface", "accent", "accent"),
    ("interface", "border", "border"),
    ("interface", "muted", "muted"),
    ("interface", "danger", "danger"),
    ("terminal", "background", "terminal_background"),
    ("terminal", "foreground", "terminal_foreground"),
    ("terminal", "cursor", "cursor"),
    ("terminal", "selection_background", "selection_background"),
    ("terminal", "selection_foreground", "selection_foreground"),
    ("effects", "matrix_color", "matrix_color"),
)


def theme_to_ini(theme: Theme) -> str:
    sections: dict[str, list[str]] = {"interface": [], "terminal": [], "effects": []}
    for section, key, attribute in THEME_COLOR_FIELDS:
        sections[section].append(f"{key} = {getattr(theme, attribute)}")
    sections["terminal"].append("ansi = " + ", ".join(theme.ansi))
    sections["effects"].append(f"scanline_opacity = {theme.scanline_opacity:g}")
    for key in CRT_EFFECTS:
        sections["effects"].append(f"{key} = {getattr(theme, key):g}")
    sections["effects"].append(f"rain = {str(theme.rain).lower()}")
    name = " ".join(theme.name.split())
    author = " ".join(theme.author.split()) or "Desconhecido"
    lines = ["[theme]", f"id = {theme.identifier}", f"name = {name}", f"author = {author}"]
    if theme.font:
        lines.append(f"font = {' '.join(theme.font.split())}")
    lines.append("")
    for section, values in sections.items():
        lines.append(f"[{section}]")
        lines.extend(values)
        lines.append("")
    return "\n".join(lines)


def _required(section: configparser.SectionProxy, key: str) -> str:
    value = section.get(key, "").strip()
    if not value:
        raise ThemeError(f"campo obrigatório ausente: {section.name}.{key}")
    return value


def _color(section: configparser.SectionProxy, key: str) -> str:
    value = _required(section, key)
    if not HEX_COLOR.fullmatch(value):
        raise ThemeError(f"cor inválida em {section.name}.{key}: {value}")
    return value.lower()


def load_theme(path: Path, builtin: bool = False) -> Theme:
    parser = configparser.ConfigParser(interpolation=None)
    try:
        with path.open(encoding="utf-8") as handle:
            parser.read_file(handle)
        metadata = parser["theme"]
        interface = parser["interface"]
        terminal = parser["terminal"]
        effects = parser["effects"]
    except (OSError, UnicodeError, configparser.Error, KeyError) as error:
        raise ThemeError(f"arquivo inválido: {error}") from error

    identifier = _required(metadata, "id")
    if not THEME_ID.fullmatch(identifier):
        raise ThemeError("id deve usar apenas letras minúsculas, números e hífens")
    name = _required(metadata, "name")
    author = metadata.get("author", "Desconhecido").strip() or "Desconhecido"
    ansi = tuple(item.strip().lower() for item in _required(terminal, "ansi").split(","))
    if len(ansi) != 16 or any(not HEX_COLOR.fullmatch(color) for color in ansi):
        raise ThemeError("terminal.ansi deve conter exatamente 16 cores hexadecimais")
    opacity = _fraction(effects, "scanline_opacity", required=True)
    crt = {key: _fraction(effects, key) for key in CRT_EFFECTS}
    rain_text = effects.get("rain", "true").strip().lower()
    if rain_text not in ("true", "false", "1", "0", "yes", "no", "on", "off"):
        raise ThemeError("effects.rain deve ser true ou false")
    font = " ".join(metadata.get("font", "").split()) or None

    return Theme(
        identifier, name, author,
        _color(interface, "background"), _color(interface, "surface"),
        _color(interface, "foreground"), _color(interface, "accent"),
        _color(interface, "border"), _color(interface, "muted"),
        _color(interface, "danger"), _color(terminal, "background"),
        _color(terminal, "foreground"), _color(terminal, "cursor"),
        _color(terminal, "selection_background"), _color(terminal, "selection_foreground"),
        _color(effects, "matrix_color"), opacity, ansi, path, builtin,
        rain=rain_text in ("true", "1", "yes", "on"), font=font, **crt,
    )


CRT_EFFECTS = ("glow", "vignette", "noise", "flicker", "curvature")


def _fraction(section: configparser.SectionProxy, key: str, required: bool = False) -> float:
    text = _required(section, key) if required else section.get(key, "0").strip() or "0"
    try:
        value = float(text)
    except ValueError as error:
        raise ThemeError(f"effects.{key} deve ser um número") from error
    if not 0.0 <= value <= 1.0:
        raise ThemeError(f"effects.{key} deve estar entre 0 e 1")
    return value


def _atomic_copy(source: Path, destination: Path) -> None:
    temporary: Path | None = None
    try:
        destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        descriptor, name = tempfile.mkstemp(prefix=f".{destination.name}.", dir=destination.parent)
        temporary = Path(name)
        with os.fdopen(descriptor, "wb") as output, source.open("rb") as input_file:
            output.write(input_file.read())
        temporary.chmod(0o600)
        temporary.replace(destination)
    except OSError as error:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        raise ThemeError(f"não foi possível copiar o tema: {error}") from error
