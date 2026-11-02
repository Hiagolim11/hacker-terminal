"""Optional, isolated local speech recognition worker (no GTK imports).

Run as ``python -m hackerterminal.speech``. With ``--file`` it transcribes an
audio file; otherwise it records from the microphone until it receives
SIGTERM/SIGINT (the app sends it when you press the shortcut again) and then
transcribes. The result is printed as one JSON line: ``{"text": ...}`` or
``{"error": ...}``. A small Whisper model is the default so dictation on a CPU
stays fast; override with ``--model`` or the ``HT_SPEECH_MODEL`` env var.
"""
from __future__ import annotations

import argparse
import json
import os

DEFAULT_MODEL = os.environ.get("HT_SPEECH_MODEL", "base")
SAMPLE_RATE = 16000
MAX_SECONDS = 120  # safety cap: never record longer than this


def transcribe(source, model_factory=None, model_name=DEFAULT_MODEL, cpu_threads=0):
    if model_factory is None:
        from faster_whisper import WhisperModel
        model_factory = WhisperModel
    # greedy decoding (beam_size=1) and every core: short dictation on a CPU
    # must feel instant, not take minutes.
    threads = cpu_threads or os.cpu_count() or 4
    model = model_factory(model_name, device="cpu", compute_type="int8", cpu_threads=threads)
    segments, _ = model.transcribe(source, beam_size=1, vad_filter=True,
                                   condition_on_previous_text=False, task="transcribe")
    return " ".join(segment.text.strip() for segment in segments if segment.text.strip())


def record_until_stop():
    """Record mono 16 kHz audio until SIGTERM/SIGINT, returning a float32 array."""
    import signal
    import threading

    import sounddevice as sd
    import numpy as np

    frames: list = []
    stop = threading.Event()

    def on_frame(indata, _frames, _time, _status):
        frames.append(indata.copy())

    for signum in (signal.SIGTERM, signal.SIGINT):
        signal.signal(signum, lambda *_: stop.set())

    with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="float32", callback=on_frame):
        stop.wait(timeout=MAX_SECONDS)

    if not frames:
        return np.zeros(0, dtype="float32")
    audio = np.concatenate(frames).reshape(-1)
    if not np.isfinite(audio).all():
        raise ValueError("O microfone retornou áudio inválido.")
    return audio


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--file")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    args = parser.parse_args()
    try:
        source = args.file if args.file else record_until_stop()
        result = transcribe(source, model_name=args.model)
        print(json.dumps({"text": result}, ensure_ascii=False))
        return 0
    except ImportError:
        print(json.dumps({"error": "missing-deps"}))
    except Exception as error:  # noqa: BLE001 - reported to the user as text
        print(json.dumps({"error": str(error)}))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
