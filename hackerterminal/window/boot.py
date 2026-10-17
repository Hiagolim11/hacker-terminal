"""The opening animation."""

from __future__ import annotations

from typing import Callable

from ..audio import SoundPlayer
from ..constants import VERSION
from ..runtime import GLib, Gtk


class BootScreen(Gtk.Box):
    def __init__(self, sound: SoundPlayer, finished: Callable[[], bool]) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.get_style_context().add_class("boot")
        self.sound = sound
        self.finished = finished
        self.alive = True
        self.source_id = 0
        self.connect("destroy", self.on_destroy)
        self.lines = (
            "[  OK  ] Inicializando núcleo visual...",
            "[  OK  ] Carregando interface VTE...",
            "[  OK  ] Restaurando preferências...",
            "[  OK  ] Ativando sessões em abas...",
            "[  OK  ] Sincronizando matriz gráfica...",
            "[ READY ] Acesso autorizado.",
        )
        self.index = 0
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        card.get_style_context().add_class("boot-card")
        card.set_halign(Gtk.Align.CENTER)
        card.set_valign(Gtk.Align.CENTER)
        card.set_vexpand(True)
        logo = Gtk.Label(label="HACKER\nTERMINAL")
        logo.set_justify(Gtk.Justification.CENTER)
        logo.get_style_context().add_class("boot-logo")
        card.pack_start(logo, False, False, 0)
        subtitle = Gtk.Label(label=f"SYSTEM BOOT // LINUX // v{VERSION}")
        subtitle.get_style_context().add_class("boot-subtitle")
        card.pack_start(subtitle, False, False, 0)
        self.progress = Gtk.ProgressBar()
        self.progress.set_margin_top(10)
        card.pack_start(self.progress, False, False, 0)
        self.status = Gtk.Label(label="", xalign=0, yalign=0)
        self.status.set_line_wrap(True)
        self.status.set_size_request(-1, 7 * 18)
        self.status.get_style_context().add_class("boot-status")
        card.pack_start(self.status, False, False, 0)
        self.pack_start(card, True, True, 0)

    def begin(self) -> bool:
        if not self.alive:
            return False
        self.sound.play()
        self.source_id = GLib.timeout_add(220, self.step)
        return False

    def step(self) -> bool:
        if not self.alive:
            self.source_id = 0
            return False
        if self.index < len(self.lines):
            text = self.status.get_text()
            self.status.set_text(f"{text}\n{self.lines[self.index]}" if text else self.lines[self.index])
            self.index += 1
            self.progress.set_fraction(self.index / len(self.lines))
            return True
        self.source_id = GLib.timeout_add(240, self.complete)
        return False

    def complete(self) -> bool:
        self.source_id = 0
        return self.finished() if self.alive else False

    def on_destroy(self, _widget) -> None:
        self.alive = False
        if self.source_id:
            GLib.source_remove(self.source_id)
            self.source_id = 0
