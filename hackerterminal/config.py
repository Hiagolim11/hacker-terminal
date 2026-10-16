"""Persistent preferences and per-window runtime configuration."""

from __future__ import annotations

import configparser
import io
import logging
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from .constants import APP_NAME, DEFAULT_FONT_SIZE, DEFAULT_SCROLLBACK, DEFAULT_THEME

LOGGER = logging.getLogger(__name__)

CURSOR_SHAPES = ("block", "ibeam", "underline")
CURSOR_BLINK_MODES = ("system", "on", "off")
FALSE_VALUES = {"0", "false", "no", "off"}


def clamp(value: int, minimum: int, maximum: int) -> int:
    return max(minimum, min(maximum, value))


def config_home() -> Path:
    configured = os.environ.get("XDG_CONFIG_HOME")
    return Path(configured).expanduser() if configured else Path.home() / ".config"


def state_home() -> Path:
    configured = os.environ.get("XDG_STATE_HOME")
    return Path(configured).expanduser() if configured else Path.home() / ".local" / "state"


def default_config_path() -> Path:
    return config_home() / APP_NAME / "config.ini"


def atomic_write_text(path: Path, text: str, prefix: str) -> bool:
    """Write ``text`` with mode 0600 through a same-directory rename."""
    temporary: Path | None = None
    try:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        descriptor, name = tempfile.mkstemp(prefix=prefix, dir=path.parent, text=True)
        temporary = Path(name)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.chmod(0o600)
        temporary.replace(path)
        return True
    except OSError as error:
        LOGGER.warning("não foi possível gravar %s: %s", path, error)
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        return False


@dataclass
class Preferences:
    profile: str = "developer"
    theme: str = DEFAULT_THEME
    font: str | None = None
    font_size: int = DEFAULT_FONT_SIZE
    boot: bool = False
    effects: bool = False
    sound: bool = False
    scrollback_lines: int = DEFAULT_SCROLLBACK
    panel_visible: bool = True
    restore_session: bool = True
    cursor_shape: str = "block"
    cursor_blink: str = "system"
    opacity: int = 100
    bold_is_bright: bool = False
    copy_on_select: bool = False
    scroll_on_output: bool = False
    scroll_on_keystroke: bool = True
    confirm_paste: bool = True
    bell_notify: bool = True
    shell: str = ""
    shell_integration: bool = True
    command_marks: bool = True
    notify_commands: bool = True
    notify_after: int = 10
    key_switch: str = "brown"
    key_volume: int = 70
    key_release: bool = True
    shortcuts: dict[str, str] = field(default_factory=dict)

    def normalize(self) -> None:
        self.profile = self.profile.strip() if self.profile and self.profile.strip() else "developer"
        self.theme = self.theme.strip() if self.theme and self.theme.strip() else DEFAULT_THEME
        self.font = self.font.strip() if self.font and self.font.strip() else None
        self.font_size = clamp(int(self.font_size), 6, 32)
        self.scrollback_lines = clamp(int(self.scrollback_lines), 1_000, 200_000)
        self.cursor_shape = self.cursor_shape if self.cursor_shape in CURSOR_SHAPES else "block"
        self.cursor_blink = self.cursor_blink if self.cursor_blink in CURSOR_BLINK_MODES else "system"
        self.opacity = clamp(int(self.opacity), 30, 100)
        self.shell = (self.shell or "").strip()
        switch = (self.key_switch or "").strip()
        valid_pack = switch.startswith("pack:") and len(switch) > 5 and "/" not in switch[5:]
        self.key_switch = switch if switch in ("red", "brown", "blue") or valid_pack else "brown"
        self.key_volume = clamp(int(self.key_volume), 0, 100)
        self.notify_after = clamp(int(self.notify_after), 3, 3600)
        self.shortcuts = {
            str(key).strip(): str(value).strip()
            for key, value in (self.shortcuts or {}).items()
            if str(key).strip()
        }


@dataclass(frozen=True)
class AppConfig:
    preferences: Preferences
    command: tuple[str, ...] = ()
    working_directory: Path = Path.home()


class ConfigStore:
    # Interpolation is disabled so values such as font names or shell commands
    # may contain "%" without corrupting the whole file.
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or default_config_path()

    def _read(self) -> configparser.ConfigParser:
        parser = configparser.ConfigParser(interpolation=None)
        parser.optionxform = str  # keep shortcut identifiers verbatim
        parser.read(self.path, encoding="utf-8")
        return parser

    def load(self) -> Preferences:
        try:
            parser = self._read()
            section = parser["terminal"] if parser.has_section("terminal") else {}
            shortcuts = dict(parser["shortcuts"]) if parser.has_section("shortcuts") else {}
            preferences = Preferences(
                profile=section.get("profile", "developer"),
                theme=section.get("theme", DEFAULT_THEME),
                font=section.get("font") or None,
                font_size=self._integer(section, "font_size", DEFAULT_FONT_SIZE),
                boot=self._boolean(section, "boot", False),
                effects=self._boolean(section, "effects", False),
                sound=self._boolean(section, "sound", False),
                scrollback_lines=self._integer(section, "scrollback_lines", DEFAULT_SCROLLBACK),
                panel_visible=self._boolean(section, "panel_visible", True),
                restore_session=self._boolean(section, "restore_session", True),
                cursor_shape=section.get("cursor_shape", "block"),
                cursor_blink=section.get("cursor_blink", "system"),
                opacity=self._integer(section, "opacity", 100),
                bold_is_bright=self._boolean(section, "bold_is_bright", False),
                copy_on_select=self._boolean(section, "copy_on_select", False),
                scroll_on_output=self._boolean(section, "scroll_on_output", False),
                scroll_on_keystroke=self._boolean(section, "scroll_on_keystroke", True),
                confirm_paste=self._boolean(section, "confirm_paste", True),
                bell_notify=self._boolean(section, "bell_notify", True),
                shell=section.get("shell", ""),
                shell_integration=self._boolean(section, "shell_integration", True),
                command_marks=self._boolean(section, "command_marks", True),
                notify_commands=self._boolean(section, "notify_commands", True),
                notify_after=self._integer(section, "notify_after", 10),
                key_switch=section.get("key_switch", "brown"),
                key_volume=self._integer(section, "key_volume", 70),
                key_release=self._boolean(section, "key_release", True),
                shortcuts=shortcuts,
            )
        except (OSError, configparser.Error, ValueError, UnicodeError) as error:
            LOGGER.warning("configuração inválida em %s; usando padrões: %s", self.path, error)
            preferences = Preferences()
        preferences.normalize()
        return preferences

    def save(self, preferences: Preferences) -> bool:
        preferences.normalize()
        try:
            parser = self._read()
        except (OSError, configparser.Error, UnicodeError):
            # A broken file is replaced, but unrelated valid sections are kept
            # whenever the file can still be parsed.
            parser = configparser.ConfigParser(interpolation=None)
            parser.optionxform = str
        parser["terminal"] = {
            "profile": preferences.profile,
            "theme": preferences.theme,
            "font": preferences.font or "",
            "font_size": str(preferences.font_size),
            "boot": str(preferences.boot).lower(),
            "effects": str(preferences.effects).lower(),
            "sound": str(preferences.sound).lower(),
            "scrollback_lines": str(preferences.scrollback_lines),
            "panel_visible": str(preferences.panel_visible).lower(),
            "restore_session": str(preferences.restore_session).lower(),
            "cursor_shape": preferences.cursor_shape,
            "cursor_blink": preferences.cursor_blink,
            "opacity": str(preferences.opacity),
            "bold_is_bright": str(preferences.bold_is_bright).lower(),
            "copy_on_select": str(preferences.copy_on_select).lower(),
            "scroll_on_output": str(preferences.scroll_on_output).lower(),
            "scroll_on_keystroke": str(preferences.scroll_on_keystroke).lower(),
            "confirm_paste": str(preferences.confirm_paste).lower(),
            "bell_notify": str(preferences.bell_notify).lower(),
            "shell": preferences.shell,
            "shell_integration": str(preferences.shell_integration).lower(),
            "command_marks": str(preferences.command_marks).lower(),
            "notify_commands": str(preferences.notify_commands).lower(),
            "notify_after": str(preferences.notify_after),
            "key_switch": preferences.key_switch,
            "key_volume": str(preferences.key_volume),
            "key_release": str(preferences.key_release).lower(),
        }
        if parser.has_section("shortcuts"):
            parser.remove_section("shortcuts")
        if preferences.shortcuts:
            parser["shortcuts"] = dict(sorted(preferences.shortcuts.items()))
        buffer = io.StringIO()
        parser.write(buffer)
        return atomic_write_text(self.path, buffer.getvalue(), ".config.")

    @staticmethod
    def _integer(section, key: str, fallback: int) -> int:
        try:
            return int(section.get(key, fallback))
        except (TypeError, ValueError):
            return fallback

    @staticmethod
    def _boolean(section, key: str, fallback: bool) -> bool:
        value = section.get(key)
        if value is None:
            return fallback
        return str(value).strip().lower() not in FALSE_VALUES


def env_enabled(name: str, default: bool = True) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() not in FALSE_VALUES
