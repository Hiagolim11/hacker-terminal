"""Run integration checks on private D-Bus/X11 surfaces with a hard deadline."""

from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import tempfile
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gui", action="store_true")
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("arguments", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if args.arguments[:1] == ["--"]:
        args.arguments = args.arguments[1:]
    with tempfile.TemporaryDirectory(prefix="ht-check-") as directory:
        root = Path(directory)
        env = dict(os.environ)
        for name in ("DBUS_SESSION_BUS_ADDRESS", "WAYLAND_DISPLAY", "DISPLAY", "GNOME_KEYRING_CONTROL"):
            env.pop(name, None)
        for kind in ("CONFIG", "CACHE", "DATA", "STATE", "RUNTIME"):
            path = root / kind.lower()
            path.mkdir(mode=0o700)
            env[f"XDG_{kind}_HOME" if kind != "RUNTIME" else "XDG_RUNTIME_DIR"] = str(path)
        env.update(HT_PRIVATE_BUS="1", HACKER_TERMINAL_AUDIO_SINK="fakesink", NO_AT_BRIDGE="1",
                   GDK_BACKEND="x11", GIO_USE_VFS="local", GTK_USE_PORTAL="0", SHELL="/bin/sh",
                   HT_GUI_REGRESSIONS="1", G_DEBUG="fatal-warnings")
        command = ["dbus-run-session", "--"]
        if args.gui:
            command += ["xvfb-run", "-a"]
        command += [sys.executable, *args.arguments]
        process = subprocess.Popen(command, env=env, start_new_session=True)
        try:
            return process.wait(timeout=args.timeout)
        except subprocess.TimeoutExpired:
            print(f"TIMEOUT ({args.timeout}s): {' '.join(args.arguments)}", file=sys.stderr)
            return 124
        finally:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()


if __name__ == "__main__":
    raise SystemExit(main())
