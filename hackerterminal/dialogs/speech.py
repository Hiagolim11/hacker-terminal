"""Dictation without a window: record, transcribe, type into the terminal.

A single shortcut (or the microphone button) toggles it. The first press
records from the microphone; the second stops recording, transcribes with a
local Whisper model in an isolated subprocess, and feeds the text into the
active pane (no Enter, so you can review it). The first time it runs, the
optional dependencies are installed automatically in the background — there is
nothing to install by hand. Progress shows in the status bar.
"""
from __future__ import annotations

import json
import signal
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

from ..runtime import GLib

PACKAGES = ["faster-whisper>=1.1,<2", "sounddevice>=0.5,<1", "numpy>=1.24,<3"]
ROOT = str(Path(__file__).resolve().parents[2])


class SpeechController:
    """Drives dictation for one window. State: idle, installing, recording, busy."""

    def __init__(self, window):
        self.window = window
        self.state = "idle"
        self.process = None
        self.output = None
        self.timer = 0

    # ------------------------------------------------------------------ status
    def say(self, text: str, transient: bool = False) -> None:
        status = getattr(self.window, "status", None)
        if status is not None:
            status.set_text(text)
            if transient:
                GLib.timeout_add(4000, self._clear, text)

    def _clear(self, text: str) -> bool:
        status = getattr(self.window, "status", None)
        if status is not None and status.get_text() == text:
            status.set_text("")
        return False

    # ------------------------------------------------------------------ toggle
    def toggle(self) -> None:
        if self.state == "recording":
            self.stop()
        elif self.state == "idle":
            self.begin()
        # installing / busy: ignore until it settles

    def begin(self) -> None:
        if self.have_deps():
            self.start_recording()
            return
        self.state = "installing"
        self.say("Preparando reconhecimento de fala (primeira vez, pode demorar)…")
        threading.Thread(target=self._install, daemon=True).start()

    # ------------------------------------------------------------- dependencies
    @staticmethod
    def have_deps() -> bool:
        try:
            return subprocess.run(
                [sys.executable, "-c", "import faster_whisper, sounddevice, numpy"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30,
            ).returncode == 0
        except (OSError, subprocess.SubprocessError):
            return False

    def _install(self) -> None:
        try:
            completed = subprocess.run(
                [sys.executable, "-m", "pip", "install", "--break-system-packages", *PACKAGES],
                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=1800,
            )
            ok = completed.returncode == 0
        except (OSError, subprocess.SubprocessError):
            ok = False
        GLib.idle_add(self._installed, ok)

    def _installed(self, ok: bool) -> bool:
        self.state = "idle"
        if ok and self.have_deps():
            self.start_recording()
        else:
            self.say("Não consegui instalar as dependências de fala. Veja requirements-speech.txt.", transient=True)
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
        self.say("🎤 Ouvindo… pressione o atalho de novo para transcrever")
        self.timer = GLib.timeout_add(200, self.poll)

    def stop(self) -> None:
        if self.process is None:
            return
        self.state = "busy"
        self.say("Transcrevendo…")
        if self.process.poll() is None:
            try:
                self.process.send_signal(signal.SIGTERM)
            except (ProcessLookupError, OSError):
                pass

    def poll(self) -> bool:
        if self.process is None:
            self.timer = 0
            return False
        if self.process.poll() is None:
            return True  # keep waiting (recording or transcribing)
        self.timer = 0
        self._finish()
        return False

    def _finish(self) -> None:
        text = ""
        message = ""
        try:
            self.output.seek(0)
            result = json.loads(self.output.read().decode("utf-8") or "{}")
            if result.get("error") == "missing-deps":
                message = "Faltam dependências de fala; tentarei instalar no próximo uso."
            elif "error" in result:
                message = result["error"]
            else:
                text = (result.get("text") or "").strip()
                message = "" if text else "Nenhuma fala detectada."
        except (ValueError, OSError):
            message = "Falha ao transcrever. Verifique memória e dependências."
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
        if self.timer:
            GLib.source_remove(self.timer)
            self.timer = 0
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
