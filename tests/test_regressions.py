"""Regression coverage for session ownership, output, history and image loading."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from hackerterminal.config import Preferences
from hackerterminal.history import HistoryStore, MAX_ENTRIES
from hackerterminal.session import SessionState, SessionStore, SessionTab
from hackerterminal.terminal import TerminalPane
from hackerterminal.window.main import HackerTerminal


class OutputSafetyTests(unittest.TestCase):
    def pane(self, text="exported output"):
        terminal = SimpleNamespace(
            get_cursor_position=lambda: (0, 1), get_scrollback_lines=lambda: 1000,
            get_column_count=lambda: 80, get_text_range_format=lambda *args: (text, None),
        )
        return SimpleNamespace(terminal=terminal, html_header=lambda title: "<html><body><pre>")

    def test_export_does_not_follow_predictable_temporary_symlink(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            unrelated = root / "unrelated.txt"
            unrelated.write_text("keep me")
            unrelated.chmod(0o644)
            output = root / "output.txt"
            (root / ".output.txt.tmp").symlink_to(unrelated)
            TerminalPane.save_output(self.pane(), output)
            self.assertEqual(unrelated.read_text(), "keep me")
            self.assertEqual(unrelated.stat().st_mode & 0o777, 0o644)
            self.assertFalse(output.is_symlink())
            self.assertEqual(output.read_text(), "exported output\n")
            self.assertEqual(output.stat().st_mode & 0o777, 0o600)

    def test_failed_replace_preserves_previous_output_and_cleans_temporary(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "output.txt"
            output.write_text("previous")
            with patch.object(Path, "replace", side_effect=OSError("disk error")):
                with self.assertRaises(OSError):
                    TerminalPane.save_output(self.pane(), output)
            self.assertEqual(output.read_text(), "previous")
            self.assertEqual(list(root.iterdir()), [output])

    def test_html_and_concurrent_exports_are_complete(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "output.html"
            TerminalPane.save_output(self.pane("<pre>color</pre>"), output)
            self.assertEqual(output.read_text(), "<html><body><pre>color</pre></body></html>\n")
            output = output.with_suffix(".txt")
            errors = []
            barrier = threading.Barrier(4)
            def export(index):
                try:
                    barrier.wait(timeout=5)
                    TerminalPane.save_output(self.pane(str(index) * 10000), output)
                except Exception as error:
                    errors.append(error)
            workers = [threading.Thread(target=export, args=(i,)) for i in range(4)]
            for worker in workers:
                worker.start()
            for worker in workers:
                worker.join(10)
                self.assertFalse(worker.is_alive())
            self.assertEqual(errors, [])
            self.assertIn(output.read_text(), [str(i) * 10000 + "\n" for i in range(4)])


class TerminalFeedbackTests(unittest.TestCase):
    def test_commit_triggers_optional_cursor_pulse_and_command_activity(self):
        pane = SimpleNamespace(
            command_pending=False,
            config=SimpleNamespace(preferences=Preferences(cursor_pulse=True)),
            broadcast_peers=[], mirroring=False,
            pulse_cursor=Mock(), on_command_started=Mock(),
        )
        TerminalPane.on_commit(pane, None, "ls", 2)
        pane.pulse_cursor.assert_called_once_with()
        pane.on_command_started.assert_not_called()
        TerminalPane.on_commit(pane, None, "\r", 1)
        pane.on_command_started.assert_called_once_with(pane)


class SessionOwnershipTests(unittest.TestCase):
    def test_command_window_cannot_clear_saved_session(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = SessionStore(root / "session.json")
            state = SessionState(900, 600, 0, (SessionTab((root,), layout=0),))
            self.assertTrue(store.save(state))
            window = SimpleNamespace(config=SimpleNamespace(command=("printf", "ok")),
                                     preferences=Preferences(), session_store=store)
            HackerTerminal.save_session(window)
            self.assertEqual(store.load(), state)

    def test_all_windows_keep_layouts_and_empty_window_does_not_clear_others(self):
        from hackerterminal.session import SessionCoordinator
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = SessionStore(root / "session.json")
            first = SessionState(900, 600, 0, (SessionTab((root,), layout=0, names=("one",)),))
            second = SessionState(1000, 700, 0, (SessionTab((root, root), "vertical", ["vertical", 0, 1], ("two", "three")),))
            coordinator = SessionCoordinator(store)
            try:
                self.assertTrue(coordinator.register("first", lambda: first))
                self.assertTrue(coordinator.register("second", lambda: second))
                self.assertTrue(coordinator.save())
                self.assertEqual(store.load().tabs, first.tabs + second.tabs)
                coordinator.remove("first", save=True)
                self.assertEqual(store.load().tabs, second.tabs)
                coordinator.remove("not-registered", save=True)
                self.assertEqual(store.load().tabs, second.tabs)
                coordinator.remove("second", save=True)
                self.assertIsNone(store.load())
            finally:
                coordinator.close()

    def test_other_process_cannot_overwrite_owned_session(self):
        from hackerterminal.session import SessionCoordinator
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = SessionStore(root / "session.json")
            state = SessionState(900, 600, 0, (SessionTab((root,), layout=0),))
            owner = SessionCoordinator(store)
            try:
                owner.register("first", lambda: state)
                self.assertTrue(owner.save())
                code = """
import sys
from pathlib import Path
from hackerterminal.session import SessionCoordinator, SessionStore
c = SessionCoordinator(SessionStore(Path(sys.argv[1])))
assert not c.register('second', lambda: None)
assert not c.save()
c.close()
"""
                subprocess.run([sys.executable, "-c", code, str(store.path)], check=True, timeout=10)
                self.assertEqual(store.load(), state)
            finally:
                owner.close()
            next_owner = SessionCoordinator(store)
            try:
                self.assertTrue(next_owner.register("next", lambda: state))
            finally:
                next_owner.close()


class HistoryConcurrencyTests(unittest.TestCase):
    def test_append_is_not_lost_during_trim(self):
        import hackerterminal.history as history
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path, ready = root / "history.jsonl", root / "ready"
            row = json.dumps({"command": "old", "status": 0, "duration": 0, "finished_at": 1}) + "\n"
            path.write_text(row * (MAX_ENTRIES + 1))
            real_write = history.atomic_write_text
            children = []
            def write_after_competing_append(path, text, prefix):
                code = """
import sys
from pathlib import Path
from hackerterminal.history import HistoryStore
Path(sys.argv[2]).touch()
assert HistoryStore(Path(sys.argv[1])).add('new-during-trim', 0, 0) is not None
"""
                child = subprocess.Popen([sys.executable, "-c", code, str(path), str(ready)])
                children.append(child)
                # The old implementation lets the append finish here. With
                # locking it must wait until the replacement is complete.
                import time
                deadline = time.monotonic() + 5
                while not ready.exists() and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertTrue(ready.exists())
                try:
                    child.wait(timeout=0.25)
                except subprocess.TimeoutExpired:
                    pass
                return real_write(path, text, prefix)
            try:
                with patch.object(history, "atomic_write_text", side_effect=write_after_competing_append):
                    HistoryStore(path).trim()
                for child in children:
                    self.assertEqual(child.wait(timeout=5), 0)
                self.assertTrue(any(entry.command == "new-during-trim" for entry in HistoryStore(path).load()))
            finally:
                for child in children:
                    if child.poll() is None:
                        child.kill()
                        child.wait()

    def test_clear_and_append_use_the_same_stable_lock(self):
        import fcntl
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "history.jsonl"
            store = HistoryStore(path)
            self.assertIsNotNone(store.add("before", 0, 0))
            lock_path = path.with_suffix(path.suffix + ".lock")
            self.assertTrue(lock_path.exists())
            with lock_path.open("a") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                code = "from pathlib import Path; from hackerterminal.history import HistoryStore; import sys; assert HistoryStore(Path(sys.argv[1])).clear()"
                child = subprocess.Popen([sys.executable, "-c", code, str(path)])
                try:
                    with self.assertRaises(subprocess.TimeoutExpired):
                        child.wait(timeout=0.3)
                    self.assertTrue(path.exists())
                finally:
                    fcntl.flock(lock, fcntl.LOCK_UN)
                    child.wait(timeout=5)
            self.assertEqual(child.returncode, 0)
            self.assertFalse(path.exists())
            self.assertTrue(lock_path.exists())
            self.assertIsNotNone(store.add("after", 0, 0))
            self.assertEqual([entry.command for entry in store.load()], ["after"])


class ImageLoadingTests(unittest.TestCase):
    def test_excessive_source_pixels_are_rejected_before_any_decoder(self):
        from hackerterminal.viewer import FileViewer, GdkPixbuf
        from hackerterminal.documents import DocumentError
        with patch.object(GdkPixbuf.Pixbuf, "get_file_info", return_value=(Mock(get_name=lambda: "png"), 100000, 100000)), \
             patch.object(GdkPixbuf.PixbufAnimation, "new_from_file") as animation, \
             patch.object(GdkPixbuf.Pixbuf, "new_from_file_at_scale") as still:
            with self.assertRaises(DocumentError):
                FileViewer._read_image(SimpleNamespace(path=Path("too-large.png")))
            animation.assert_not_called()
            still.assert_not_called()

    def test_large_static_image_is_never_decoded_at_original_size(self):
        from hackerterminal.viewer import FileViewer, GdkPixbuf, MAX_DECODE_SIDE
        image = Mock()
        image.apply_embedded_orientation.return_value = image
        with patch.object(GdkPixbuf.Pixbuf, "get_file_info", return_value=(Mock(get_name=lambda: "png"), 12000, 4000)), \
             patch.object(GdkPixbuf.PixbufAnimation, "new_from_file", side_effect=AssertionError("full decode")), \
             patch.object(GdkPixbuf.Pixbuf, "new_from_file_at_scale", return_value=image) as scaled:
            result = FileViewer._read_image(SimpleNamespace(path=Path("large.png")))
        self.assertEqual(result, ("still", image, 12000, 4000))
        scaled.assert_called_once_with("large.png", MAX_DECODE_SIDE, MAX_DECODE_SIDE, True)

    def test_large_animation_is_rejected_before_decoding(self):
        from hackerterminal.viewer import FileViewer, GdkPixbuf
        from hackerterminal.documents import DocumentError
        with patch.object(GdkPixbuf.Pixbuf, "get_file_info", return_value=(Mock(get_name=lambda: "gif"), 10000, 3000)), \
             patch.object(GdkPixbuf.PixbufAnimation, "new_from_file") as decode:
            with self.assertRaises(DocumentError):
                FileViewer._read_image(SimpleNamespace(path=Path("large.gif")))
            decode.assert_not_called()

    def test_small_animation_still_plays(self):
        from hackerterminal.viewer import FileViewer, GdkPixbuf
        animation = Mock()
        animation.is_static_image.return_value = False
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "small.gif"
            path.write_bytes(b"fixture")
            with patch.object(GdkPixbuf.Pixbuf, "get_file_info", return_value=(Mock(get_name=lambda: "gif"), 40, 20)), \
                 patch.object(GdkPixbuf.PixbufAnimation, "new_from_file", return_value=animation):
                result = FileViewer._read_image(SimpleNamespace(path=path))
            self.assertEqual(result, ("animation", animation, 40, 20))


if __name__ == "__main__":
    unittest.main()
