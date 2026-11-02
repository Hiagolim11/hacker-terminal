import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from hackerterminal.runtime import GLib, Gtk
from hackerterminal.dialogs.speech import SpeechController


def fake_window():
    pane = SimpleNamespace(terminal=Mock())
    return SimpleNamespace(status=Gtk.Label(), get_active_terminal=lambda: pane), pane


def drop_timers(controller):
    for attribute in ("poll_timer", "count_timer"):
        source = getattr(controller, attribute)
        if source:
            GLib.source_remove(source)
            setattr(controller, attribute, 0)


class SpeechControllerTests(unittest.TestCase):
    def test_toggle_records_then_types_into_terminal(self):
        window, pane = fake_window()
        controller = SpeechController(window)
        controller.ready = True  # skip the background dependency check
        worker = Mock()
        worker.poll.return_value = None  # still recording
        with patch("hackerterminal.dialogs.speech.subprocess.Popen", return_value=worker):
            controller.toggle()
        self.assertEqual(controller.state, "recording")
        drop_timers(controller)

        controller.output.seek(0)
        controller.output.write(b'{"text": "ls -la"}')
        worker.poll.return_value = 0  # finished transcribing
        controller.toggle()  # second press: stop early
        self.assertEqual(controller.state, "busy")
        self.assertFalse(controller.poll())
        pane.terminal.feed_child.assert_called_once_with(b"ls -la")
        self.assertEqual(controller.state, "idle")

    def test_auto_stop_when_countdown_ends(self):
        window, _pane = fake_window()
        controller = SpeechController(window)
        controller.ready = True
        worker = Mock()
        worker.poll.return_value = None
        with patch("hackerterminal.dialogs.speech.subprocess.Popen", return_value=worker):
            controller.toggle()
        drop_timers(controller)
        controller.remaining = 1
        self.assertFalse(controller._tick())  # last tick stops recording
        self.assertEqual(controller.state, "busy")
        worker.send_signal.assert_called_once()

    def test_cleanup_kills_worker(self):
        window, _pane = fake_window()
        controller = SpeechController(window)
        controller.ready = True
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
