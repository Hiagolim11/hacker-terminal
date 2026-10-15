"""Font discovery with verified Powerline and Nerd Font coverage."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from .constants import DEFAULT_FONT_SIZE, NERD_GLYPHS, POWERLINE_GLYPHS, PREFERRED_FONTS
from .runtime import Pango, PangoCairo


@dataclass(frozen=True)
class FontChoice:
    family: str
    has_powerline: bool
    has_nerd_symbols: bool


def installed_font_families() -> dict[str, str]:
    font_map = PangoCairo.FontMap.get_default()
    return {family.get_name().casefold(): family.get_name() for family in font_map.list_families()}


def font_has_glyphs(family: str, codepoints: tuple[int, ...]) -> bool:
    font_map = PangoCairo.FontMap.get_default()
    context = font_map.create_context()
    font = font_map.load_font(context, Pango.FontDescription(f"{family} {DEFAULT_FONT_SIZE}"))
    if font is None or font.describe().get_family().casefold() != family.casefold():
        return False
    coverage = font.get_coverage(Pango.Language.get_default())
    return all(coverage.get(codepoint) != Pango.CoverageLevel.NONE for codepoint in codepoints)


@lru_cache(maxsize=32)
def choose_font(requested: str | None = None) -> FontChoice:
    families = installed_font_families()
    patched_fonts = sorted(
        name
        for name in families.values()
        if any(marker in name.casefold() for marker in ("nerd font", " powerline", " nf"))
    )
    ordered = ([requested] if requested else []) + list(PREFERRED_FONTS[:9]) + patched_fonts + list(PREFERRED_FONTS[9:])
    seen: set[str] = set()
    first_powerline: FontChoice | None = None
    first_available: FontChoice | None = None
    for candidate in ordered:
        if not candidate:
            continue
        actual = families.get(candidate.casefold())
        if actual is None or actual.casefold() in seen:
            continue
        seen.add(actual.casefold())
        choice = FontChoice(
            actual,
            font_has_glyphs(actual, POWERLINE_GLYPHS),
            font_has_glyphs(actual, NERD_GLYPHS),
        )
        if requested and actual.casefold() == requested.casefold():
            return choice
        first_available = first_available or choice
        if choice.has_powerline and choice.has_nerd_symbols:
            return choice
        if choice.has_powerline and first_powerline is None:
            first_powerline = choice
    return first_powerline or first_available or FontChoice("Monospace", False, False)
