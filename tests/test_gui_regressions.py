"""Actual GTK widgets: session isolation and bounded viewer reloads under Xvfb."""

from __future__ import annotations

import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from hackerterminal.config import AppConfig, ConfigStore, Preferences
from hackerterminal.session import SessionStore
from hackerterminal.runtime import Gtk


def wait_for(condition, seconds=5):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        while Gtk.events_pending():
            Gtk.main_iteration_do(False)
        if condition():
            return True
        time.sleep(0.01)
    return condition()


@unittest.skipUnless(os.environ.get("HT_GUI_REGRESSIONS") == "1", "run with tests/run_isolated.py --gui")
class GuiRegressionTests(unittest.TestCase):
    def test_reload_coalesces_work_and_destroy_drops_pending_reload(self):
        from hackerterminal.viewer import FileViewer, GdkPixbuf
        for destroy in (False, True):
            with self.subTest(destroy=destroy), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "image.png"
                path.touch()
                started, release = threading.Event(), threading.Event()
                calls = []
                image = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, False, 8, 20, 10)
                image.fill(0x123456FF)
                def read(_viewer):
                    calls.append(1)
                    started.set()
                    if not release.wait(5):
                        raise RuntimeError("worker was not released")
                    return "still", image, 20, 10
                with patch.object(FileViewer, "_read_image", read):
                    viewer = FileViewer(path, lambda item: item.destroy())
                    try:
                        self.assertTrue(started.wait(2))
                        for _ in range(12):
                            viewer.load()
                        time.sleep(0.1)
                        self.assertEqual(len(calls), 1, "reload starts parallel decoders")
                        if destroy:
                            viewer.destroy()
                        release.set()
                        if destroy:
                            wait_for(lambda: False, 0.2)
                            self.assertEqual(len(calls), 1)
                        else:
                            self.assertTrue(wait_for(lambda: viewer.stack.get_visible_child_name() == "image"))
                            self.assertEqual(len(calls), 2, "only the latest pending reload should run")
                            self.assertIs(viewer.source, image)
                    finally:
                        release.set()
                        viewer.destroy()
                        wait_for(lambda: False, 0.1)

    def test_real_windows_share_session_without_command_or_empty_window_deleting_it(self):
        from hackerterminal.actions import ActionStore
        from hackerterminal.app import HackerTerminalApp
        from hackerterminal.profiles import ProfileManager
        from hackerterminal.themes import ThemeManager
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first_dir, second_dir = root / "one", root / "two"
            first_dir.mkdir()
            second_dir.mkdir()
            preferences = Preferences(shell="/bin/sh")
            store = SessionStore(root / "session.json")
            themes = ThemeManager(root / "themes")
            provider = Gtk.CssProvider()
            provider.load_from_data(themes.get(preferences.theme).css())
            app = HackerTerminalApp(AppConfig(preferences, (), first_dir), ConfigStore(root / "config.ini"),
                                    ActionStore(root / "actions.ini"), store, themes,
                                    ProfileManager(root / "profiles"), provider, separate=True)
            app.register(None)
            windows = []
            try:
                first = app.open_window(AppConfig(preferences, (), first_dir), restore=False)
                second = app.open_window(AppConfig(preferences, (), second_dir), restore=False)
                transient = app.open_window(AppConfig(preferences, ("sleep", "30"), root), restore=False)
                windows += [first, second, transient]
                first.get_active_terminal().set_custom_name("api")
                second.split_active(Gtk.Orientation.VERTICAL)
                second.get_active_terminal().set_custom_name("logs")
                first.save_session()
                state = store.load()
                self.assertEqual(set(state.directories), {first_dir, second_dir})
                self.assertTrue(any(len(tab.directories) == 2 for tab in state.tabs))
                before = store.path.read_bytes()
                transient.save_session()
                self.assertEqual(store.path.read_bytes(), before)
                transient.close_page(force=True)
                self.assertEqual(store.path.read_bytes(), before)
                first.close_page(force=True)
                self.assertEqual(set(store.load().directories), {second_dir})
                second.save_session()
                restored = app.open_window(AppConfig(preferences, (), root), restore=True)
                windows.append(restored)
                self.assertEqual(len(restored.terminals()), 2)
                self.assertIn("logs", [pane.custom_name for pane in restored.terminals()])
                app.on_quit_signal()
                self.assertIsNotNone(store.load())
            finally:
                for window in windows:
                    window.closing_window = True
                    window.destroy()
                for coordinator in getattr(app, "session_coordinators", {}).values():
                    coordinator.close()


if __name__ == "__main__":
    unittest.main()
