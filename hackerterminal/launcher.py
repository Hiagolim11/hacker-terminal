"""Fast start: hand a new window to the Hacker Terminal that is already open.

All plain windows live in one process. A second launch only needs Gio
(~25 ms) to pass its command line to that process over D-Bus, instead of
loading GTK and VTE and keeping another ~150 MB process alive. Options
that change how a window looks still get a process of their own, because
the theme's CSS applies to every window of a process.
"""

from __future__ import annotations

import os
import sys

from .constants import APP_ID

# These change the look of a window, so it needs its own process.
OWN_PROCESS_OPTIONS = {
    "--separate", "--theme", "--profile", "--font", "--font-size",
    "--no-effects", "--no-sound", "--no-panel",
}
# Answered by this process itself, without opening a window.
LOCAL_OPTIONS = {
    "-h", "--help", "--version", "--diagnose", "--debug", "--dropdown",
    "--list-themes", "--list-profiles", "--list-shortcuts",
}


def separate_requested() -> bool:
    return os.environ.get("HACKER_TERMINAL_SEPARATE", "").strip().lower() in ("1", "true", "yes", "on")


def wants_running_instance(argv: list[str]) -> bool:
    if separate_requested():
        return False
    for argument in argv:
        if argument in ("-e", "--execute"):
            break  # the rest belongs to the command to run
        name = argument.split("=", 1)[0]
        if name in OWN_PROCESS_OPTIONS or name in LOCAL_OPTIONS:
            return False
    return True


def forward(argv: list[str]) -> int | None:
    """Exit code once a running instance opened the window; None to start normally."""
    if not wants_running_instance(argv):
        return None
    try:
        from gi.repository import Gio, GLib

        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        reply = bus.call_sync(
            "org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus", "NameHasOwner",
            GLib.Variant("(s)", (APP_ID,)), GLib.VariantType("(b)"), Gio.DBusCallFlags.NONE, 1000, None,
        )
        if not reply.unpack()[0]:
            return None
        application = Gio.Application(application_id=APP_ID, flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        application.register(None)
    except Exception:  # no session bus, or it refused: just start normally
        return None
    if not application.get_is_remote():
        # The open instance quit in between and this light process took its
        # name. Start over as a separate full instance; exec drops the
        # D-Bus connection, which frees the name for the next launch.
        os.environ["HACKER_TERMINAL_SEPARATE"] = "1"
        os.execv(sys.executable, [sys.executable, *sys.argv])
    return application.run([sys.argv[0], *argv])
