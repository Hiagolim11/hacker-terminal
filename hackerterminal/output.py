"""Terminal output export and recording, separate from the pane widget."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from .runtime import GLib, Vte
from .storage import write_text

LOGGER = logging.getLogger(__name__)


HTML_HEADER = (
    "<!doctype html>\n<html><head><meta charset=\"utf-8\"><title>{title}</title>"
    "<style>body{{background:{background};color:{foreground};margin:24px}}"
    "pre{{font:13px/1.35 monospace;white-space:pre-wrap;margin:0}}</style></head><body>\n"
)


def unlimited_scrollback(limit: int) -> bool:
    # VTE reports an unlimited scrollback (set as -1) as G_MAXLONG.
    return limit < 0 or limit >= 2**31


class OutputRecorder:
    """Append a pane's finished lines to a file while recording.

    Lines are written as soon as the cursor has moved past them, every
    couple of seconds, so a later `clear` (which may wipe the scrollback)
    or a scrollback overflow cannot lose what was already recorded.
    """

    FLUSH_SECONDS = 1

    def __init__(self, terminal: Vte.Terminal, path: Path, html: bool, header: str = "") -> None:
        self.terminal = terminal
        self.path = path
        self.html = html
        self.saved_row = terminal.get_cursor_position()[1]
        self.lines = 0
        self.lost_rows = 0
        self.handle = path.open("w", encoding="utf-8")
        os.chmod(path, 0o600)
        if header:
            self.handle.write(header)
        self.source_id = GLib.timeout_add_seconds(self.FLUSH_SECONDS, self._tick)
        # Fast output could push unsaved rows out of the scrollback between
        # ticks; flush early once half of it is pending.
        self.changed_handler = terminal.connect("contents-changed", self._on_contents_changed)

    def _on_contents_changed(self, terminal) -> None:
        # The scrollback is unlimited while recording, so this only keeps
        # each write (and the temporary scrollback) reasonably small.
        if self.handle is not None and terminal.get_cursor_position()[1] - self.saved_row > 5_000:
            self._tick()

    def first_available_row(self) -> int:
        limit = self.terminal.get_scrollback_lines()
        if unlimited_scrollback(limit):
            return 0  # nothing has been dropped
        cursor_row = self.terminal.get_cursor_position()[1]
        return max(0, cursor_row - limit + 1)

    def flush(self) -> None:
        if self.handle is None:
            return
        cursor_row = self.terminal.get_cursor_position()[1]
        if cursor_row < self.saved_row:
            self.saved_row = cursor_row  # the scrollback was reset under us
        first = self.first_available_row()
        if self.saved_row < first:
            self.lost_rows += first - self.saved_row
            self.saved_row = first
        end = cursor_row - 1  # only rows the cursor has left are final
        if end < self.saved_row:
            return
        fmt = Vte.Format.HTML if self.html else Vte.Format.TEXT
        result = self.terminal.get_text_range_format(fmt, self.saved_row, 0, end, self.terminal.get_column_count())
        text = result[0] if isinstance(result, tuple) else result
        if text:
            if self.html:
                text = text.replace("<pre>", "").replace("</pre>", "")
            self.handle.write(text if text.endswith("\n") else text + "\n")
            self.handle.flush()
        self.lines += end - self.saved_row + 1
        self.saved_row = end + 1

    def _tick(self) -> bool:
        if self.handle is None:
            return False
        try:
            self.flush()
        except (OSError, ValueError) as error:
            LOGGER.warning("gravação interrompida: %s", error)
            self.stop()
            return False
        return True

    def stop(self) -> None:
        if self.handle is None:
            return
        if self.source_id and GLib.MainContext.default().find_source_by_id(self.source_id) is not None:
            GLib.source_remove(self.source_id)
        self.source_id = 0
        if self.changed_handler:
            self.terminal.disconnect(self.changed_handler)
            self.changed_handler = 0
        try:
            # Include the current line too: recording is over.
            cursor_row = self.terminal.get_cursor_position()[1]
            if cursor_row >= self.saved_row:
                fmt = Vte.Format.HTML if self.html else Vte.Format.TEXT
                result = self.terminal.get_text_range_format(
                    fmt, max(self.saved_row, self.first_available_row()), 0, cursor_row, self.terminal.get_column_count()
                )
                text = result[0] if isinstance(result, tuple) else result
                if text and text.strip():
                    if self.html:
                        text = text.replace("<pre>", "").replace("</pre>", "")
                    self.handle.write(text.rstrip("\n") + "\n")
            if self.html:
                self.handle.write("</pre></body></html>\n")
        finally:
            self.handle.close()
            self.handle = None


def save_output(terminal: Vte.Terminal, path: Path, header: str = "") -> int:
    """Write everything still in the scrollback; returns the line count."""
    html = path.suffix.lower() in (".html", ".htm")
    cursor_row = terminal.get_cursor_position()[1]
    limit = terminal.get_scrollback_lines()
    first = 0 if unlimited_scrollback(limit) else max(0, cursor_row - limit + 1)
    fmt = Vte.Format.HTML if html else Vte.Format.TEXT
    result = terminal.get_text_range_format(fmt, first, 0, cursor_row, terminal.get_column_count())
    text = (result[0] if isinstance(result, tuple) else result) or ""
    if html:
        text = header + text.replace("<pre>", "").replace("</pre>", "") + "</pre></body></html>\n"
    elif not text.endswith("\n"):
        text += "\n"
    write_text(path, text, ".output.")
    return cursor_row - first + 1


