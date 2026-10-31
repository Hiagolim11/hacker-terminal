"""Review-only transcription dialog; worker lifetime follows the dialog."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

from ..runtime import GLib, Gdk, Gtk


class SpeechDialog(Gtk.Dialog):
    def __init__(self, parent):
        super().__init__(title='Fala para texto', transient_for=parent, modal=False)
        self.set_default_size(640, 400)
        self.process = None
        self.output = None
        self.timer = 0
        self.add_button('Fechar', Gtk.ResponseType.CLOSE)
        box = self.get_content_area()
        self.status = Gtk.Label(label='Whisper large-v3 local. Primeiro uso baixa o modelo (vários GB).')
        self.status.set_line_wrap(True)
        box.pack_start(self.status, False, False, 8)
        actions = Gtk.Box(spacing=8)
        self.mic = Gtk.Button(label='Gravar 10 segundos')
        self.file = Gtk.Button(label='Abrir áudio')
        self.copy = Gtk.Button(label='Copiar texto')
        for button in (self.mic, self.file, self.copy):
            actions.pack_start(button, False, False, 0)
        box.pack_start(actions, False, False, 8)
        self.text = Gtk.TextView(wrap_mode=Gtk.WrapMode.WORD_CHAR)
        scroll = Gtk.ScrolledWindow()
        scroll.add(self.text)
        box.pack_start(scroll, True, True, 0)
        self.mic.connect('clicked', lambda _: self.start())
        self.file.connect('clicked', self.choose)
        self.copy.connect('clicked', self.copy_text)
        self.connect('response', lambda *_: self.destroy())
        self.connect('destroy', self.cleanup)
        self.show_all()

    def copy_text(self, _):
        buf = self.text.get_buffer()
        Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).set_text(buf.get_text(*buf.get_bounds(), True), -1)

    def choose(self, _):
        chooser = Gtk.FileChooserDialog(title='Selecionar áudio', transient_for=self,
                                        action=Gtk.FileChooserAction.OPEN)
        chooser.add_buttons('Cancelar', Gtk.ResponseType.CANCEL, 'Abrir', Gtk.ResponseType.OK)
        if chooser.run() == Gtk.ResponseType.OK:
            filename = chooser.get_filename()
            chooser.destroy()
            self.start(filename)
        else:
            chooser.destroy()

    def start(self, filename=None):
        if self.process is not None:
            return
        command = [sys.executable, '-m', 'hackerterminal.speech']
        if filename:
            command += ['--file', filename]
        try:
            self.output = tempfile.TemporaryFile(mode='w+b')
            self.process = subprocess.Popen(command, cwd=str(Path(__file__).resolve().parents[2]),
                                            stdout=self.output, stderr=subprocess.DEVNULL)
        except OSError as error:
            if self.output:
                self.output.close()
                self.output = None
            self.status.set_text(str(error))
            return
        self.mic.set_sensitive(False)
        self.file.set_sensitive(False)
        self.status.set_text('Transcrevendo…' if filename else 'Gravando por 10 segundos, depois transcrevendo…')
        self.timer = GLib.timeout_add(200, self.poll)

    def poll(self):
        if self.process.poll() is None:
            return True
        self.output.seek(0)
        try:
            result = json.loads(self.output.read().decode('utf-8'))
            if 'error' in result:
                self.status.set_text(result['error'])
            else:
                self.text.get_buffer().set_text(result['text'])
                self.status.set_text('Revise antes de copiar.' if result['text'] else 'Nenhuma fala detectada.')
        except (ValueError, KeyError):
            self.status.set_text('Falha no processo de transcrição. Verifique memória e dependências.')
        self.output.close()
        self.output = None
        self.process = None
        self.timer = 0
        self.mic.set_sensitive(True)
        self.file.set_sensitive(True)
        return False

    def cleanup(self, *_):
        if self.timer:
            GLib.source_remove(self.timer)
            self.timer = 0
        if self.process is not None:
            if self.process.poll() is None:
                self.process.kill()
            self.process.wait()
            self.process = None
        if self.output:
            self.output.close()
            self.output = None
