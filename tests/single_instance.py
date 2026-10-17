"""Plain windows share one process; later launches only pass their command line.

Run with: dbus-run-session -- env HT_PRIVATE_BUS=1 xvfb-run -a python3 tests/single_instance.py
(a private bus, so the user's running Hacker Terminal is never involved).
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
LAUNCH = [sys.executable, str(PROJECT / "hacker_terminal.py")]


def windows_of(pid: int) -> int:
    """Visible top-level windows of a process (GTK's 10x10 leader window excluded)."""
    found = subprocess.run(["xdotool", "search", "--onlyvisible", "--pid", str(pid)], capture_output=True, text=True)
    count = 0
    for window in found.stdout.split():
        geometry = subprocess.run(["xdotool", "getwindowgeometry", window], capture_output=True, text=True).stdout
        count += "Geometry: 10x10" not in geometry
    return count


def wait(condition, seconds: float = 15) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.1)
    return condition()


def app_processes() -> list[int]:
    result = subprocess.run(["pgrep", "-f", str(PROJECT / "hacker_terminal.py")], capture_output=True, text=True)
    return [int(pid) for pid in result.stdout.split() if int(pid) != os.getpid()]


def main() -> int:
    bus = os.environ.get("DBUS_SESSION_BUS_ADDRESS", "")
    if os.environ.get("HT_PRIVATE_BUS") != "1" or "/run/user/" in bus:
        print("execute: dbus-run-session -- env HT_PRIVATE_BUS=1 xvfb-run -a python3 tests/single_instance.py",
              file=sys.stderr)
        return 2
    home = Path(tempfile.mkdtemp(prefix="ht-single-"))
    (home / "projeto").mkdir()
    os.environ.update({
        "HOME": str(home), "XDG_CONFIG_HOME": str(home / "config"), "XDG_CACHE_HOME": str(home / "cache"),
        "XDG_STATE_HOME": str(home / "state"), "XDG_DATA_HOME": str(home / "data"),
        "HACKER_TERMINAL_AUDIO_SINK": "fakesink", "NO_AT_BRIDGE": "1", "SHELL": "/bin/sh",
    })
    primary = subprocess.Popen([*LAUNCH, "--no-boot"], stderr=subprocess.DEVNULL)
    try:
        assert wait(lambda: windows_of(primary.pid) == 1), "first window did not open"

        started = time.monotonic()
        second = subprocess.run([*LAUNCH, "--working-directory", "projeto"], cwd=home,
                                capture_output=True, text=True, timeout=20)
        elapsed = time.monotonic() - started
        assert second.returncode == 0, second.stderr
        assert wait(lambda: windows_of(primary.pid) == 2), "second window not in the first process"
        assert app_processes() == [primary.pid], f"extra processes: {app_processes()}"
        print(f"segunda janela no mesmo processo: ok ({elapsed * 1000:.0f} ms para o comando terminar)")

        bad = subprocess.run([*LAUNCH, "--working-directory", "nao-existe"], cwd=home,
                             capture_output=True, text=True, timeout=20)
        assert bad.returncode == 2 and "inexistente" in bad.stderr, (bad.returncode, bad.stderr)
        assert windows_of(primary.pid) == 2
        print("erro de pasta volta para quem chamou: ok")

        themed = subprocess.Popen([*LAUNCH, "--theme", "paper-light", "--no-boot"], stderr=subprocess.DEVNULL)
        try:
            assert wait(lambda: windows_of(themed.pid) == 1), "--theme did not open its own process"
            assert windows_of(primary.pid) == 2
            print("--theme abre processo próprio: ok")
        finally:
            themed.terminate()
            themed.wait(timeout=10)
    finally:
        primary.terminate()
        primary.wait(timeout=10)

    # With nothing open, a launch becomes the new shared process.
    again = subprocess.Popen([*LAUNCH, "--no-boot"], stderr=subprocess.DEVNULL)
    try:
        assert wait(lambda: windows_of(again.pid) == 1), "could not start again after closing"
        print("reabrir depois de fechar tudo: ok")
    finally:
        again.terminate()
        again.wait(timeout=10)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
