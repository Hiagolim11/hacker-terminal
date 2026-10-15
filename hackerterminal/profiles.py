"""Built-in and user-defined profiles and preference application."""

from __future__ import annotations

import configparser
import io
import logging
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from .config import (
    CURSOR_SHAPES,
    FALSE_VALUES,
    Preferences,
    atomic_write_text,
    clamp,
    default_config_path,
)

LOGGER = logging.getLogger(__name__)
PROFILE_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,47}$")
DEFAULT_PROFILE = "developer"


def slugify(text: str) -> str:
    """ASCII identifier from a display name: "Laboratório Ágil" -> "laboratorio-agil"."""
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", ascii_text.casefold()).strip("-")[:40]


class ProfileError(ValueError):
    """Raised when a profile cannot be parsed, saved or removed."""


@dataclass(frozen=True)
class Profile:
    identifier: str
    name: str
    description: str
    theme: str
    font_size: int
    boot: bool
    effects: bool
    sound: bool
    panel_visible: bool
    working_directory: str = "~"
    # Optional settings: None keeps whatever the user already has.
    font: str | None = None
    shell: str | None = None
    cursor_shape: str | None = None
    opacity: int | None = None
    own_actions: bool = False
    builtin: bool = False
    path: Path | None = None


PROFILES = (
    Profile(
        "developer",
        "Desenvolvimento",
        "Visual sóbrio, ações visíveis e sem distrações.",
        "minimal-dark",
        11,
        False,
        False,
        False,
        True,
        builtin=True,
    ),
    Profile(
        "focus",
        "Foco",
        "Terminal limpo em azul, sem painel lateral.",
        "ice-blue",
        12,
        False,
        False,
        False,
        False,
        builtin=True,
    ),
    Profile(
        "retro",
        "Retro Hacker",
        "Identidade visual completa com boot e efeitos.",
        "matrix-green",
        11,
        True,
        True,
        False,
        True,
        builtin=True,
    ),    Profile(
        "crt",
        "Retrô CRT",
        "Monitor de fósforo âmbar com brilho, curvatura e ruído, inspirado no Cool Retro Term.",
        "phosphor-amber",
        12,
        True,
        True,
        False,
        False,
        builtin=True,
    ),
)


def _boolean(value: str | None, fallback: bool) -> bool:
    if value is None or not value.strip():
        return fallback
    return value.strip().lower() not in FALSE_VALUES


def _optional(value: str | None) -> str | None:
    return value.strip() if value and value.strip() else None


def load_profile(path: Path) -> Profile:
    parser = configparser.ConfigParser(interpolation=None)
    try:
        with path.open(encoding="utf-8") as handle:
            parser.read_file(handle)
        section = parser["profile"]
    except (OSError, UnicodeError, configparser.Error, KeyError) as error:
        raise ProfileError(f"arquivo inválido: {error}") from error
    identifier = section.get("id", "").strip()
    if not PROFILE_ID.fullmatch(identifier):
        raise ProfileError("id deve usar apenas letras minúsculas, números e hífens")
    name = " ".join(section.get("name", "").split())
    if not name:
        raise ProfileError("campo obrigatório ausente: profile.name")
    try:
        font_size = clamp(int(section.get("font_size", "11")), 6, 32)
        opacity_text = _optional(section.get("opacity"))
        opacity = clamp(int(opacity_text), 30, 100) if opacity_text else None
    except ValueError as error:
        raise ProfileError(f"número inválido: {error}") from error
    cursor_shape = _optional(section.get("cursor_shape"))
    if cursor_shape is not None and cursor_shape not in CURSOR_SHAPES:
        raise ProfileError(f"formato de cursor inválido: {cursor_shape}")
    return Profile(
        identifier=identifier,
        name=name,
        description=" ".join(section.get("description", "").split()),
        theme=section.get("theme", "").strip() or "minimal-dark",
        font_size=font_size,
        boot=_boolean(section.get("boot"), False),
        effects=_boolean(section.get("effects"), False),
        sound=_boolean(section.get("sound"), False),
        panel_visible=_boolean(section.get("panel_visible"), True),
        working_directory=section.get("working_directory", "").strip() or "~",
        font=_optional(section.get("font")),
        shell=_optional(section.get("shell")),
        cursor_shape=cursor_shape,
        opacity=opacity,
        own_actions=_boolean(section.get("own_actions"), False),
        path=path,
    )


def profile_to_ini(profile: Profile) -> str:
    parser = configparser.ConfigParser(interpolation=None)
    values = {
        "id": profile.identifier,
        "name": " ".join(profile.name.split()),
        "description": " ".join(profile.description.split()),
        "theme": profile.theme,
        "font_size": str(profile.font_size),
        "boot": str(profile.boot).lower(),
        "effects": str(profile.effects).lower(),
        "sound": str(profile.sound).lower(),
        "panel_visible": str(profile.panel_visible).lower(),
        "working_directory": profile.working_directory,
        "font": profile.font or "",
        "shell": profile.shell or "",
        "cursor_shape": profile.cursor_shape or "",
        "opacity": "" if profile.opacity is None else str(profile.opacity),
        "own_actions": str(profile.own_actions).lower(),
    }
    parser["profile"] = values
    buffer = io.StringIO()
    parser.write(buffer)
    return buffer.getvalue()


def profile_from_preferences(
    identifier: str,
    name: str,
    description: str,
    preferences: Preferences,
    working_directory: str = "~",
    own_actions: bool = False,
) -> Profile:
    """Capture the current settings as a complete user profile."""
    return Profile(
        identifier=identifier,
        name=" ".join(name.split()),
        description=" ".join(description.split()),
        theme=preferences.theme,
        font_size=preferences.font_size,
        boot=preferences.boot,
        effects=preferences.effects,
        sound=preferences.sound,
        panel_visible=preferences.panel_visible,
        working_directory=working_directory or "~",
        font=preferences.font,
        shell=preferences.shell,
        cursor_shape=preferences.cursor_shape,
        opacity=preferences.opacity,
        own_actions=own_actions,
    )


class ProfileManager:
    def __init__(self, user_directory: Path | None = None) -> None:
        self.user_directory = user_directory or default_config_path().parent / "profiles"
        self.profiles: dict[str, Profile] = {}
        self.errors: list[str] = []
        self.reload()

    def reload(self) -> None:
        self.profiles = {profile.identifier: profile for profile in PROFILES}
        self.errors = []
        if not self.user_directory.is_dir():
            return
        for path in sorted(self.user_directory.glob("*.ini")):
            try:
                profile = load_profile(path)
            except ProfileError as error:
                self.errors.append(f"{path.name}: {error}")
                LOGGER.warning("perfil ignorado %s: %s", path, error)
                continue
            if profile.identifier in self.profiles and self.profiles[profile.identifier].builtin:
                self.errors.append(f"{path.name}: o id {profile.identifier} pertence a um perfil interno")
                continue
            self.profiles[profile.identifier] = profile

    def get(self, identifier: str | None) -> Profile:
        return self.profiles.get(identifier or "") or self.profiles[DEFAULT_PROFILE]

    def all(self) -> list[Profile]:
        builtin = [profile for profile in PROFILES]
        custom = sorted(
            (profile for profile in self.profiles.values() if not profile.builtin),
            key=lambda profile: profile.name.casefold(),
        )
        return builtin + custom

    def is_custom(self, identifier: str) -> bool:
        profile = self.profiles.get(identifier)
        return profile is not None and not profile.builtin

    def unique_identifier(self, name: str) -> str:
        base = slugify(name) or "perfil"
        candidate = base
        counter = 2
        while candidate in self.profiles:
            candidate = f"{base}-{counter}"[:48]
            counter += 1
        return candidate

    def actions_path(self, identifier: str) -> Path | None:
        """Where a profile keeps its own quick actions, if it has them."""
        profile = self.profiles.get(identifier)
        if profile is None or not profile.own_actions:
            return None
        return self.user_directory / f"{profile.identifier}.actions"

    def save_custom(self, profile: Profile) -> Profile:
        existing = self.profiles.get(profile.identifier)
        if existing is not None and existing.builtin:
            raise ProfileError("perfis internos não podem ser sobrescritos")
        if not PROFILE_ID.fullmatch(profile.identifier) or not profile.name.strip():
            raise ProfileError("perfil sem nome ou com identificador inválido")
        destination = self.user_directory / f"{profile.identifier}.ini"
        if not atomic_write_text(destination, profile_to_ini(profile), f".{destination.name}."):
            raise ProfileError(f"não foi possível gravar {destination}")
        self.reload()
        return self.profiles[profile.identifier]

    def delete_custom(self, identifier: str) -> None:
        profile = self.profiles.get(identifier)
        if profile is None or profile.builtin or profile.path is None:
            raise ProfileError("somente perfis personalizados podem ser removidos")
        try:
            profile.path.unlink()
            actions = self.user_directory / f"{identifier}.actions"
            actions.unlink(missing_ok=True)
        except OSError as error:
            raise ProfileError(f"não foi possível remover o perfil: {error}") from error
        self.reload()

    def apply(self, identifier: str, preferences: Preferences) -> Profile:
        profile = self.get(identifier)
        preferences.profile = profile.identifier
        preferences.theme = profile.theme
        preferences.font_size = profile.font_size
        preferences.boot = profile.boot
        preferences.effects = profile.effects
        preferences.sound = profile.sound
        preferences.panel_visible = profile.panel_visible
        if profile.font is not None or not profile.builtin:
            preferences.font = profile.font
        if profile.shell is not None or not profile.builtin:
            preferences.shell = profile.shell or ""
        if profile.cursor_shape is not None:
            preferences.cursor_shape = profile.cursor_shape
        if profile.opacity is not None:
            preferences.opacity = profile.opacity
        preferences.normalize()
        return profile

    def working_directory(self, identifier: str | None) -> Path:
        path = Path(self.get(identifier).working_directory).expanduser()
        try:
            resolved = path.resolve()
        except (OSError, RuntimeError):
            return Path.home()
        if not resolved.is_dir():
            LOGGER.warning("diretório do perfil inexistente: %s", path)
            return Path.home()
        return resolved
