"""Safe restoration of window geometry and terminal working directories."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .config import atomic_write_text, clamp, default_config_path
from .storage import exclusive_lock

LOGGER = logging.getLogger(__name__)


MAX_PANES_PER_TAB = 4
MAX_PANES = 20

MAX_NAME = 40

# A layout is a leaf index or ["horizontal"|"vertical", first, second] with
# an optional fourth item: the first child's share of the split (0.05–0.95).
Layout = int | list


def clean_name(value) -> str:
    """A pane name: printable, single spaced, at most MAX_NAME characters."""
    if not isinstance(value, str):
        return ""
    text = "".join(char if char.isprintable() else " " for char in value)
    return " ".join(text.split())[:MAX_NAME]


def valid_ratio(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and 0.05 <= value <= 0.95


@dataclass(frozen=True)
class SessionTab:
    directories: tuple[Path, ...]
    orientation: str | None = None
    layout: Layout | None = None
    names: tuple[str, ...] = ()

    def name(self, index: int) -> str:
        return self.names[index] if index < len(self.names) else ""

    def tree(self) -> Layout:
        """The split tree, deriving it from the v2 fields when needed."""
        if self.layout is not None:
            return self.layout
        if len(self.directories) == 2 and self.orientation:
            return [self.orientation, 0, 1]
        return 0


def valid_layout(layout, count: int) -> bool:
    """True when the tree uses each of the ``count`` leaves exactly once."""
    seen: list[int] = []

    def walk(node, depth: int) -> bool:
        if depth > MAX_PANES_PER_TAB:
            return False
        if isinstance(node, bool):
            return False
        if isinstance(node, int):
            seen.append(node)
            return True
        return (
            isinstance(node, list)
            and len(node) in (3, 4)
            and node[0] in ("horizontal", "vertical")
            and (len(node) == 3 or valid_ratio(node[3]))
            and walk(node[1], depth + 1)
            and walk(node[2], depth + 1)
        )

    return walk(layout, 0) and sorted(seen) == list(range(count))


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
            if version not in (1, 2, 3):
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
                    if not isinstance(item, dict) or total >= MAX_PANES:
                        continue
                    raw = [value for value in item.get("directories", []) if isinstance(value, str)]
                    raw = raw[: min(MAX_PANES_PER_TAB, MAX_PANES - total)]
                    directories = tuple(Path(value).expanduser() for value in raw)
                    raw_names = item.get("names")
                    names = tuple(clean_name(value) for value in raw_names[: len(directories)]) if isinstance(raw_names, list) else ()
                    if not directories or not all(path.is_dir() for path in directories):
                        # A missing folder breaks the layout: keep what still exists, unsplit.
                        kept = [(path, names[index] if index < len(names) else "")
                                for index, path in enumerate(directories) if path.is_dir()][:1]
                        if not kept:
                            continue
                        tabs_list.append(SessionTab((kept[0][0],), names=(kept[0][1],)))
                        total += 1
                        continue
                    layout = item.get("layout")
                    orientation = item.get("orientation")
                    if layout is not None and not valid_layout(layout, len(directories)):
                        layout = None
                    if orientation not in ("horizontal", "vertical") or len(directories) != 2:
                        orientation = None
                    if layout is None and orientation is None:
                        directories, names = directories[:1], names[:1]
                    tabs_list.append(SessionTab(directories, orientation, layout, names))
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
        remaining = MAX_PANES
        for tab in state.tabs:
            if remaining <= 0:
                break
            if len(tab.directories) > min(MAX_PANES_PER_TAB, remaining) or not all(
                path.is_dir() for path in tab.directories
            ):
                # Too many panes or a vanished folder: keep the first one only.
                directories = [str(path) for path in tab.directories[:1] if path.is_dir()]
                layout = 0
            else:
                directories = [str(path) for path in tab.directories]
                layout = tab.tree()
            if not directories:
                continue
            if not valid_layout(layout, len(directories)):
                directories, layout = directories[:1], 0
            orientation = layout[0] if isinstance(layout, list) and len(directories) == 2 else None
            entry = {"directories": directories, "orientation": orientation, "layout": layout}
            names = [clean_name(tab.name(index)) for index in range(len(directories))]
            if any(names):
                entry["names"] = names
            tabs.append(entry)
            remaining -= len(directories)
        payload = {
            "version": 3,
            "width": clamp(state.width, 720, 4000),
            "height": clamp(state.height, 440, 2160),
            "active_tab": max(0, state.active_tab),
            "tabs": tabs,
        }
        return atomic_write_text(self.path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n", ".session.")

    def clear(self) -> None:
        try:
            self.path.unlink(missing_ok=True)
        except OSError:
            pass


class SessionCoordinator:
    """One writer per session file; combine normal windows in opening order.

    Version 3 remains readable: the saved tabs reopen in a single window.
    Concurrent separate processes do not overwrite the owning process's
    session. Drop-down windows use a different store and therefore lock.
    """

    def __init__(self, store: SessionStore) -> None:
        self.store = store
        self.windows: dict[object, Callable[[], SessionState | None]] = {}
        self._lock = None
        self._attempted = False

    def register(self, key: object, snapshot: Callable[[], SessionState | None]) -> bool:
        if not self._attempted:
            self._attempted = True
            try:
                self._lock = exclusive_lock(self.store.path.with_suffix(self.store.path.suffix + ".lock"), blocking=False)
            except BlockingIOError:
                LOGGER.info("sessão já gerenciada por outro processo: %s", self.store.path)
            except OSError as error:
                LOGGER.warning("não foi possível reservar a sessão %s: %s", self.store.path, error)
        if self._lock is None:
            return False
        self.windows[key] = snapshot
        return True

    def save(self) -> bool:
        if self._lock is None:
            return False
        states = [state for snapshot in self.windows.values() if (state := snapshot()) is not None]
        if not states:
            self.store.clear()
            return True
        first = states[0]
        tabs = tuple(tab for state in states for tab in state.tabs)
        return self.store.save(SessionState(first.width, first.height, first.active_tab, tabs))

    def remove(self, key: object, *, save: bool = False) -> None:
        if key in self.windows:
            del self.windows[key]
            if save:
                self.save()

    def close(self) -> None:
        self.windows.clear()
        if self._lock is not None:
            self._lock.close()
            self._lock = None
