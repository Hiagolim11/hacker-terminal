"""Optional synthesized interface sounds."""

from __future__ import annotations

import math
import os
import struct
import tempfile
import wave
from pathlib import Path

from .runtime import load_gst


def make_tone(path: Path, notes: list[tuple[float, float]], volume: float = 0.18) -> Path | None:
    try:
        if path.is_file() and path.stat().st_size > 44:
            return path
    except OSError:
        pass
    rate = 22_050
    temporary_path: Path | None = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        os.close(descriptor)
        temporary_path = Path(temporary_name)
        with wave.open(str(temporary_path), "wb") as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(rate)
            for frequency, duration in notes:
                count = int(rate * duration)
                data = bytearray()
                for index in range(count):
                    envelope = min(1.0, index / 160) * min(1.0, (count - index) / 240)
                    sample = int(32_767 * volume * envelope * math.sin(2 * math.pi * frequency * index / rate))
                    data.extend(struct.pack("<h", sample))
                audio.writeframes(data)
        temporary_path.replace(path)
        return path
    except (OSError, wave.Error):
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        return None


class SoundPlayer:
    """Plays a short sound; GStreamer is set up only when it first plays."""

    def __init__(self, path: Path | None, volume: float) -> None:
        self.path = path
        self.volume = volume
        self.player = None
        self.prepared = False

    def prepare(self) -> None:
        self.prepared = True
        Gst = load_gst()
        if Gst is not None and self.path is not None:
            Gst.init(None)
            self.player = Gst.ElementFactory.make("playbin", None)
            if self.player:
                self.player.set_property("uri", Gst.filename_to_uri(str(self.path)))
                self.player.set_property("volume", self.volume)

    def play(self) -> None:
        if not self.prepared:
            self.prepare()
        if self.player is not None:
            Gst = load_gst()
            self.player.set_state(Gst.State.NULL)
            self.player.set_state(Gst.State.PLAYING)
