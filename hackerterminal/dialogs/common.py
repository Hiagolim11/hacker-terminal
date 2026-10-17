"""Small helpers shared by dialogs: messages, confirmations and form pages."""

from __future__ import annotations

import time
from pathlib import Path

from ..runtime import Gtk


def show_error(parent: Gtk.Window, title: str, message: str) -> None:
    dialog = Gtk.MessageDialog(
        transient_for=parent,
        modal=True,
        message_type=Gtk.MessageType.ERROR,
        buttons=Gtk.ButtonsType.CLOSE,
        text=title,
    )
    dialog.format_secondary_text(message)
    dialog.run()
    dialog.destroy()


def confirm(parent: Gtk.Window, title: str, message: str, action: str) -> bool:
    dialog = Gtk.MessageDialog(
        transient_for=parent,
        modal=True,
        message_type=Gtk.MessageType.QUESTION,
        buttons=Gtk.ButtonsType.NONE,
        text=title,
    )
    dialog.format_secondary_text(message)
    dialog.add_buttons("Cancelar", Gtk.ResponseType.CANCEL, action, Gtk.ResponseType.OK)
    response = dialog.run()
    dialog.destroy()
    return response == Gtk.ResponseType.OK


def mark_suggested(dialog: Gtk.Dialog) -> None:
    button = dialog.get_widget_for_response(Gtk.ResponseType.OK)
    if button is not None:
        button.get_style_context().add_class("suggested-action")


def shorten_home(path: Path) -> str:
    try:
        return "~/" + str(path.relative_to(Path.home())) if path != Path.home() else "~"
    except ValueError:
        return str(path)


def relative_time(moment: float, now: float | None = None) -> str:
    seconds = max(0, int((now if now is not None else time.time()) - moment))
    if seconds < 60:
        return "agora"
    if seconds < 3600:
        return f"há {seconds // 60} min"
    if seconds < 86400:
        return f"há {seconds // 3600} h"
    if seconds < 7 * 86400:
        return f"há {seconds // 86400} d"
    return time.strftime("%d/%m/%Y", time.localtime(moment))


class FormPage(Gtk.ScrolledWindow):
    """A scrollable two-column settings page with section headings."""

    def __init__(self) -> None:
        super().__init__()
        self.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.grid = Gtk.Grid(column_spacing=14, row_spacing=10, margin=16)
        self.add(self.grid)
        self.row = 0

    def heading(self, text: str) -> None:
        label = Gtk.Label(label=text, xalign=0)
        label.get_style_context().add_class("dialog-heading")
        self.grid.attach(label, 0, self.row, 2, 1)
        self.row += 1

    def field(self, text: str, widget: Gtk.Widget, tooltip: str | None = None) -> None:
        label = Gtk.Label(label=text, xalign=0)
        label.set_line_wrap(True)
        if tooltip:
            label.set_tooltip_text(tooltip)
            widget.set_tooltip_text(tooltip)
        self.grid.attach(label, 0, self.row, 1, 1)
        widget.set_halign(Gtk.Align.END if isinstance(widget, Gtk.Switch) else Gtk.Align.FILL)
        widget.set_valign(Gtk.Align.CENTER)
        widget.set_hexpand(not isinstance(widget, Gtk.Switch))
        self.grid.attach(widget, 1, self.row, 1, 1)
        self.row += 1

    def full(self, widget: Gtk.Widget, column: int = 0, width: int = 2) -> None:
        self.grid.attach(widget, column, self.row, width, 1)
        self.row += 1

    def hint(self, text: str, column: int = 0, width: int = 2) -> Gtk.Label:
        label = Gtk.Label(label=text, xalign=0)
        label.set_line_wrap(True)
        label.get_style_context().add_class("panel-hint")
        self.full(label, column, width)
        return label


def choice_combo(options: tuple[tuple[str, str], ...], selected: str) -> Gtk.ComboBoxText:
    combo = Gtk.ComboBoxText()
    for identifier, label in options:
        combo.append(identifier, label)
    if not combo.set_active_id(selected):
        combo.set_active(0)
    return combo
