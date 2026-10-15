"""Headless GTK/VTE integration test for tabs, search and preferences."""
# pylint: disable=broad-exception-caught

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hackerterminal.audio import SoundPlayer
from hackerterminal.actions import ActionStore, QuickAction
from hackerterminal.config import AppConfig, ConfigStore, Preferences
from hackerterminal.profiles import ProfileManager
from hackerterminal.runtime import Gdk, GLib, Gtk
from hackerterminal.session import SessionState, SessionStore, SessionTab
from hackerterminal.themes import ThemeManager
from hackerterminal.ui import (
    ActionEditorDialog,
    BootScreen,
    CommandPaletteDialog,
    HackerTerminal,
    HackerTerminalApp,
    PreferencesDialog,
    ProfileEditorDialog,
    ThemeEditorDialog,
)


def main() -> int:
    temporary = tempfile.TemporaryDirectory()
    root = Path(temporary.name)
    preferences = Preferences(boot=False, effects=False, sound=False)
    store = ConfigStore(root / "config.ini")
    action_store = ActionStore(root / "actions.ini")
    session_store = SessionStore(root / "session.json")
    restored_directory = root / "restored-directory"
    restored_directory.mkdir()
    restored_split_directory = root / "restored-split-directory"
    restored_split_directory.mkdir()
    session_store.save(
        SessionState(
            900,
            600,
            1,
            (
                SessionTab((root, restored_split_directory), "vertical"),
                SessionTab((restored_directory,)),
            ),
        )
    )
    themes = ThemeManager(root / "themes")
    profiles = ProfileManager(root / "profiles")
    config = AppConfig(preferences, (), root)
    provider = Gtk.CssProvider()
    provider.load_from_data(themes.get(preferences.theme).css())
    application = HackerTerminalApp(
        config, store, action_store, session_store, themes, profiles, provider
    )
    application.register(None)
    boot = BootScreen(SoundPlayer(None, 0), lambda: False)
    boot.begin()
    boot.destroy()
    if boot.source_id:
        raise AssertionError("boot timer was not cancelled on destroy")
    window = HackerTerminal(
        application, config, store, action_store, session_store, themes, profiles, provider
    )
    result = {"ok": False}

    def finish(ok: bool) -> bool:
        result["ok"] = ok
        window.closing_window = True
        for pane in window.terminals():
            pane.prepare_close()
        window.destroy()
        Gtk.main_quit()
        return False

    def verify_search(terminal) -> bool:
        try:
            terminal.show_search()
            terminal.search_bar.entry.set_text("searchable-marker")
            if not terminal.search_bar.get_reveal_child():
                raise AssertionError("search bar did not open")
            if not terminal.search_bar.last_result:
                raise AssertionError("search did not find its result")
            window.on_terminal_title_changed(terminal, "A very long dynamic terminal title for testing")
            if "…" not in window.tab_labels[terminal].get_text():
                raise AssertionError("long tab title was not compacted")
            dialog = PreferencesDialog(window, preferences, themes, profiles)
            horizontal, vertical = dialog.scroller.get_policy()
            if horizontal != Gtk.PolicyType.NEVER or vertical != Gtk.PolicyType.AUTOMATIC:
                raise AssertionError("preferences dialog is not responsive")
            while Gtk.events_pending():
                Gtk.main_iteration_do(False)
            if dialog.scroller.get_allocated_height() < 200:
                raise AssertionError("preferences content does not fill the dialog")
            dialog.shortcuts_editor.set_binding("search", "<Primary><Shift>t")
            if "Conflito" not in dialog.shortcuts_editor.warning.get_text():
                raise AssertionError("shortcut conflict was not reported")
            dialog.shortcuts_editor.reset_all()
            dialog.shortcuts_editor.set_binding("copy", "")
            dialog.cursor_shape.set_active_id("underline")
            dialog.shell.set_text("/definitely/missing-shell")
            if "Não encontrado" not in dialog.shell_status.get_text():
                raise AssertionError("missing custom shell was not reported")
            dialog.shell.set_text("")
            editor = ThemeEditorDialog(dialog, themes, themes.get("ice-blue"))
            editor.name_entry.set_text("Gelo Escuro")
            custom = themes.save_custom(editor.build_theme())
            editor.destroy()
            if custom.builtin or custom.identifier != "gelo-escuro":
                raise AssertionError("theme editor did not create a custom theme")
            dialog.refresh_themes(custom.identifier)
            dialog.update_theme_buttons()
            if not dialog.delete_theme_button.get_sensitive():
                raise AssertionError("custom theme cannot be removed")
            themes.delete_custom(custom.identifier)
            dialog.scrollback.set_value(30_000)
            dialog.profile.set_active(2)
            dialog.refresh_themes("cyberpunk-purple")
            dialog.apply()
            dialog.destroy()
            preferences.font_size = 13
            preferences.panel_visible = False
            window.preferences_changed()
            if store.load().font_size != 13:
                raise AssertionError("preferences were not persisted")
            if store.load().scrollback_lines != 30_000:
                raise AssertionError("dialog preferences were not persisted")
            if store.load().theme != "cyberpunk-purple":
                raise AssertionError("theme preference was not persisted")
            if store.load().shortcuts != {"copy": ""}:
                raise AssertionError("shortcut changes from the dialog were not persisted")
            if store.load().cursor_shape != "underline":
                raise AssertionError("cursor preference was not persisted")
            if store.load().profile != "retro":
                raise AssertionError("profile preference was not persisted")
            if window.active_theme.identifier != "cyberpunk-purple":
                raise AssertionError("theme was not applied immediately")
            if window.action_panel is None or window.action_panel.get_visible():
                raise AssertionError("panel visibility preference was not applied")
            base_actions = len(window.action_store.load())
            editor = ProfileEditorDialog(window, profiles, None)
            editor.name_entry.set_text("Laboratório")
            editor.own_actions.set_active(True)
            editor.directory.set_filename(str(root))
            saved = editor.save(preferences, window.action_store)
            editor.destroy()
            if saved.identifier != "laboratorio" or not saved.own_actions:
                raise AssertionError("custom profile was not created")
            if Path(saved.working_directory).expanduser().resolve() != root.resolve():
                raise AssertionError("profile working directory was not stored")
            preferences.profile = saved.identifier
            window.preferences_changed()
            if window.action_store.path != profiles.actions_path(saved.identifier):
                raise AssertionError("profile actions were not activated")
            if len(window.action_panel.action_buttons) != base_actions:
                raise AssertionError("profile actions did not start as a copy of the current list")
            window.action_store.save([QuickAction("lab", "Lab", "true")])
            window.action_panel.reload_actions()
            profiles.apply("developer", preferences)
            window.preferences_changed()
            if window.action_store is not action_store or len(window.action_panel.action_buttons) != base_actions:
                raise AssertionError("switching profile did not restore the shared actions")
            prefs_dialog = PreferencesDialog(window, preferences, themes, profiles)
            prefs_dialog.refresh_profiles("laboratorio")
            prefs_dialog.update_profile_note()
            if not prefs_dialog.delete_profile_button.get_sensitive():
                raise AssertionError("custom profile cannot be removed from the dialog")
            if prefs_dialog.collect().profile != "laboratorio":
                raise AssertionError("dialog snapshot does not reflect the selected profile")
            prefs_dialog.destroy()
            profiles.delete_custom("laboratorio")
            frame = window.frame_for_pane(terminal)
            window.close_page(frame, force=True)
            if window.notebook.get_n_pages() != 2:
                raise AssertionError("tab was not closed")
            return finish(True)
        except Exception:
            traceback.print_exc()
            return finish(False)

    def verify() -> bool:
        try:
            if window.notebook.get_n_pages() != 2:
                raise AssertionError("saved tabs were not restored")
            if window.notebook.get_current_page() != 1:
                raise AssertionError("active saved tab was not restored")
            first_frame = window.notebook.get_nth_page(0)
            if not isinstance(first_frame, Gtk.Frame) or len(window.page_panes[first_frame]) != 2:
                raise AssertionError("saved split panes were not restored")
            restored_split = first_frame.get_child()
            if (
                not isinstance(restored_split, Gtk.Paned)
                or restored_split.get_orientation() != Gtk.Orientation.VERTICAL
            ):
                raise AssertionError("saved split orientation was not restored")
            if window.action_panel is None or len(window.action_panel.action_buttons) != 8:
                raise AssertionError("sidebar actions are missing")
            if not all(button.get_visible() for button in window.action_panel.action_buttons):
                raise AssertionError("sidebar actions are not visible")
            horizontal, vertical = window.action_panel.scroller.get_policy()
            if horizontal != Gtk.PolicyType.NEVER or vertical != Gtk.PolicyType.AUTOMATIC:
                raise AssertionError("sidebar does not have responsive scrolling")
            if not window.action_panel.compact:
                raise AssertionError("small window did not activate compact sidebar")
            if window.action_panel.get_size_request()[0] != 178:
                raise AssertionError("compact sidebar width was not applied")

            class NarrowConfigure:
                width = 600
                height = 420

            class WideConfigure:
                width = 800
                height = 500

            window.on_configure_event(window, NarrowConfigure())
            if window.action_panel.get_visible():
                raise AssertionError("narrow window did not auto-hide the sidebar")
            window.toggle_panel()
            if not window.action_panel.get_visible() or not preferences.panel_visible:
                raise AssertionError("sidebar peek failed or changed the saved preference")
            window.on_configure_event(window, WideConfigure())
            if not window.action_panel.get_visible():
                raise AssertionError("sidebar did not return on a wide window")
            if window.notebook.get_show_tabs() != (window.notebook.get_n_pages() > 1):
                raise AssertionError("tab strip visibility does not follow the tab count")
            editor = ActionEditorDialog(window, action_store)
            editor.actions = [QuickAction("tests", "Executar testes", "make check", True)]
            if not action_store.save(editor.actions):
                raise AssertionError("custom actions were not saved")
            editor.destroy()
            window.action_panel.reload_actions()
            if len(window.action_panel.action_buttons) != 1:
                raise AssertionError("custom actions were not reloaded")
            palette = CommandPaletteDialog(window, window.palette_items())
            palette.entry.set_text("cyberpunk")
            matches = palette.filtered_items()
            if len(matches) != 1 or matches[0][1] != "Tema":
                raise AssertionError("command palette filtering failed")
            callback = matches[0][2]
            palette.destroy()
            callback()
            if window.active_theme.identifier != "cyberpunk-purple":
                raise AssertionError("command palette action was not executed")
            inherited_directory = root / "inherited-directory"
            inherited_directory.mkdir()
            git_directory = inherited_directory / ".git"
            git_directory.mkdir()
            (git_directory / "HEAD").write_text("ref: refs/heads/daily-work\n", encoding="utf-8")
            first_terminal = window.get_active_terminal()
            if first_terminal is None:
                raise AssertionError("initial terminal is missing")
            first_terminal.current_working_directory = lambda: inherited_directory
            window.new_tab()
            if window.notebook.get_n_pages() != 3:
                raise AssertionError("second tab was not created")
            terminal = window.get_active_terminal()
            if terminal is None:
                raise AssertionError("active terminal is missing")
            if terminal.config.working_directory != inherited_directory:
                raise AssertionError("new tab did not inherit the active directory")
            window.update_status()
            if "GIT daily-work" not in window.status.get_text():
                raise AssertionError("git branch was not shown in status")
            window.split_active(Gtk.Orientation.HORIZONTAL)
            frame = window.active_frame()
            if frame is None or len(window.page_panes[frame]) != 2:
                raise AssertionError("terminal pane was not split")
            if not window.close_active_pane(force=True) or len(window.page_panes[frame]) != 1:
                raise AssertionError("split terminal pane was not closed")
            window.split_active(Gtk.Orientation.VERTICAL)
            split = frame.get_child()
            if not isinstance(split, Gtk.Paned) or split.get_orientation() != Gtk.Orientation.VERTICAL:
                raise AssertionError("vertical terminal split was not created")
            if not window.close_active_pane(force=True):
                raise AssertionError("vertical split pane was not closed")
            terminal = window.get_active_terminal()
            if terminal is None:
                raise AssertionError("surviving split pane is missing")

            class KeyEvent:
                def __init__(self, keyval, state):
                    self.keyval = keyval
                    self.state = state

            control_shift = Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.SHIFT_MASK
            pages_before = window.notebook.get_n_pages()
            if not window.on_window_key_press(window, KeyEvent(Gdk.KEY_T, control_shift)):
                raise AssertionError("Ctrl+Shift+T was not handled")
            if window.notebook.get_n_pages() != pages_before + 1:
                raise AssertionError("new-tab shortcut did not open a tab")
            if window.on_window_key_press(window, KeyEvent(Gdk.KEY_a, Gdk.ModifierType.CONTROL_MASK)):
                raise AssertionError("unbound key was consumed instead of reaching the shell")
            preferences.shortcuts = {"new_tab": "<Primary><Alt>n"}
            window.preferences_changed()
            if window.on_window_key_press(window, KeyEvent(Gdk.KEY_T, control_shift)):
                raise AssertionError("old shortcut still active after remapping")
            alt_control = Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.MOD1_MASK
            if not window.on_window_key_press(window, KeyEvent(Gdk.KEY_n, alt_control)):
                raise AssertionError("remapped shortcut was not handled")
            if "Alt" not in window.toolbar_buttons[0].get_tooltip_text():
                raise AssertionError("header tooltip does not show the remapped shortcut")
            if store.load().shortcuts != {"new_tab": "<Primary><Alt>n"}:
                raise AssertionError("shortcut override was not persisted")
            preferences.shortcuts = {}
            window.preferences_changed()
            window.close_page(window.active_frame(), force=True)
            window.close_page(window.active_frame(), force=True)

            background = window.get_active_terminal()
            window.cycle_tab(1)
            foreground = window.get_active_terminal()
            if background is foreground or background is None:
                raise AssertionError("cycle_tab did not change the active tab")
            background.on_bell(background.terminal)
            box = window.tab_labels[background].get_parent()
            if not box.get_style_context().has_class("tab-bell"):
                raise AssertionError("bell in a background tab was not indicated")
            window.cycle_tab(-1)
            window.on_pane_focus(background)
            if box.get_style_context().has_class("tab-bell"):
                raise AssertionError("bell indicator was not cleared on focus")
            window.cycle_tab(1)

            pasted = []
            pane = window.get_active_terminal()
            pane.confirm_paste = lambda text, risks: pasted.append(("asked", risks)) or False
            pane.paste_text("rm -rf build\nmake\n")
            if not pasted or pasted[0][0] != "asked":
                raise AssertionError("multi-line paste did not ask for confirmation")
            window.notebook.set_current_page(window.notebook.page_num(window.frame_for_pane(terminal)))

            focus_target = window.action_panel.action_buttons[0]
            focus_target.grab_focus()
            if terminal.terminal.has_focus():
                raise AssertionError("sidebar button did not receive focus")

            class PrimaryClickEvent:
                button = 1
                state = 0

            original_uri_at_event = terminal.uri_at_event
            terminal.uri_at_event = lambda _event: None
            try:
                if terminal.on_button_press(terminal.terminal, PrimaryClickEvent()):
                    raise AssertionError("plain primary click was consumed")
            finally:
                terminal.uri_at_event = original_uri_at_event
            if not terminal.terminal.has_focus():
                raise AssertionError("terminal did not reclaim focus after click")
            if window.get_active_terminal() is not terminal:
                raise AssertionError("clicked terminal pane did not become active")
            focus_target.grab_focus()

            class TouchBeginEvent:
                type = Gdk.EventType.TOUCH_BEGIN

            if terminal.on_touch_event(terminal.terminal, TouchBeginEvent()):
                raise AssertionError("touchpad tap was consumed")
            if not terminal.terminal.has_focus():
                raise AssertionError("terminal did not reclaim focus after touchpad tap")
            if not terminal.terminal.get_events() & Gdk.EventMask.TOUCH_MASK:
                raise AssertionError("terminal did not subscribe to native touch events")
            if not terminal.terminal.get_enable_fallback_scrolling():
                raise AssertionError("VTE fallback scrolling is disabled")
            if not terminal.terminal.get_scroll_unit_is_pixels():
                raise AssertionError("VTE does not use pixel scroll units")
            focus_target.grab_focus()

            class SmoothScrollEvent:
                direction = Gdk.ScrollDirection.SMOOTH
                state = 0

                @staticmethod
                def get_scroll_deltas():
                    return True, 0.0, 0.5

            if terminal.on_terminal_scroll(terminal.terminal, SmoothScrollEvent()):
                raise AssertionError("smooth touchpad scroll was consumed before VTE")
            if not terminal.terminal.has_focus():
                raise AssertionError("touchpad scroll did not reactivate the terminal")
            preferences.effects = True
            window.preferences_changed()
            widget = terminal.terminal
            while widget is not None and widget is not terminal:
                if isinstance(widget, Gtk.Overlay):
                    raise AssertionError("effects overlay sits above the terminal")
                widget = widget.get_parent()
            if not terminal.effects.enabled:
                raise AssertionError("visual effects were not enabled")
            if shutil.which("xdotool"):
                # Real X input: the pointer hit-test must reach VTE even with
                # effects on (an overlay window used to swallow scrolling).
                received = []
                handler = terminal.terminal.connect(
                    "scroll-event", lambda *_args: received.append(True) or False
                )
                while Gtk.events_pending():
                    Gtk.main_iteration_do(False)
                origin = terminal.terminal.get_window().get_origin()
                x_root, y_root = origin[-2], origin[-1]
                allocation = terminal.terminal.get_allocation()
                subprocess.run(
                    [
                        "xdotool",
                        "mousemove",
                        str(x_root + allocation.width // 2),
                        str(y_root + allocation.height // 2),
                        "click",
                        "4",
                    ],
                    check=False,
                )
                deadline = time.monotonic() + 2
                while not received and time.monotonic() < deadline:
                    Gtk.main_iteration_do(False)
                terminal.terminal.disconnect(handler)
                if not received:
                    raise AssertionError("scrolling over the terminal did not reach VTE with effects on")
            preferences.effects = False
            window.preferences_changed()
            focus_target.grab_focus()
            if window.on_window_focus_in(window, None):
                raise AssertionError("window activation event was consumed")
            while Gtk.events_pending():
                Gtk.main_iteration_do(False)
            if not terminal.terminal.has_focus():
                raise AssertionError("X11 window activation did not restore terminal focus")
            session_store.save(
                SessionState(
                    900,
                    600,
                    1,
                    (SessionTab((root, inherited_directory), "horizontal"),),
                )
            )
            restored = session_store.load()
            if (
                restored is None
                or restored.active_tab != 0
                or restored.tabs[0].orientation != "horizontal"
                or len(restored.directories) != 2
            ):
                raise AssertionError("session state was not restored")
            terminal.terminal.feed(b"searchable-marker\r\n")
            GLib.timeout_add(250, verify_search, terminal)
        except Exception:
            traceback.print_exc()
            return finish(False)
        return False

    GLib.timeout_add(300, lambda: window.resize(800, 500) or False)
    GLib.timeout_add(800, verify)
    window.connect("destroy", lambda *_: Gtk.main_quit() if Gtk.main_level() else None)
    window.show_all()
    Gtk.main()
    temporary.cleanup()
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
