#!/usr/bin/env python3
"""Build docs/index.html (the GitHub Pages site) from packaging/site/index.template.html.

The version and the theme colours come from the app itself, so the page
never drifts from the release it advertises. Run it before each release.
"""

from __future__ import annotations

import html
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from hackerterminal.constants import VERSION  # noqa: E402
from hackerterminal.themes import ThemeManager  # noqa: E402

FAVOURITES = ("zero-day", "phosphor-amber", "neon-noir", "aurora", "graphite", "paper-light")


def main() -> int:
    themes = ThemeManager(Path("/nonexistent"))  # built-in themes only
    swatches = []
    for identifier in FAVOURITES:
        theme = themes.get(identifier)
        dots = "".join(f'<i style="background:{color}"></i>' for color in theme.ansi[1:7])
        swatches.append(
            f'<div class="swatch" style="background:{theme.terminal_background};color:{theme.terminal_foreground}">'
            f"<span>{html.escape(theme.name)}</span><span class=\"dots\" aria-hidden=\"true\">{dots}</span></div>"
        )
    names = sorted((theme.name for theme in themes.all()), key=str.casefold)
    page = (ROOT / "packaging" / "site" / "index.template.html").read_text(encoding="utf-8")
    page = page.replace("__SWATCHES__", "".join(swatches))
    page = page.replace("__THEME_LIST__", "".join(f"<span>{html.escape(name)}</span>" for name in names))
    page = page.replace("__VERSION__", VERSION)
    assert "__" not in page.split("<script>")[0].replace("___", ""), "unfilled placeholder"
    (ROOT / "docs" / "index.html").write_text(page, encoding="utf-8")
    (ROOT / "docs" / ".nojekyll").touch()  # serve the files as they are
    print(f"docs/index.html: versão {VERSION}, {len(names)} temas")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
