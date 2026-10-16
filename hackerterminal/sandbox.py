"""Running inside a Flatpak sandbox.

The terminal must run the user's real shell, so it starts it on the host
with ``flatpak-spawn --host``. Files the host shell needs (integration
scripts, ht-open) are copied to the app's data directory, which is a real
host path (~/.var/app/<id>/data). Nothing here runs outside Flatpak.
"""

from __future__ import annotations

import functools
import logging
import os
import shutil
import subprocess
from pathlib import Path

from .constants import APP_ID

LOGGER = logging.getLogger(__name__)
IN_FLATPAK = Path("/.flatpak-info").is_file()


def host_command(argv: list[str], directory: Path, environment: dict[str, str]) -> list[str]:
    """Wrap ``argv`` to run on the host in ``directory`` with ``environment`` added."""
    wrapped = ["flatpak-spawn", "--host", "--watch-bus", f"--directory={directory}"]
    wrapped += [f"--env={key}={value}" for key, value in sorted(environment.items())]
    return [*wrapped, "--", *argv]


@functools.lru_cache(maxsize=1)
def host_shell() -> str:
    """The user's login shell on the host (the sandbox's /etc/passwd is not it)."""
    try:
        result = subprocess.run(
            ["flatpak-spawn", "--host", "sh", "-c", 'getent passwd "$(id -un)" | cut -d: -f7'],
            capture_output=True, text=True, timeout=5, check=False,
        )
        shell = result.stdout.strip()
        if result.returncode == 0 and shell.startswith("/"):
            return shell
    except (OSError, subprocess.SubprocessError) as error:
        LOGGER.warning("não foi possível consultar o shell do sistema: %s", error)
    return "/bin/bash"


def host_runtime_directory() -> Path | None:
    """$XDG_RUNTIME_DIR/app/<id>: shared with the host at the same path."""
    base = os.environ.get("XDG_RUNTIME_DIR")
    if not base:
        return None
    directory = Path(base) / "app" / APP_ID
    return directory if directory.is_dir() else None


def export_to_host(source: Path, name: str) -> Path | None:
    """Copy a file or directory tree to a host-visible place and return it."""
    base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "hacker-terminal" / "host"
    target = base / name
    try:
        if source.is_dir():
            shutil.copytree(source, target, dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__"))
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
    except OSError as error:
        LOGGER.warning("não foi possível preparar %s para o sistema: %s", name, error)
        return None
    return target
