import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from hackerterminal.runtime import GLib, Gtk
from hackerterminal.dialogs.speech import SpeechController


def fake_window():
    pane = SimpleNamespace(terminal=Mock())
    return SimpleNamespace(status=Gtk.Label(), get_active_terminal=lambda: pane), pane


class SpeechControllerTests(unittest.TestCase):
    @patch.object(SpeechController, "have_deps", return_value=True)
    def test_toggle_records_then_types_into_terminal(self, _deps):
        window, pane = fake_window()
        controller = SpeechController(window)
        worker = Mock()
        worker.poll.return_value = None  # still recording
        with patch("hackerterminal.dialogs.speech.subprocess.Popen", return_value=worker):
            controller.toggle()
        self.assertEqual(controller.state, "recording")
        GLib.source_remove(controller.timer)
        controller.timer = 0

        controller.output.seek(0)
        controller.output.write(b'{"text": "ls -la"}')
        worker.poll.return_value = 0  # finished transcribing
        controller.toggle()  # second press: stop
        self.assertFalse(controller.poll())
        pane.terminal.feed_child.assert_called_once_with(b"ls -la")
        self.assertEqual(controller.state, "idle")

    @patch.object(SpeechController, "have_deps", return_value=True)
    def test_cleanup_kills_worker(self, _deps):
        window, _pane = fake_window()
        controller = SpeechController(window)
        worker = Mock()
        worker.poll.return_value = None
        with patch("hackerterminal.dialogs.speech.subprocess.Popen", return_value=worker):
            controller.toggle()
        controller.cleanup()
        worker.kill.assert_called_once()
        worker.wait.assert_called_once()
        self.assertIsNone(controller.output)
        self.assertEqual(controller.state, "idle")


if __name__ == "__main__":
    unittest.main()
