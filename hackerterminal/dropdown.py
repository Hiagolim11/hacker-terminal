"""Quake-style drop-down terminal: geometry and the desktop's global shortcut.

`hacker-terminal --dropdown` runs as a unique application: the first call
creates the window, later calls reach it over D-Bus and toggle it. A global
key bound to that command (F12 by default, set up from Preferences on XFCE)
turns it into a drop-down terminal.
"""

from __future__ import annotations

import shlex
import shutil
import subprocess
import sys
from pathlib import Path

XFCONF_CHANNEL = "xfce4-keyboard-shortcuts"
DEFAULT_KEY = "F12"


def geometry(area: tuple[int, int, int, int], height_percent: int) -> tuple[int, int, int, int]:
    """Full width of the work area, `height_percent` of its height, at the top."""
    x, y, width, height = area
    percent = max(25, min(90, height_percent))
    return x, y, width, max(240, height * percent // 100)


def launch_command() -> str:
    """Command line that toggles the drop-down terminal from anywhere."""
    installed = shutil.which("hacker-terminal")
    if installed:
        return shlex.join([installed, "--dropdown"])
    script = Path(__file__).resolve().parent.parent / "hacker_terminal.py"
    return shlex.join([sys.executable, str(script), "--dropdown"])


def xfce_available() -> bool:
    return shutil.which("xfconf-query") is not None


def xfce_property(key: str) -> str:
    return f"/commands/custom/{key}"


def xfce_binding(key: str) -> str | None:
    """Command bound to `key` in XFCE, or None when the key is free."""
    try:
        result = subprocess.run(
            ["xfconf-query", "-c", XFCONF_CHANNEL, "-p", xfce_property(key)],
            capture_output=True, text=True, timeout=5, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def bind_xfce(key: str, command: str) -> tuple[bool, str]:
    """Bind `key` to `command`; refuses to replace another program's key."""
    current = xfce_binding(key)
    if current and "--dropdown" not in current:
        return False, f"{key} já está associado a: {current}"
    try:
        result = subprocess.run(
            ["xfconf-query", "-c", XFCONF_CHANNEL, "-p", xfce_property(key), "-n", "-t", "string", "-s", command],
            capture_output=True, text=True, timeout=5, check=False,
        )
    except (OSError, subprocess.SubprocessError) as error:
        return False, str(error)
    if result.returncode != 0:
        return False, result.stderr.strip() or "xfconf-query falhou"
    return True, f"{key} agora abre e esconde o terminal suspenso."
