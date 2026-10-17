#!/usr/bin/env python3
"""Fetch the Mechvibes sound packs and compact them into hackerterminal/soundpacks.

Run by hand when updating the bundled packs (needs git and ffmpeg with
libvorbis); the result is committed, so builds never touch the network.

The packs come from the Mechvibes repository (MIT) at a pinned commit.
They stay in the Mechvibes format, but are made smaller:

- "single" packs keep one recording with every key in it, mostly silence
  between keys. Only the parts the config uses are kept, back to back,
  and the offsets in config.json are rewritten to match.
- WAV files become Ogg Vorbis.
- Everything is mono, 48 kHz (the rate the player mixes at).
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPOSITORY = "https://github.com/hainguyents13/mechvibes.git"
COMMIT = "326252a13e7bef4f1c35d08ef0189b5af6f8ba02"
RATE = 48_000
GAP_MS = 40  # silence between kept parts, so one never bleeds into the next
QUALITY = "5"  # libvorbis -q:a; clicks stay crisp, ~80 kbit/s mono
# Clearer names where the pack's own is a placeholder.
NAMES = {"holy-pandas": "Holy Pandas"}

PROJECT = Path(__file__).resolve().parent.parent
DESTINATION = PROJECT / "hackerterminal" / "soundpacks"

LICENSE_HEADER = f"""Sound packs from Mechvibes
https://github.com/hainguyents13/mechvibes (commit {COMMIT[:12]}, src/audio)

Changes made by packaging/fetch_soundpacks.py: in packs made of one long
recording, only the parts used by config.json are kept (its offsets are
rewritten to match); those recordings and the WAV files are re-encoded as
mono 48 kHz Ogg Vorbis; MP3 files are copied as they are; some display
names are clarified. No sound was edited otherwise.

"""


def run(*command: str, **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(command, check=True, **kwargs)


def decode(path: Path) -> bytes:
    """Mono 16-bit PCM at RATE."""
    return run("ffmpeg", "-v", "error", "-i", str(path), "-f", "s16le", "-ac", "1", "-ar", str(RATE), "-",
               capture_output=True).stdout


def encode(pcm: bytes, path: Path) -> None:
    run("ffmpeg", "-v", "error", "-y", "-f", "s16le", "-ac", "1", "-ar", str(RATE), "-i", "-",
        "-c:a", "libvorbis", "-q:a", QUALITY, str(path), input=pcm)


def compact_single(source: Path, target: Path, config: dict) -> None:
    pcm = decode(source / config["sound"])
    bytes_per_ms = RATE * 2 // 1000
    kept = bytearray()
    placed: dict[tuple, list[int]] = {}
    defines = {}
    for code, span in config["defines"].items():
        if not isinstance(span, list) or len(span) != 2:
            defines[code] = span
            continue
        key = (round(span[0]), round(span[1]))
        if key not in placed:
            start, length = key
            piece = pcm[start * bytes_per_ms:(start + length) * bytes_per_ms]
            piece += bytes(length * bytes_per_ms - len(piece))  # past the end: pad, as the player would
            placed[key] = [len(kept) // bytes_per_ms, length]
            kept += piece + bytes(GAP_MS * bytes_per_ms)
        defines[code] = placed[key]
    config["defines"] = defines
    config["sound"] = "sound.ogg"
    encode(bytes(kept), target / "sound.ogg")


def copy_multi(source: Path, target: Path, config: dict) -> None:
    renamed: dict[str, str] = {}
    for item in sorted(source.rglob("*")):
        if not item.is_file() or item.name in ("config.json", "README.md", "LICENSE"):
            continue
        relative = item.relative_to(source)
        out = target / relative
        out.parent.mkdir(parents=True, exist_ok=True)
        if item.suffix.lower() == ".wav":
            out = out.with_suffix(".ogg")
            encode(decode(item), out)
            renamed[relative.as_posix()] = out.relative_to(target).as_posix()
        else:
            shutil.copy2(item, out)
    for field in ("sound", "soundup"):
        if config.get(field) in renamed:
            config[field] = renamed[config[field]]
    config["defines"] = {code: renamed.get(name, name) if isinstance(name, str) else name
                         for code, name in config["defines"].items()}
    if config.get("sound") and "{" not in config["sound"] and not (target / config["sound"]).exists():
        del config["sound"]  # names a file the pack never had


def main() -> int:
    for tool in ("git", "ffmpeg"):
        if shutil.which(tool) is None:
            print(f"falta o programa {tool}", file=sys.stderr)
            return 1
    with tempfile.TemporaryDirectory() as temporary:
        checkout = Path(temporary) / "mechvibes"
        run("git", "clone", "-q", "--filter=blob:none", "--no-checkout", REPOSITORY, str(checkout))
        run("git", "-C", str(checkout), "sparse-checkout", "set", "src/audio")
        run("git", "-C", str(checkout), "checkout", "-q", COMMIT)
        audio = checkout / "src" / "audio"
        run("git", "-C", str(checkout), "checkout", "-q", COMMIT, "--", "LICENSE")  # outside the sparse set
        upstream_license = (checkout / "LICENSE").read_text(encoding="utf-8")
        if DESTINATION.exists():
            shutil.rmtree(DESTINATION)
        DESTINATION.mkdir(parents=True)
        notices = [LICENSE_HEADER + upstream_license.strip() + "\n"]
        for source in sorted(path for path in audio.iterdir() if (path / "config.json").is_file()):
            target = DESTINATION / source.name
            target.mkdir()
            config = json.loads((source / "config.json").read_text(encoding="utf-8"))
            if config.get("key_define_type", "single") == "single":
                compact_single(source, target, config)
            else:
                copy_multi(source, target, config)
            config["name"] = NAMES.get(source.name, " ".join(str(config.get("name", source.name)).split()))
            (target / "config.json").write_text(json.dumps(config, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            if (source / "LICENSE").is_file():
                notices.append(f"\n----\nPack {source.name}:\n\n" + (source / "LICENSE").read_text(encoding="utf-8").strip() + "\n")
            size = sum(item.stat().st_size for item in target.rglob("*") if item.is_file())
            print(f"{source.name:28} {size // 1024:5} KB  {config['name']}")
        (DESTINATION / "LICENSE").write_text("".join(notices), encoding="utf-8")
    total = sum(item.stat().st_size for item in DESTINATION.rglob("*") if item.is_file())
    print(f"total: {total / 1024 / 1024:.1f} MB em {DESTINATION.relative_to(PROJECT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
