"""Low-latency mechanical keyboard sounds.

Two sources feed the same engine:

* a modal synthesizer that models the physical events of Cherry-style
  switches (click jacket, tactile bump, bottom-out, top-out, stabilizers);
* recorded sound packs, either Mechvibes packs (``config.json``) or a plain
  folder of ``press*.wav`` / ``release*.wav`` files.

Everything is decoded to 48 kHz mono PCM up front. Playback pushes the
buffer straight into an already-running GStreamer voice with ``sync=false``,
so a key press costs one buffer push instead of starting a pipeline.
"""

from __future__ import annotations

import array
import hashlib
import json
import logging
import math
import os
import random
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .runtime import Gdk, GLib, Gst

LOGGER = logging.getLogger(__name__)
RATE = 48_000
VOICES = 8
IDLE_PAUSE_SECONDS = 15
SYNTH_VERSION = 4
VARIANTS = 8
SIZES = ("normal", "large", "enter", "space")
KINDS = ("press", "release")
SYNTH_SWITCHES = {
    "red": "Linear (estilo Red)",
    "brown": "Tátil (estilo Brown)",
    "blue": "Clicky (estilo Blue)",
}
DEFAULT_SWITCH = "brown"

Samples = array.array


# --------------------------------------------------------------------------
# Synthesis


@dataclass(frozen=True)
class Mode:
    """A decaying resonance excited by an impact."""

    frequency: float
    decay_ms: float
    gain: float


@dataclass(frozen=True)
class Impact:
    """One physical collision inside the switch."""

    at_ms: float
    amplitude: float
    modes: tuple[Mode, ...]
    noise_ms: float = 1.2
    brightness: float = 0.5  # share of the excitation that is noise


BOTTOM_OUT = (
    Mode(310, 24, 0.50),   # case / plate body
    Mode(560, 16, 0.48),
    Mode(1300, 8.5, 0.50),  # keycap "clack"
    Mode(2900, 4.5, 0.46),
    Mode(4700, 2.2, 0.26),  # stem on housing
)
TOP_OUT = (
    Mode(760, 8, 0.30),
    Mode(1900, 5.5, 0.46),
    Mode(3500, 3.0, 0.36),
    Mode(5600, 1.4, 0.16),
)
CLICK = (
    Mode(3900, 2.4, 1.0),
    Mode(6300, 1.5, 0.75),
    Mode(9100, 0.9, 0.35),
)
TACTILE_TICK = (
    Mode(2350, 1.4, 0.8),
    Mode(5200, 0.9, 0.5),
)
STABILIZER = (
    Mode(2150, 5.0, 0.6),
    Mode(3150, 3.5, 0.45),
    Mode(4700, 2.0, 0.2),
)


def switch_events(switch: str, kind: str) -> list[Impact]:
    """The collisions a switch produces on press or release, in order."""
    if kind == "press":
        if switch == "blue":
            # The click jacket snaps right at actuation, then bottoms out.
            return [
                Impact(0.0, 0.95, CLICK, noise_ms=0.6, brightness=0.7),
                Impact(1.3, 0.45, CLICK, noise_ms=0.4, brightness=0.7),
                Impact(9.0, 0.70, BOTTOM_OUT),
            ]
        if switch == "brown":
            # A faint tick from the tactile leaf, then a regular bottom-out.
            return [
                Impact(0.0, 0.16, TACTILE_TICK, noise_ms=0.5, brightness=0.6),
                Impact(6.5, 0.92, BOTTOM_OUT),
            ]
        return [Impact(0.0, 0.95, BOTTOM_OUT)]
    if switch == "blue":
        # The jacket clicks again on the way up before the stem tops out.
        return [
            Impact(0.0, 0.55, CLICK, noise_ms=0.5, brightness=0.7),
            Impact(4.0, 0.40, TOP_OUT),
        ]
    return [Impact(0.0, 0.50, TOP_OUT)]


SIZE_SHAPES = {
    # frequency scale, decay scale, loudness, stabilizer rattles
    "normal": (1.0, 1.0, 1.0, 0),
    "large": (0.86, 1.25, 1.05, 1),
    "enter": (0.80, 1.35, 1.10, 1),
    "space": (0.62, 1.70, 1.20, 2),
}


def _render_impact(out: list[float], impact: Impact, rng: random.Random,
                   frequency_scale: float, decay_scale: float) -> None:
    start = int(max(0.0, impact.at_ms + rng.uniform(-0.4, 0.4)) * RATE / 1000)
    noise_length = max(1, int(impact.noise_ms * RATE / 1000))
    pulse_length = max(2, int(0.00035 * RATE))
    excitation = []
    for index in range(max(noise_length, pulse_length)):
        pulse = math.sin(math.pi * index / pulse_length) if index < pulse_length else 0.0
        noise = rng.uniform(-1.0, 1.0) * math.exp(-index / max(1.0, noise_length / 3))
        excitation.append((1 - impact.brightness) * pulse + impact.brightness * noise)
    amplitude = impact.amplitude * rng.uniform(0.88, 1.12)
    for mode in impact.modes:
        frequency = mode.frequency * frequency_scale * rng.uniform(0.96, 1.04)
        if frequency >= RATE / 2.2:
            continue
        decay = mode.decay_ms * decay_scale * rng.uniform(0.9, 1.1) / 1000
        radius = math.exp(-1.0 / (decay * RATE))
        a1 = 2 * radius * math.cos(2 * math.pi * frequency / RATE)
        a2 = radius * radius
        y1 = y2 = 0.0
        length = min(len(out) - start, int(decay * RATE * 7) + len(excitation))
        response = []
        for index in range(length):
            x = excitation[index] if index < len(excitation) else 0.0
            y = x + a1 * y1 - a2 * y2
            y2, y1 = y1, y
            response.append(y)
        # Normalize each mode to its own peak so the declared gains are the
        # real levels; otherwise long low modes swamp the click.
        peak = max((abs(value) for value in response), default=0.0)
        if peak <= 0:
            continue
        gain = mode.gain * amplitude / peak
        for index, value in enumerate(response):
            out[start + index] += gain * value


def synthesize(switch: str, kind: str, size: str, seed: int) -> Samples:
    """Render one keystroke sound as 16-bit mono PCM."""
    rng = random.Random(seed)
    frequency_scale, decay_scale, loudness, rattles = SIZE_SHAPES[size]
    frequency_scale *= rng.uniform(0.97, 1.03)
    events = switch_events(switch, kind)
    if rattles and kind == "press":
        last = events[-1].at_ms
        events = events + [
            Impact(last + rng.uniform(2.5, 4.5) + 4 * index, 0.18 / (index + 1), STABILIZER, 0.5, 0.6)
            for index in range(rattles)
        ]
    elif rattles:
        events = events + [Impact(rng.uniform(1.5, 3.0), 0.12, STABILIZER, 0.5, 0.6)]
    length = int(RATE * (0.075 if size == "normal" else 0.11))
    out = [0.0] * length
    for impact in events:
        _render_impact(out, impact, rng, frequency_scale, decay_scale)
    # Gentle fade so the tail never ends in a step.
    fade = int(0.006 * RATE)
    for index in range(fade):
        out[length - fade + index] *= 1 - index / fade
    peak = max(1e-9, max(abs(value) for value in out))
    scale = loudness * 0.8 / peak
    samples = array.array("h")
    for value in out:
        # Soft clip keeps transients punchy without hard distortion.
        samples.append(int(32_000 * math.tanh(value * scale)))
    return samples


# --------------------------------------------------------------------------
# Banks


@dataclass
class SoundBank:
    """Pre-decoded sounds grouped by (kind, size) plus optional per-key sounds."""

    name: str
    sounds: dict[tuple[str, str], list[Samples]] = field(default_factory=dict)
    per_key: dict[int, Samples] = field(default_factory=dict)
    release_per_key: dict[int, Samples] = field(default_factory=dict)

    def pick(self, kind: str, size: str, keycode: int) -> Samples | None:
        table = self.per_key if kind == "press" else self.release_per_key
        if keycode in table:
            return table[keycode]
        options = self.sounds.get((kind, size)) or self.sounds.get((kind, "normal"))
        if not options:
            return None
        # Each key keeps a stable voice with a little live variation.
        index = (keycode * 7 + random.randrange(2)) % len(options)
        return options[index]


def _cache_dir() -> Path:
    configured = os.environ.get("XDG_CACHE_HOME")
    base = Path(configured).expanduser() if configured else Path.home() / ".cache"
    return base / "hacker-terminal" / "keysounds"


def synth_bank(switch: str) -> SoundBank:
    """Build (or load from cache) the synthesized bank for a switch."""
    switch = switch if switch in SYNTH_SWITCHES else DEFAULT_SWITCH
    bank = SoundBank(SYNTH_SWITCHES[switch])
    cache = _cache_dir() / f"{switch}-v{SYNTH_VERSION}.pcm"
    count = len(KINDS) * len(SIZES) * VARIANTS
    try:
        raw = cache.read_bytes()
        index_size = 4 * count
        lengths = array.array("I")
        lengths.frombytes(raw[:index_size])
        offset = index_size
        for kind in KINDS:
            for size in SIZES:
                variants = []
                for _ in range(VARIANTS):
                    length = lengths[len(bank.sounds) * VARIANTS + len(variants)]
                    samples = array.array("h")
                    samples.frombytes(raw[offset:offset + length * 2])
                    offset += length * 2
                    variants.append(samples)
                bank.sounds[(kind, size)] = variants
        if offset == len(raw):
            return bank
    except (OSError, ValueError, IndexError):
        pass
    bank.sounds.clear()
    for kind in KINDS:
        for size in SIZES:
            base = int(hashlib.sha256(f"{switch}/{kind}/{size}".encode()).hexdigest()[:8], 16)
            bank.sounds[(kind, size)] = [synthesize(switch, kind, size, base + variant) for variant in range(VARIANTS)]
    try:
        cache.parent.mkdir(parents=True, exist_ok=True)
        lengths = array.array("I", [len(item) for kind in KINDS for size in SIZES for item in bank.sounds[(kind, size)]])
        body = b"".join(item.tobytes() for kind in KINDS for size in SIZES for item in bank.sounds[(kind, size)])
        temporary = cache.with_suffix(".tmp")
        temporary.write_bytes(lengths.tobytes() + body)
        temporary.replace(cache)
    except OSError as error:
        LOGGER.debug("cache de sons indisponível: %s", error)
    return bank


# --------------------------------------------------------------------------
# Sound packs

AUDIO_SUFFIXES = (".wav", ".ogg", ".oga", ".mp3", ".flac", ".opus")
# libuiohook (Mechvibes) codes for keys whose Linux evdev code differs.
EVDEV_TO_UIOHOOK = {
    96: 3612, 97: 3613, 98: 3637, 99: 3639, 100: 3640, 102: 60999, 103: 61000,
    104: 61001, 105: 61003, 106: 61005, 107: 61007, 108: 61008, 109: 61009,
    110: 61010, 111: 61011, 125: 3675, 126: 3676, 127: 3677,
}


class PackError(ValueError):
    """Raised when a sound pack cannot be read."""


@dataclass(frozen=True)
class SoundPack:
    identifier: str
    name: str
    path: Path


def decode_audio(path: Path) -> Samples:
    """Decode any GStreamer-supported file to 48 kHz mono 16-bit PCM."""
    if Gst is None:
        raise PackError("GStreamer não está disponível")
    Gst.init(None)
    pipeline = Gst.Pipeline.new(None)
    source = Gst.ElementFactory.make("filesrc", None)
    decoder = Gst.ElementFactory.make("decodebin", None)
    convert = Gst.ElementFactory.make("audioconvert", None)
    resample = Gst.ElementFactory.make("audioresample", None)
    sink = Gst.ElementFactory.make("appsink", None)
    if None in (source, decoder, convert, resample, sink):
        raise PackError("plugins do GStreamer ausentes para decodificar áudio")
    source.set_property("location", str(path))
    sink.set_property("caps", Gst.Caps.from_string(f"audio/x-raw,format=S16LE,rate={RATE},channels=1,layout=interleaved"))
    sink.set_property("sync", False)
    for element in (source, decoder, convert, resample, sink):
        pipeline.add(element)
    source.link(decoder)
    convert.link(resample)
    resample.link(sink)
    decoder.connect("pad-added", lambda _element, pad: pad.link(convert.get_static_pad("sink")))
    pipeline.set_state(Gst.State.PLAYING)
    data = bytearray()
    try:
        while True:
            sample = sink.emit("try-pull-sample", 5 * Gst.SECOND)
            if sample is None:
                break
            buffer = sample.get_buffer()
            ok, info = buffer.map(Gst.MapFlags.READ)
            if ok:
                data.extend(info.data)
                buffer.unmap(info)
        message = pipeline.get_bus().pop_filtered(Gst.MessageType.ERROR)
        if message is not None:
            raise PackError(f"{path.name}: {message.parse_error()[0].message}")
    finally:
        pipeline.set_state(Gst.State.NULL)
    if not data:
        raise PackError(f"{path.name}: nenhum áudio decodificado")
    samples = array.array("h")
    samples.frombytes(bytes(data[: len(data) // 2 * 2]))
    return samples


def _trim(samples: Samples, limit_seconds: float = 1.5) -> Samples:
    return samples[: int(RATE * limit_seconds)]


def pack_name(path: Path) -> str:
    config = path / "config.json"
    if config.is_file():
        try:
            name = json.loads(config.read_text(encoding="utf-8")).get("name")
            if isinstance(name, str) and name.strip():
                return " ".join(name.split())
        except (OSError, ValueError):
            pass
    return path.name


def load_pack(path: Path) -> SoundBank:
    """Load a Mechvibes pack or a folder of press/release recordings."""
    if not path.is_dir():
        raise PackError(f"pasta não encontrada: {path}")
    config = path / "config.json"
    if config.is_file():
        return _load_mechvibes(path, config)
    return _load_folder(path)


def _load_mechvibes(path: Path, config_path: Path) -> SoundBank:
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise PackError(f"config.json inválido: {error}") from error
    bank = SoundBank(pack_name(path))
    defines = config.get("defines") or {}
    if not isinstance(defines, dict):
        raise PackError("config.json sem 'defines'")
    kind = config.get("key_define_type", "single")
    decoded: dict[str, Samples] = {}

    def file_samples(name: str) -> Samples:
        candidate = (path / name).resolve()
        if path.resolve() not in candidate.parents:
            raise PackError(f"arquivo fora do pacote: {name}")
        if name not in decoded:
            decoded[name] = decode_audio(candidate)
        return decoded[name]

    by_code: dict[int, Samples] = {}
    if kind == "multi":
        for code, name in defines.items():
            if isinstance(name, str) and name and str(code).isdigit():
                by_code[int(code)] = _trim(file_samples(name))
    else:
        sound = config.get("sound")
        if not isinstance(sound, str):
            raise PackError("config.json sem o arquivo 'sound'")
        source = file_samples(sound)
        for code, span in defines.items():
            if not str(code).isdigit() or not isinstance(span, list) or len(span) != 2:
                continue
            start = int(float(span[0]) * RATE / 1000)
            length = int(float(span[1]) * RATE / 1000)
            if length > 0 and start < len(source):
                by_code[int(code)] = _trim(source[start:start + length])
    if not by_code:
        raise PackError("o pacote não define nenhum som de tecla")
    fallback = list(by_code.values())
    for evdev in range(1, 256):
        code = EVDEV_TO_UIOHOOK.get(evdev, evdev)
        if code in by_code:
            bank.per_key[evdev + 8] = by_code[code]  # X keycode = evdev + 8
    bank.sounds[("press", "normal")] = fallback[: VARIANTS * 4]
    return bank


def _load_folder(path: Path) -> SoundBank:
    bank = SoundBank(pack_name(path))
    files = sorted(item for item in path.iterdir() if item.suffix.lower() in AUDIO_SUFFIXES)
    pattern = re.compile(r"^(?:(normal|large|enter|space)[-_])?(press|release|down|up)[-_ ]?\d*$")
    for item in files:
        match = pattern.fullmatch(item.stem.lower())
        if match is None:
            continue
        size = match.group(1) or "normal"
        kind = "press" if match.group(2) in ("press", "down") else "release"
        bank.sounds.setdefault((kind, size), []).append(_trim(decode_audio(item)))
    if ("press", "normal") not in bank.sounds:
        raise PackError("a pasta precisa ter ao menos um arquivo press.wav (ou press1.ogg, down.wav…)")
    return bank


def packs_directory() -> Path:
    configured = os.environ.get("XDG_DATA_HOME")
    base = Path(configured).expanduser() if configured else Path.home() / ".local" / "share"
    return base / "hacker-terminal" / "soundpacks"


def list_packs(directory: Path | None = None) -> list[SoundPack]:
    directory = directory or packs_directory()
    if not directory.is_dir():
        return []
    packs = []
    for item in sorted(directory.iterdir()):
        if item.is_dir() and ((item / "config.json").is_file() or any(
            child.suffix.lower() in AUDIO_SUFFIXES for child in item.iterdir()
        )):
            packs.append(SoundPack(item.name, pack_name(item), item))
    return packs


# --------------------------------------------------------------------------
# Playback


def key_size(keyval: int) -> str:
    if keyval == Gdk.KEY_space:
        return "space"
    if keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter, Gdk.KEY_ISO_Enter):
        return "enter"
    if keyval in (
        Gdk.KEY_BackSpace, Gdk.KEY_Shift_L, Gdk.KEY_Shift_R, Gdk.KEY_Tab,
        Gdk.KEY_ISO_Left_Tab, Gdk.KEY_Caps_Lock,
    ):
        return "large"
    return "normal"


def _make_sink() -> object | None:
    preferred = os.environ.get("HACKER_TERMINAL_AUDIO_SINK")
    for name in ([preferred] if preferred else []) + ["pulsesink", "pipewiresink", "autoaudiosink"]:
        sink = Gst.ElementFactory.make(name, None)
        if sink is None:
            continue
        properties = {prop.name for prop in sink.list_properties()}
        if "sync" in properties:
            sink.set_property("sync", False)  # render on arrival: no scheduling delay
        if "buffer-time" in properties:
            sink.set_property("buffer-time", 20_000)
            sink.set_property("latency-time", 5_000)
        return sink
    return None


class _Voice:
    def __init__(self) -> None:
        self.pipeline = Gst.Pipeline.new(None)
        self.source = Gst.ElementFactory.make("appsrc", None)
        convert = Gst.ElementFactory.make("audioconvert", None)
        self.volume = Gst.ElementFactory.make("volume", None)
        sink = _make_sink()
        self.sink = sink
        if None in (self.source, convert, self.volume, sink):
            raise RuntimeError("elementos de áudio indisponíveis")
        self.source.set_property("caps", Gst.Caps.from_string(f"audio/x-raw,format=S16LE,rate={RATE},channels=1,layout=interleaved"))
        self.source.set_property("format", Gst.Format.TIME)
        self.source.set_property("is-live", True)
        self.source.set_property("do-timestamp", True)
        for element in (self.source, convert, self.volume, sink):
            self.pipeline.add(element)
        self.source.link(convert)
        convert.link(self.volume)
        self.volume.link(sink)
        self.pipeline.set_state(Gst.State.PLAYING)

    def set_volume(self, value: float) -> None:
        self.volume.set_property("volume", value)

    def push(self, data: bytes) -> None:
        self.source.emit("push-buffer", Gst.Buffer.new_wrapped(data))

    def set_playing(self, playing: bool) -> None:
        # PAUSED corks the stream so PipeWire can suspend the audio device.
        self.pipeline.set_state(Gst.State.PLAYING if playing else Gst.State.PAUSED)

    def stop(self) -> None:
        self.pipeline.set_state(Gst.State.NULL)


class KeySoundEngine:
    """Shared, process-wide keyboard sound player."""

    _instance: "KeySoundEngine | None" = None

    @classmethod
    def shared(cls) -> "KeySoundEngine":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self) -> None:
        self.voices: list[_Voice] = []
        self.next_voice = 0
        self.bank: SoundBank | None = None
        self.source_key: str | None = None
        self.volume = 0.7
        self.release_enabled = True
        self.pressed: set[int] = set()
        self.failed = False
        self.loading_key: str | None = None
        self.last_error: str | None = None
        self.on_loaded: list[Callable[[], None]] = []
        self.paused = False
        self.last_activity = 0.0
        self.idle_source = 0

    def available(self) -> bool:
        return Gst is not None and not self.failed

    def _ensure_voices(self) -> bool:
        if self.voices or self.failed:
            return bool(self.voices)
        if Gst is None:
            self.failed = True
            return False
        Gst.init(None)
        try:
            self.voices = [_Voice() for _ in range(VOICES)]
            for voice in self.voices:
                voice.set_volume(self.volume)
        except RuntimeError as error:
            LOGGER.warning("som do teclado desativado: %s", error)
            self.failed = True
            self.voices = []
        return bool(self.voices)

    def configure(self, source: str, volume: int, release: bool) -> None:
        """Select ``red``/``brown``/``blue`` or ``pack:<name>``; loads in the background."""
        self.volume = max(0.0, min(1.0, volume / 100))
        self.release_enabled = release
        for voice in self.voices:
            voice.set_volume(self.volume)
        if source == self.source_key or source == self.loading_key:
            return
        self.loading_key = source

        def work() -> None:
            try:
                if source.startswith("pack:"):
                    bank = load_pack(packs_directory() / Path(source[5:]).name)
                else:
                    bank = synth_bank(source)
                error = None
            except (PackError, OSError) as failure:
                bank, error = None, str(failure)
            GLib.idle_add(self._loaded, source, bank, error)

        threading.Thread(target=work, name="keysound-loader", daemon=True).start()

    def _loaded(self, source: str, bank: SoundBank | None, error: str | None) -> bool:
        if source != self.loading_key:
            return False
        self.loading_key = None
        self.last_error = error
        if bank is None:
            LOGGER.warning("pacote de sons não carregado (%s): %s", source, error)
            if not source.startswith("pack:"):
                return False
            bank = synth_bank(DEFAULT_SWITCH)
        self.bank = bank
        self.source_key = source
        self._ensure_voices()  # warm up now so the first key is not delayed
        self._arm_idle_timer()
        for callback in list(self.on_loaded):
            callback()
        return False

    def _play(self, samples: Samples | None) -> None:
        if samples is None or not self._ensure_voices():
            return
        data = samples.tobytes()
        self.last_activity = time.monotonic()
        if self.paused:
            for item in self.voices:
                item.set_playing(True)
            self.paused = False
        self._arm_idle_timer()
        voice = self.voices[self.next_voice]
        self.next_voice = (self.next_voice + 1) % len(self.voices)
        voice.push(data)

    def _arm_idle_timer(self) -> None:
        if not self.idle_source and self.voices and not self.paused:
            self.last_activity = self.last_activity or time.monotonic()
            self.idle_source = GLib.timeout_add_seconds(5, self._check_idle)

    def _check_idle(self) -> bool:
        if time.monotonic() - self.last_activity < IDLE_PAUSE_SECONDS:
            return True
        for voice in self.voices:
            voice.set_playing(False)
        self.paused = True
        self.idle_source = 0
        return False

    def press(self, keycode: int, keyval: int) -> None:
        if keycode in self.pressed:
            return  # auto-repeat: real switches are silent while held
        self.pressed.add(keycode)
        if self.bank is not None:
            self._play(self.bank.pick("press", key_size(keyval), keycode))

    def release(self, keycode: int, keyval: int) -> None:
        self.pressed.discard(keycode)
        if self.bank is not None and self.release_enabled:
            self._play(self.bank.pick("release", key_size(keyval), keycode))

    def reset_keys(self) -> None:
        self.pressed.clear()

    def shutdown(self) -> None:
        if self.idle_source:
            GLib.source_remove(self.idle_source)
            self.idle_source = 0
        for voice in self.voices:
            voice.stop()
        self.voices = []
