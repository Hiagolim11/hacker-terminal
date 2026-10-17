"""Command history across tabs, windows and sessions, from the shell hooks.

One JSON object per line in $XDG_STATE_HOME/hacker-terminal/history.jsonl
(mode 0600), newest last, trimmed to the most recent MAX_ENTRIES. Like
bash and zsh with ignorespace, a command typed with a leading space is
never recorded.
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from .config import atomic_write_text, state_home
from .constants import APP_NAME

LOGGER = logging.getLogger(__name__)
MAX_ENTRIES = 5000
MAX_COMMAND = 300  # what the shell hooks report at most
MAX_FILE_BYTES = 4 * 1024 * 1024


@dataclass(frozen=True)
class HistoryEntry:
    command: str
    status: int | None
    duration: float
    finished_at: float  # Unix time
    directory: str = ""
    place: str = ""  # tab or pane name, e.g. "🔒 Umbrel"

    @property
    def failed(self) -> bool:
        return self.status not in (None, 0)


def should_record(command: str) -> bool:
    return bool(command.strip()) and not command.startswith(" ")


def parse_line(line: str) -> HistoryEntry | None:
    try:
        data = json.loads(line)
        command = str(data["command"])[:MAX_COMMAND]
        status = data.get("status")
        if status is not None and (isinstance(status, bool) or not isinstance(status, int)):
            return None
        entry = HistoryEntry(
            command=command,
            status=status,
            duration=max(0.0, float(data.get("duration", 0))),
            finished_at=float(data["finished_at"]),
            directory=str(data.get("directory", ""))[:4096],
            place=str(data.get("place", ""))[:80],
        )
    except (ValueError, TypeError, KeyError, AttributeError):
        return None
    return entry if should_record(entry.command) else None


class HistoryStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or state_home() / APP_NAME / "history.jsonl"
        self.appended = 0

    def add(self, command: str, status: int | None, duration: float, directory: str = "", place: str = "",
            finished_at: float | None = None) -> HistoryEntry | None:
        if not should_record(command):
            return None
        entry = HistoryEntry(command[:MAX_COMMAND], status, round(max(0.0, duration), 3),
                             finished_at if finished_at is not None else time.time(), directory, place)
        line = json.dumps(asdict(entry), ensure_ascii=False) + "\n"
        try:
            self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            descriptor = os.open(self.path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
            with os.fdopen(descriptor, "a", encoding="utf-8") as handle:
                handle.write(line)
        except OSError as error:
            LOGGER.warning("histórico de comandos não gravado: %s", error)
            return None
        self.appended += 1
        if self.appended % 200 == 0:
            self.trim()
        return entry

    def load(self) -> list[HistoryEntry]:
        """Valid entries, newest first; damaged lines are skipped."""
        try:
            if self.path.stat().st_size > MAX_FILE_BYTES * 2:
                self.trim()
            lines = self.path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return []
        entries = [entry for entry in map(parse_line, lines[-MAX_ENTRIES:]) if entry is not None]
        entries.reverse()
        return entries

    def trim(self) -> None:
        try:
            lines = self.path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return
        if len(lines) > MAX_ENTRIES:
            atomic_write_text(self.path, "\n".join(lines[-MAX_ENTRIES:]) + "\n", ".history.")

    def clear(self) -> bool:
        try:
            self.path.unlink(missing_ok=True)
            return True
        except OSError:
            return False


def search(entries: list[HistoryEntry], text: str = "", only_failed: bool = False,
           unique: bool = True) -> list[HistoryEntry]:
    """Entries whose command, folder or place contain every word of ``text``.

    With ``unique`` a command shows once, at its most recent run.
    """
    words = text.casefold().split()
    seen: set[str] = set()
    result = []
    for entry in entries:
        if only_failed and not entry.failed:
            continue
        haystack = f"{entry.command} {entry.directory} {entry.place}".casefold()
        if any(word not in haystack for word in words):
            continue
        if unique:
            if entry.command in seen:
                continue
            seen.add(entry.command)
        result.append(entry)
    return result
