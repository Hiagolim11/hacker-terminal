"""GTK introspection imports with a useful dependency error."""

from __future__ import annotations

try:
    import gi

    gi.require_version("Gtk", "3.0")
    gi.require_version("Gdk", "3.0")
    gi.require_version("Pango", "1.0")
    gi.require_version("PangoCairo", "1.0")
    gi.require_version("Vte", "2.91")
    from gi.repository import Gdk, Gio, GLib, Gtk, Pango, PangoCairo, Vte
except (ImportError, ValueError) as error:
    raise SystemExit(
        "Dependencias GTK/VTE ausentes. No Debian/Kali, execute: "
        "sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-3.0 gir1.2-vte-2.91"
    ) from error

try:
    gi.require_version("Atk", "1.0")
    from gi.repository import Atk
except (ImportError, ValueError):
    Atk = None

try:
    # Draw callbacks receive a cairo.Context; without python3-gi-cairo every
    # call raises TypeError, so the effects are disabled instead.
    gi.require_foreign("cairo")
    HAS_CAIRO = True
except ImportError:
    HAS_CAIRO = False

try:
    # X11 only: the server time lets the drop-down window take focus.
    gi.require_version("GdkX11", "3.0")
    from gi.repository import GdkX11
except (ImportError, ValueError):
    GdkX11 = None

_gst = False


def load_gst():
    """GStreamer, imported on first use (sound off: never, saving ~130 ms)."""
    global _gst
    if _gst is False:
        try:
            gi.require_version("Gst", "1.0")
            from gi.repository import Gst as module
        except (ImportError, ValueError):
            module = None
        _gst = module
    return _gst


__all__ = ["load_gst", "HAS_CAIRO", "Atk", "Gdk", "GdkX11", "Gio", "GLib", "Gtk", "Pango", "PangoCairo", "Vte"]
