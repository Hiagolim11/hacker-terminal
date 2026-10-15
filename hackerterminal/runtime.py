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
        "sudo apt install python3-gi gir1.2-gtk-3.0 gir1.2-vte-2.91"
    ) from error

try:
    gi.require_version("Gst", "1.0")
    from gi.repository import Gst
except (ImportError, ValueError):
    Gst = None

__all__ = ["Gdk", "Gio", "GLib", "Gst", "Gtk", "Pango", "PangoCairo", "Vte"]
