import unittest
from unittest.mock import Mock, patch
from hackerterminal.runtime import Gtk
from hackerterminal.dialogs.speech import SpeechDialog


class SpeechGuiTests(unittest.TestCase):
    def test_close_cancels_worker(self):
        parent = Gtk.Window()
        dialog = SpeechDialog(parent)
        worker = Mock()
        worker.poll.return_value = None
        with patch('hackerterminal.dialogs.speech.subprocess.Popen', return_value=worker):
            dialog.start()
        self.assertFalse(dialog.mic.get_sensitive())
        dialog.destroy()
        worker.kill.assert_called_once()
        worker.wait.assert_called_once()
        self.assertIsNone(dialog.output)
        parent.destroy()

    def test_result_and_retry(self):
        parent = Gtk.Window()
        dialog = SpeechDialog(parent)
        worker = Mock()
        worker.poll.return_value = 0
        with patch('hackerterminal.dialogs.speech.subprocess.Popen', return_value=worker):
            dialog.start('/tmp/audio.wav')
        dialog.output.write(b'{"text":"teste"}')
        from hackerterminal.runtime import GLib
        GLib.source_remove(dialog.timer)
        self.assertFalse(dialog.poll())
        self.assertTrue(dialog.mic.get_sensitive())
        self.assertEqual(dialog.text.get_buffer().get_char_count(), 5)
        dialog.destroy()
        parent.destroy()
