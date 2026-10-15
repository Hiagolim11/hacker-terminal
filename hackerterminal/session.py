"""Safe restoration of window geometry and terminal working directories."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .config import clamp, default_config_path


@dataclass(frozen=True)
class SessionTab:
    directories: tuple[Path, ...]
    orientation: str | None = None


@dataclass(frozen=True)
class SessionState:
    width: int
    height: int
    active_tab: int
    tabs: tuple[SessionTab, ...]

    @property
    def directories(self) -> tuple[Path, ...]:
        return tuple(directory for tab in self.tabs for directory in tab.directories)


class SessionStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or default_config_path().with_name("session.json")

    def load(self) -> SessionState | None:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            version = payload.get("version")
            if version not in (1, 2):
                return None
            if version == 1:
                tabs = tuple(
                    SessionTab((path,))
                    for value in payload.get("directories", [])[:20]
                    if isinstance(value, str) and (path := Path(value).expanduser()).is_dir()
                )
            else:
                tabs_list: list[SessionTab] = []
                total = 0
                for item in payload.get("tabs", []):
                    if not isinstance(item, dict) or total >= 20:
                        continue
                    remaining = 20 - total
                    directories = tuple(
                        path
                        for value in item.get("directories", [])[: min(2, remaining)]
                        if isinstance(value, str) and (path := Path(value).expanduser()).is_dir()
                    )
                    if not directories:
                        continue
                    orientation = item.get("orientation")
                    if orientation not in ("horizontal", "vertical") or len(directories) < 2:
                        orientation = None
                    tabs_list.append(SessionTab(directories, orientation))
                    total += len(directories)
                tabs = tuple(tabs_list)
            if not tabs:
                return None
            width = clamp(int(payload.get("width", 1180)), 720, 4000)
            height = clamp(int(payload.get("height", 720)), 440, 2160)
            active = clamp(int(payload.get("active_tab", 0)), 0, len(tabs) - 1)
            return SessionState(width, height, active, tabs)
        except (OSError, ValueError, TypeError, AttributeError, json.JSONDecodeError):
            return None

    def save(self, state: SessionState) -> bool:
        tabs: list[dict[str, object]] = []
        remaining = 20
        for tab in state.tabs:
            if remaining <= 0:
                break
            directories = [str(path) for path in tab.directories[: min(2, remaining)] if path.is_dir()]
            if not directories:
                continue
            orientation = (
                tab.orientation
                if tab.orientation in ("horizontal", "vertical") and len(directories) == 2
                else None
            )
            tabs.append({"directories": directories, "orientation": orientation})
            remaining -= len(directories)
        payload = {
            "version": 2,
            "width": clamp(state.width, 720, 4000),
            "height": clamp(state.height, 440, 2160),
            "active_tab": max(0, state.active_tab),
            "tabs": tabs,
        }
        temporary: Path | None = None
        try:
            self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            descriptor, name = tempfile.mkstemp(prefix=".session.", dir=self.path.parent, text=True)
            temporary = Path(name)
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
            temporary.chmod(0o600)
            temporary.replace(self.path)
            return True
        except OSError:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
            return False

    def clear(self) -> None:
        try:
            self.path.unlink(missing_ok=True)
        except OSError:
            pass
