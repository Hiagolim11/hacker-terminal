"""Dictation without a window: record, transcribe, type into the terminal.

One shortcut (or the microphone button) starts it: it records a few seconds
from the microphone — a countdown shows in the status bar — then stops on its
own (or earlier if you press the shortcut again), transcribes with a local
Whisper model in an isolated subprocess, and feeds the text into the active
pane (no Enter, so you can review it). There is no dialog. The first time it
runs, the optional dependencies are checked and, if missing, installed in the
background — nothing to install by hand, and the interface never freezes.
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

from ..runtime import GLib

PACKAGES = ["faster-whisper>=1.1,<2", "sounddevice>=0.5,<1", "numpy>=1.24,<3"]
ROOT = str(Path(__file__).resolve().parents[2])
MAX_SECONDS = max(2, int(os.environ.get("HT_SPEECH_SECONDS", "8") or 8))


class SpeechController:
    """Drives dictation for one window. State: idle, preparing, recording, busy."""

    def __init__(self, window):
        self.window = window
        self.state = "idle"
        self.ready = False
        self.process = None
        self.output = None
        self.poll_timer = 0
        self.count_timer = 0
        self.remaining = 0

    # ------------------------------------------------------------------ status
    def say(self, text: str, transient: bool = False) -> None:
        status = getattr(self.window, "status", None)
        if status is not None:
            status.set_text(text)
            if transient:
                GLib.timeout_add(5000, self._clear, text)

    def _clear(self, text: str) -> bool:
        status = getattr(self.window, "status", None)
        if status is not None and status.get_text() == text:
            status.set_text("")
        return False

    def _mark_button(self, active: bool) -> None:
        button = getattr(self.window, "dictate_button", None)
        if button is not None:
            context = button.get_style_context()
            (context.add_class if active else context.remove_class)("recording")

    # ------------------------------------------------------------------ toggle
    def toggle(self) -> None:
        if self.state == "recording":
            self.stop()
        elif self.state == "idle":
            self.begin()
        # preparing / busy: ignore until it settles

    def begin(self) -> None:
        if self.ready:
            self.start_recording()
            return
        self.state = "preparing"
        self.say("Preparando o ditado (primeira vez pode demorar)…")
        threading.Thread(target=self._prepare, daemon=True).start()

    # ------------------------------------------------------------- dependencies
    def _prepare(self) -> None:
        ok = self.have_deps()
        if not ok:
            ok = self._install() and self.have_deps()
        GLib.idle_add(self._prepared, ok)

    def _prepared(self, ok: bool) -> bool:
        if ok:
            self.ready = True
            self.start_recording()
        else:
            self.state = "idle"
            self.say("Não consegui preparar o ditado (dependências de fala). Veja requirements-speech.txt.",
                     transient=True)
        return False

    @staticmethod
    def have_deps() -> bool:
        try:
            return subprocess.run(
                [sys.executable, "-c", "import faster_whisper, sounddevice, numpy"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60,
            ).returncode == 0
        except (OSError, subprocess.SubprocessError):
            return False

    def _install(self) -> bool:
        try:
            return subprocess.run(
                [sys.executable, "-m", "pip", "install", "--break-system-packages", *PACKAGES],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=1800,
            ).returncode == 0
        except (OSError, subprocess.SubprocessError):
            return False

    # --------------------------------------------------------------- recording
    def start_recording(self) -> None:
        try:
            self.output = tempfile.TemporaryFile(mode="w+b")
            self.process = subprocess.Popen(
                [sys.executable, "-m", "hackerterminal.speech"], cwd=ROOT,
                stdout=self.output, stderr=subprocess.DEVNULL,
            )
        except OSError as error:
            if self.output is not None:
                self.output.close()
                self.output = None
            self.say(f"Não foi possível gravar: {error}", transient=True)
            return
        self.state = "recording"
        self._mark_button(True)
        self.remaining = MAX_SECONDS
        self.say(f"🎤 Gravando… {self.remaining}s · Ctrl+Shift+M para parar")
        self.poll_timer = GLib.timeout_add(150, self.poll)
        self.count_timer = GLib.timeout_add(1000, self._tick)

    def _tick(self) -> bool:
        if self.state != "recording":
            self.count_timer = 0
            return False
        self.remaining -= 1
        if self.remaining <= 0:
            self.count_timer = 0
            self.stop()
            return False
        self.say(f"🎤 Gravando… {self.remaining}s · Ctrl+Shift+M para parar")
        return True

    def stop(self) -> None:
        if self.process is None:
            return
        self.state = "busy"
        self._mark_button(False)
        if self.count_timer:
            GLib.source_remove(self.count_timer)
            self.count_timer = 0
        self.say("Transcrevendo…")
        if self.process.poll() is None:
            try:
                self.process.send_signal(signal.SIGTERM)
            except (ProcessLookupError, OSError):
                pass

    def poll(self) -> bool:
        if self.process is None:
            self.poll_timer = 0
            return False
        if self.process.poll() is None:
            return True  # still recording or transcribing
        self.poll_timer = 0
        self._finish()
        return False

    def _finish(self) -> None:
        text = ""
        message = ""
        try:
            self.output.seek(0)
            result = json.loads(self.output.read().decode("utf-8") or "{}")
            if result.get("error") == "missing-deps":
                self.ready = False
                message = "Faltam dependências de fala; serão instaladas no próximo uso."
            elif "error" in result:
                message = result["error"]
            else:
                text = (result.get("text") or "").strip()
                message = "" if text else "Nenhuma fala detectada — fale mais perto do microfone."
        except (ValueError, OSError):
            message = "Falha ao transcrever. Verifique o microfone e a memória."
        finally:
            if self.output is not None:
                self.output.close()
            self.output = None
            self.process = None
            self.state = "idle"
        if text:
            self.type_into_terminal(text)
        if message:
            self.say(message, transient=True)

    def type_into_terminal(self, text: str) -> None:
        getter = getattr(self.window, "get_active_terminal", None)
        pane = getter() if getter is not None else None
        terminal = getattr(pane, "terminal", None)
        if terminal is not None:
            terminal.feed_child(text.replace("\n", " ").encode())

    # ------------------------------------------------------------------ cleanup
    def cleanup(self, *_) -> None:
        for attribute in ("poll_timer", "count_timer"):
            source = getattr(self, attribute, 0)
            if source:
                GLib.source_remove(source)
                setattr(self, attribute, 0)
        if self.process is not None:
            if self.process.poll() is None:
                self.process.kill()
            self.process.wait()
            self.process = None
        if self.output is not None:
            self.output.close()
            self.output = None
        self.state = "idle"


__all__ = ["SpeechController"]
