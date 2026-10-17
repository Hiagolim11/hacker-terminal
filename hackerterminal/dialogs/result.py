"""A quick action's output in its own small window, instead of the terminal.

The command runs in the background through the user's shell, in the
active pane's folder, with no terminal attached: its output streams into
the window as it arrives, and the window ends with the exit status and
the time it took. "Rodar no terminal" falls back to typing it in the pane.
"""

from __future__ import annotations

import codecs
import os
import re
import signal
import time
from pathlib import Path
from typing import Callable

from ..runtime import Gdk, Gio, GLib, Gtk
from ..terminal import format_duration, resolve_shell

ANSI = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07\x1b]*(?:\x07|\x1b\\)|[@-Z\\-_])")
MAX_OUTPUT = 2 * 1024 * 1024  # characters kept; the rest is cut with a note
CHUNK = 64 * 1024


def clean_output(text: str) -> str:
    """Terminal escape codes and carriage-return redraws out of the text."""
    text = ANSI.sub("", text)
    # "progress\rprogress 50%\r..." keeps only the last redraw of each line
    return "\n".join(line.rsplit("\r", 1)[-1] for line in text.split("\n"))


class ResultWindow(Gtk.Window):
    def __init__(self, parent: Gtk.Window | None, title: str, command: str, directory: Path,
                 run_in_terminal: Callable[[str], None]) -> None:
        super().__init__(title=title, transient_for=parent, destroy_with_parent=True)
        self.command = command
        self.run_in_terminal = run_in_terminal
        self.process: Gio.Subprocess | None = None
        self.cancellable = Gio.Cancellable()
        self.started = time.monotonic()
        self.decoder = codecs.getincrementaldecoder("utf-8")("replace")
        self.kept = 0
        self.truncated = False
        self.finished = False
        self.exit_status: int | None = None
        self.set_default_size(720, 420)
        self.get_style_context().add_class("result-window")
        self.connect("destroy", lambda *_: self.stop())
        self.connect("key-press-event", self.on_key)

        header = Gtk.HeaderBar(title=title, show_close_button=True)
        self.status = Gtk.Label(label="Rodando…")
        self.status.get_style_context().add_class("result-status")
        header.set_subtitle(command if len(command) <= 70 else command[:69] + "…")
        header.pack_end(self.status)
        self.set_titlebar(header)

        self.view = Gtk.TextView(editable=False, cursor_visible=False, monospace=True,
                                 wrap_mode=Gtk.WrapMode.WORD_CHAR, left_margin=14, right_margin=14,
                                 top_margin=12, bottom_margin=12)
        self.view.get_style_context().add_class("result-output")
        self.buffer = self.view.get_buffer()
        self.end_mark = self.buffer.create_mark(None, self.buffer.get_end_iter(), False)
        scroller = Gtk.ScrolledWindow()
        scroller.add(self.view)

        bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        bar.get_style_context().add_class("result-bar")
        self.stop_button = Gtk.Button(label="Parar")
        self.stop_button.connect("clicked", lambda *_: self.stop())
        terminal_button = Gtk.Button(label="Rodar no terminal")
        terminal_button.set_tooltip_text("Digita o comando no painel atual, como antes")
        terminal_button.connect("clicked", lambda *_: self.to_terminal())
        copy_button = Gtk.Button(label="Copiar")
        copy_button.connect("clicked", lambda *_: self.copy())
        bar.pack_start(self.stop_button, False, False, 0)
        bar.pack_end(copy_button, False, False, 0)
        bar.pack_end(terminal_button, False, False, 0)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.pack_start(scroller, True, True, 0)
        box.pack_start(bar, False, False, 0)
        self.add(box)
        self.show_all()
        self.start(directory)

    # ----------------------------------------------------------- process
    def start(self, directory: Path) -> None:
        launcher = Gio.SubprocessLauncher.new(Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_MERGE)
        launcher.set_cwd(str(directory if directory.is_dir() else Path.home()))
        launcher.setenv("TERM", "dumb", True)
        launcher.setenv("NO_COLOR", "1", True)
        launcher.set_stdin_file_path(os.devnull)  # nothing can wait for typing that never comes
        # setsid: the command and everything it starts form one group, so
        # "Parar" stops a pipeline such as "ping ... | grep" as a whole.
        try:
            self.process = launcher.spawnv(["setsid", resolve_shell(), "-c", self.command])
        except GLib.Error as error:
            self.append(f"Não foi possível iniciar o comando: {error.message}\n")
            self.done(127)
            return
        self.read_more()
        self.process.wait_async(self.cancellable, self.on_exit)

    def read_more(self) -> None:
        stream = self.process.get_stdout_pipe()
        stream.read_bytes_async(CHUNK, GLib.PRIORITY_DEFAULT, self.cancellable, self.on_bytes)

    def on_bytes(self, stream, result) -> None:
        try:
            data = stream.read_bytes_finish(result)
        except GLib.Error:
            return  # cancelled: the window closed
        chunk = data.get_data() if data is not None else b""
        if not chunk:
            self.append(self.decoder.decode(b"", final=True))
            return
        self.append(self.decoder.decode(chunk))
        self.read_more()

    def on_exit(self, process, result) -> None:
        try:
            process.wait_finish(result)
        except GLib.Error:
            return
        if process.get_if_signaled():
            self.done(128 + process.get_term_sig(), stopped=True)
        else:
            self.done(process.get_exit_status())

    def stop(self) -> None:
        if self.process is not None and not self.finished:
            try:
                os.killpg(int(self.process.get_identifier()), signal.SIGTERM)
            except (ProcessLookupError, PermissionError, TypeError, ValueError):
                self.process.force_exit()

    # ----------------------------------------------------------- display
    def append(self, text: str) -> None:
        if not text or self.truncated:
            return
        text = clean_output(text)
        if not self.kept:
            text = text.lstrip("\n")  # many commands open with a blank line
            if not text:
                return
        if self.kept + len(text) > MAX_OUTPUT:
            text = text[: MAX_OUTPUT - self.kept] + "\n[saída longa demais: o restante foi omitido]\n"
            self.truncated = True
        self.kept += len(text)
        self.buffer.insert(self.buffer.get_end_iter(), text)
        self.view.scroll_mark_onscreen(self.end_mark)

    def done(self, status: int, stopped: bool = False) -> None:
        self.finished = True
        self.exit_status = status
        elapsed = time.monotonic() - self.started
        took = "< 1 s" if elapsed < 1 else format_duration(elapsed)
        if stopped:
            text, style = f"Parado após {took}", "result-failed"
        elif status == 0:
            text, style = f"✓ Concluído em {took}", "result-ok"
        else:
            text, style = f"✗ Saída {status} · {took}", "result-failed"
        self.status.set_text(text)
        self.status.get_style_context().add_class(style)
        self.stop_button.set_sensitive(False)
        if not self.buffer.get_char_count():
            self.append("(o comando não mostrou nada)\n")

    def copy(self) -> None:
        start, end = self.buffer.get_bounds()
        Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).set_text(self.buffer.get_text(start, end, False), -1)
        self.status.set_text("Copiado")

    def to_terminal(self) -> None:
        self.run_in_terminal(self.command)
        self.destroy()

    def on_key(self, _window, event) -> bool:
        if event.keyval == Gdk.KEY_Escape:
            self.destroy()
            return True
        return False


__all__ = ["ResultWindow", "clean_output"]
