#!/usr/bin/env python3
"""Build docs/index.html (the GitHub Pages site) from packaging/site/index.template.html.

The version, the theme colours, the profiles and the quick actions come from
the app itself, so the page (and its interactive demo) never drifts from the
release it advertises. Run it before each release.
"""

from __future__ import annotations

import hashlib
import html
import json
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from hackerterminal.actions import DEFAULT_ACTIONS, fields  # noqa: E402
from hackerterminal.constants import DEFAULT_THEME, VERSION  # noqa: E402
from hackerterminal.profiles import PROFILES  # noqa: E402
from hackerterminal.themes import ThemeManager  # noqa: E402

FAVOURITES = ("zero-day", "phosphor-amber", "neon-noir", "aurora", "graphite", "paper-light")
SITE = ROOT / "packaging" / "site"
DOCS = ROOT / "docs"
# Small full-travel recordings (about 60 KB each) the demo plays as you type.
DEMO_SOUNDPACKS = ("holy-pandas", "mxblue-travel", "turquoise", "cream-travel")
# Mechvibes key codes for the keys with their own sound.
SPECIAL_KEYS = {"14": "Backspace", "28": "Enter", "57": "Space"}


def theme_data(theme) -> dict:
    return {
        "id": theme.identifier,
        "name": theme.name,
        "author": theme.author,
        "dark": theme.dark,
        "font": theme.font,
        "ui": {key: getattr(theme, key) for key in ("background", "surface", "foreground", "accent", "border", "muted", "danger")},
        "term": {
            "background": theme.terminal_background,
            "foreground": theme.terminal_foreground,
            "cursor": theme.cursor,
            "selection_background": theme.selection_background,
            "selection_foreground": theme.selection_foreground,
        },
        "ansi": list(theme.ansi),
        "fx": {
            "matrix": theme.matrix_color,
            "scanlines": theme.scanline_opacity,
            "glow": theme.glow,
            "vignette": theme.vignette,
            "noise": theme.noise,
            "flicker": theme.flicker,
            "curvature": theme.curvature,
            "rain": theme.rain,
        },
    }


def expand(pattern: str) -> list[str]:
    """``GENERIC_R{0-4}.mp3`` -> the five file names, as Mechvibes reads them."""
    match = re.search(r"\{(\d+)-(\d+)\}", pattern)
    if not match:
        return [pattern]
    first, last = int(match.group(1)), int(match.group(2))
    return [pattern[: match.start()] + str(n) + pattern[match.end():] for n in range(first, last + 1)]


def copy_soundpacks() -> list[dict]:
    """Copy the demo's packs to docs/audio/keys/ and describe them for the page."""
    target_root = DOCS / "audio" / "keys"
    shutil.rmtree(target_root, ignore_errors=True)
    packs = []
    for identifier in DEMO_SOUNDPACKS:
        source = ROOT / "hackerterminal" / "soundpacks" / identifier
        config = json.loads((source / "config.json").read_text(encoding="utf-8"))
        # Like the app, a sound the pack names but does not ship falls back to the generic one.
        def present(name: str | None) -> str | None:
            return name if name and (source / name).is_file() else None

        defines = config.get("defines", {})
        keys = {
            name: {"press": present(defines.get(code)), "release": present(defines.get(f"{code}-up"))}
            for code, name in SPECIAL_KEYS.items()
        }
        keys = {name: key for name, key in keys.items() if key["press"] or key["release"]}
        pack = {
            "id": identifier,
            "name": config["name"],
            "base": f"audio/keys/{identifier}/",
            "press": [name for name in expand(config["sound"]) if present(name)],
            "release": present(config.get("soundup")),
            "keys": keys,
        }
        wanted = set(pack["press"]) | {pack["release"]} | {f for key in keys.values() for f in key.values()}
        for name in sorted(f for f in wanted if f):
            destination = target_root / identifier / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source / name, destination)
        packs.append(pack)
    return packs


def demo_data(themes: ThemeManager) -> str:
    data = {
        "version": VERSION,
        "default_theme": DEFAULT_THEME,
        "themes": [theme_data(theme) for theme in sorted(themes.all(), key=lambda t: t.name.casefold())],
        "profiles": [
            {
                "id": profile.identifier,
                "name": profile.name,
                "description": profile.description,
                "theme": profile.theme,
                "font_size": profile.font_size,
                "effects": profile.effects,
                "sound": profile.sound,
                "panel": profile.panel_visible,
            }
            for profile in PROFILES
        ],
        "actions": [
            {
                "id": action.identifier,
                "label": action.label,
                "command": action.command,
                "fields": [{"name": field.name, "default": field.default} for field in fields(action.command)],
                "in_terminal": action.in_terminal,
            }
            for action in DEFAULT_ACTIONS
        ],
        "soundpacks": copy_soundpacks(),
    }
    # Safe inside <script type="application/json">: no "</script>" can close it early.
    return json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")


def main() -> int:
    themes = ThemeManager(Path("/nonexistent"))  # built-in themes only
    swatches = []
    for identifier in FAVOURITES:
        theme = themes.get(identifier)
        dots = "".join(f'<i style="background:{color}"></i>' for color in theme.ansi[1:7])
        swatches.append(
            '<div class="theme-tile reveal" data-ui>'
            f'<div class="face" style="background:{theme.terminal_background};color:{theme.terminal_foreground}">'
            f'<span class="l1"><i style="color:{theme.accent}">hacker@lab</i> ~ $ ls</span>'
            f'<span class="l2">bin   docs   scan.sh</span>'
            f'<span class="pal" aria-hidden="true">{dots}</span></div>'
            f'<div class="strip"><b>{html.escape(theme.name)}</b><span>{html.escape(theme.identifier)}</span></div>'
            "</div>"
        )
    names = sorted((theme.name for theme in themes.all()), key=str.casefold)
    page = (SITE / "index.template.html").read_text(encoding="utf-8")
    page = page.replace("__SWATCHES__", "".join(swatches))
    page = page.replace("__THEME_LIST__", "".join(f"<span>{html.escape(name)}</span>" for name in names))
    page = page.replace("__VERSION__", VERSION)
    page = page.replace("__DEMO_DATA__", demo_data(themes))
    assert "__" not in page.split("<script>")[0].replace("___", ""), "unfilled placeholder"
    # Cache-busting: reference demo.css/demo.js with a short content hash, so a
    # changed file gets a new URL and browsers never serve a stale demo.
    for name in ("demo.css", "demo.js"):
        data = (SITE / name).read_bytes()
        (DOCS / name).write_bytes(data)
        digest = hashlib.sha1(data).hexdigest()[:8]
        marker = f'"{name}"'
        assert page.count(marker) == 1, f"esperava uma referência a {name}"
        page = page.replace(marker, f'"{name}?v={digest}"')
    (DOCS / "index.html").write_text(page, encoding="utf-8")
    (DOCS / ".nojekyll").touch()  # serve the files as they are
    print(f"docs/index.html: versão {VERSION}, {len(names)} temas, demonstração interativa")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
