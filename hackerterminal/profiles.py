"""Built-in development profiles and preference application."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .config import Preferences


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
    ),
)


class ProfileManager:
    def __init__(self) -> None:
        self.profiles = {profile.identifier: profile for profile in PROFILES}

    def get(self, identifier: str | None) -> Profile:
        return self.profiles.get(identifier or "") or self.profiles["developer"]

    def all(self) -> list[Profile]:
        return list(PROFILES)

    def apply(self, identifier: str, preferences: Preferences) -> Profile:
        profile = self.get(identifier)
        preferences.profile = profile.identifier
        preferences.theme = profile.theme
        preferences.font_size = profile.font_size
        preferences.boot = profile.boot
        preferences.effects = profile.effects
        preferences.sound = profile.sound
        preferences.panel_visible = profile.panel_visible
        preferences.normalize()
        return profile

    def working_directory(self, identifier: str | None) -> Path:
        return Path(self.get(identifier).working_directory).expanduser().resolve()
