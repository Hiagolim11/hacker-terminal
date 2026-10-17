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
from hackerterminal.keysound import KeySoundEngine
from hackerterminal.actions import DEFAULT_ACTIONS, ActionStore, QuickAction
from hackerterminal.config import AppConfig, ConfigStore, Preferences
from hackerterminal.profiles import ProfileManager
from hackerterminal.runtime import Gdk, GLib, Gtk, Vte
from hackerterminal.session import SessionState, SessionStore, SessionTab
from hackerterminal.themes import ThemeManager
from hackerterminal.ui import (
    ActionEditorDialog,
    BootScreen,
    CommandPaletteDialog,
    FieldsDialog,
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
    # Separate: never negotiate the single instance on the user's session bus.
    application = HackerTerminalApp(
        config, store, action_store, session_store, themes, profiles, provider, separate=True
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
            if not dialog.key_switch.set_active_id("blue"):
                raise AssertionError("blue switch is not offered")
            dialog.key_volume.set_value(40)
            dialog.key_release.set_active(False)
            engine = KeySoundEngine.shared()
            deadline = time.monotonic() + 5
            while (engine.source_key != "blue" or engine.loading_key) and time.monotonic() < deadline:
                Gtk.main_iteration_do(False)
            if engine.source_key != "blue" or engine.release_enabled:
                raise AssertionError("sound preview did not follow the dialog")
            if not dialog.key_status.get_text().startswith("Pronto"):
                raise AssertionError("sound status was not updated")

            class TestKey:
                hardware_keycode = 52
                keyval = Gdk.KEY_z

            dialog.on_key_test_press(dialog.key_test, TestKey())
            if 52 not in engine.pressed:
                raise AssertionError("typing in the test field did not play a sound")
            dialog.on_key_test_release(dialog.key_test, TestKey())
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
            saved_sound = store.load()
            if (saved_sound.key_switch, saved_sound.key_volume, saved_sound.key_release) != ("blue", 40, False):
                raise AssertionError("keyboard sound preferences were not persisted")
            preferences.sound = True
            window.preferences_changed()
            pane = window.get_active_terminal()
            if not pane.sound_enabled:
                raise AssertionError("keyboard sound was not enabled on the terminal")
            pane.on_terminal_key_press(pane.terminal, TestKey())
            if 52 not in engine.pressed:
                raise AssertionError("terminal key press did not reach the sound engine")
            pane.on_terminal_key_release(pane.terminal, TestKey())
            preferences.sound = False
            window.preferences_changed()
            if store.load().profile != "retro":
                raise AssertionError("profile preference was not persisted")
            if window.active_theme.identifier != "cyberpunk-purple":
                raise AssertionError("theme was not applied immediately")
            if window.action_panel is None or window.action_panel.get_visible():
                raise AssertionError("panel visibility preference was not applied")
            fixtures = Path(__file__).resolve().parent / "fixtures"
            origin = window.get_active_terminal()
            pages_before = window.notebook.get_n_pages()

            def shape(node):
                """A layout without its split ratios."""
                return [node[0], shape(node[1]), shape(node[2])] if isinstance(node, list) else node

            def wait_for(condition, seconds: float = 5.0) -> bool:
                deadline = time.monotonic() + seconds
                while not condition() and time.monotonic() < deadline:
                    Gtk.main_iteration_do(False)
                return condition()

            window.open_file(fixtures / "gradiente.png", origin)
            image_viewer = window.active_viewer()
            if image_viewer is None or window.notebook.get_n_pages() != pages_before + 1:
                raise AssertionError("image viewer tab was not opened")
            if window.notebook.page_num(image_viewer) != window.notebook.page_num(window.frame_for_pane(origin)) + 1:
                raise AssertionError("viewer tab was not placed next to its terminal")
            if not wait_for(lambda: image_viewer.stack.get_visible_child_name() == "image"):
                raise AssertionError("image did not load")
            if "64 × 40 px" not in image_viewer.info.get_text():
                raise AssertionError("image size was not reported")
            window.run_shortcut_action("zoom_in")
            if image_viewer.fit or image_viewer.zoom <= 1.0:
                raise AssertionError("zoom shortcut did not reach the image viewer")
            window.open_file(fixtures / "gradiente.png", origin)
            if len(window.viewers) != 1:
                raise AssertionError("reopening a file created a duplicate tab")
            window.open_file(fixtures / "animado.gif", origin)
            gif_viewer = window.active_viewer()
            if not wait_for(lambda: gif_viewer.animation is not None):
                raise AssertionError("animated GIF was not shown as an animation")
            window.open_file(fixtures / "vendas.xlsx", origin)
            sheet_viewer = window.active_viewer()
            if not wait_for(lambda: sheet_viewer.stack.get_visible_child_name() == "table"):
                raise AssertionError("spreadsheet did not load")
            if len(sheet_viewer.tables) != 2 or "3 planilhas" not in sheet_viewer.info.get_text():
                raise AssertionError("spreadsheet sheets were not shown")
            first_table = sheet_viewer.tables[0].get_model()
            if len(first_table) != 9 or first_table[1][1] != "Café ☕" or first_table[1][4] != "15/10/2026":
                raise AssertionError("spreadsheet cells were not displayed correctly")
            sheet_viewer.tables[0].get_selection().select_path(Gtk.TreePath.new_from_indices([1]))
            sheet_viewer.copy()
            if not wait_for(lambda: (Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).wait_for_text() or "").startswith("Café ☕\t3")):
                raise AssertionError("copying spreadsheet rows failed")
            if "VISUALIZAÇÕES" not in window.status.get_text() or "1 SESSÃO" not in window.status.get_text() and "SESSÕES" not in window.status.get_text():
                raise AssertionError("status does not count viewers separately")
            broken = root / "quebrado.xlsx"
            broken.write_bytes(b"PK\x03\x04 corrompido")
            window.open_file(broken, origin)
            broken_viewer = window.active_viewer()
            if not wait_for(lambda: broken_viewer.stack.get_visible_child_name() == "error"):
                raise AssertionError("corrupt spreadsheet did not show an error page")
            for viewer in list(window.viewers):
                window.notebook.set_current_page(window.notebook.page_num(viewer))
                if not window.close_active_pane():
                    raise AssertionError("close shortcut did not close the viewer")
            if window.viewers or window.get_active_terminal() is not origin:
                raise AssertionError("closing viewers did not return to the terminal")
            if window.notebook.get_n_pages() != pages_before:
                raise AssertionError("viewer tabs were left behind")
            if not window.open_socket or origin.extra_env.get("HACKER_TERMINAL_SOCKET") != str(window.open_socket):
                raise AssertionError("terminal panes do not receive the ht-open socket")

            # Nested splits: a 2x2 grid, collapse, limit and session round trip.
            window.new_tab()
            grid_frame = window.active_frame()
            top_left = window.get_active_terminal()
            top_right = window.split_active(Gtk.Orientation.HORIZONTAL)
            window.on_pane_focus(top_left)
            bottom_left = window.split_active(Gtk.Orientation.VERTICAL)
            window.on_pane_focus(top_right)
            bottom_right = window.split_active(Gtk.Orientation.VERTICAL)
            wait_for(lambda: False, 0.3)
            order = window.leaves(grid_frame.get_child())
            if order != [top_left, bottom_left, top_right, bottom_right]:
                raise AssertionError("2x2 grid panes are not in visual order")
            if shape(window.layout_of(grid_frame.get_child(), order)) != ["horizontal", ["vertical", 0, 1], ["vertical", 2, 3]]:
                raise AssertionError("2x2 grid layout is wrong")
            if any(pane.get_allocated_width() < 100 or pane.get_allocated_height() < 60 for pane in order):
                raise AssertionError("grid panes were not given usable space")
            # Broadcast: one action reaches every pane exactly once, no echo loop.
            window.on_pane_focus(top_left)
            window.toggle_broadcast(grid_frame)
            if grid_frame not in window.broadcast_frames or len(top_left.broadcast_peers) != 3:
                raise AssertionError("broadcast did not link the grid panes")
            if not wait_for(lambda: all(pane.shell_running for pane in order), 5):
                raise AssertionError("grid shells did not start")
            top_left.run_command("echo BROAD$((40+2))")

            def outputs(pane):
                row = pane.terminal.get_cursor_position()[1]
                text = pane.terminal.get_text_range_format(Vte.Format.TEXT, 0, 0, row, 200)[0]
                return ["BROAD42"] * text.count("BROAD42")

            if not wait_for(lambda: all(len(outputs(pane)) == 1 for pane in order), 20):
                screens = []
                for pane in order:
                    row = pane.terminal.get_cursor_position()[1]
                    text = pane.terminal.get_text_range_format(Vte.Format.TEXT, max(0, row - 6), 0, row, 200)[0]
                    screens.append((pane.shell_running, pane.child_pid, row, text[-300:]))
                raise AssertionError(f"broadcast outputs per pane: {[len(outputs(pane)) for pane in order]}; screens: {screens}")
            wait_for(lambda: False, 0.5)
            if any(len(outputs(pane)) != 1 for pane in order):
                raise AssertionError("a broadcast command ran more than once")
            window.toggle_broadcast(grid_frame)
            if any(pane.broadcast_peers for pane in order) or grid_frame.get_style_context().has_class("broadcast"):
                raise AssertionError("broadcast did not switch off")
            infos = []
            original_info = window.show_info
            window.show_info = infos.append
            if window.split_active(Gtk.Orientation.HORIZONTAL) is not None or not infos:
                raise AssertionError("a fifth pane was allowed in one tab")
            window.show_info = original_info
            session_store.clear()
            preferences.restore_session = True
            window.save_session()
            saved_grid = session_store.load()
            if saved_grid is None or not any(shape(tab.tree()) == ["horizontal", ["vertical", 0, 1], ["vertical", 2, 3]] for tab in saved_grid.tabs):
                raise AssertionError("the grid layout was not saved")
            window.on_pane_focus(bottom_left)
            window.close_active_pane(force=True)
            if shape(window.layout_of(grid_frame.get_child(), window.leaves(grid_frame.get_child()))) != ["horizontal", 0, ["vertical", 1, 2]]:
                raise AssertionError("closing a grid pane did not collapse its split")
            if window.get_active_terminal() is not top_left:
                raise AssertionError("focus did not move to the collapsed neighbour")
            replay_frame_count = window.notebook.get_n_pages()
            window.saved_session = saved_grid
            window.restore_session()
            restored_frames = [window.notebook.get_nth_page(index) for index in range(replay_frame_count, window.notebook.get_n_pages())]
            if not any(
                isinstance(frame, Gtk.Frame)
                and shape(window.layout_of(frame.get_child(), window.leaves(frame.get_child()))) == ["horizontal", ["vertical", 0, 1], ["vertical", 2, 3]]
                for frame in restored_frames
            ):
                raise AssertionError("restoring the session did not rebuild the grid")
            # Split sizes and pane names survive a save and restore.
            sized_frame = restored_frames[-1]
            window.notebook.set_current_page(window.notebook.page_num(sized_frame))
            wait_for(lambda: False, 0.8)
            outer = sized_frame.get_child()
            outer.set_position(int(outer.get_allocated_width() * 0.3))
            inner = outer.get_child2()
            inner.set_position(int(inner.get_allocated_height() * 0.7))
            sized_leaves = window.leaves(outer)
            sized_leaves[0].set_custom_name("api")
            sized_leaves[3].set_custom_name("logs\x1b")
            if not sized_leaves[0].name_bar.get_visible() or sized_leaves[1].name_bar.get_visible():
                raise AssertionError("the pane name bar did not follow the name")
            if "api" not in window.tab_labels[sized_leaves[0]].get_text() and window.get_active_terminal() is sized_leaves[0]:
                raise AssertionError("the tab did not show the pane name")
            wait_for(lambda: False, 0.3)
            window.save_session()
            sized_tab = session_store.load().tabs[-1]
            if sized_tab.names != ("api", "", "", "logs"):
                raise AssertionError(f"pane names were not saved: {sized_tab.names}")
            if abs(sized_tab.tree()[3] - 0.3) > 0.03 or abs(sized_tab.tree()[2][3] - 0.7) > 0.03:
                raise AssertionError(f"split ratios were not saved: {sized_tab.tree()}")
            before = window.notebook.get_n_pages()
            window.saved_session = SessionState(1000, 700, 0, (sized_tab,))
            window.restore_session()
            replayed = window.notebook.get_nth_page(before)
            hidden_tree = window.layout_of(replayed.get_child(), window.leaves(replayed.get_child()))
            if hidden_tree[3] != sized_tab.tree()[3]:
                raise AssertionError(f"a tab never shown lost its split sizes: {hidden_tree}")
            window.notebook.set_current_page(before)
            wait_for(lambda: False, 0.8)
            replayed_tree = window.layout_of(replayed.get_child(), window.leaves(replayed.get_child()))
            if abs(replayed_tree[3] - 0.3) > 0.03 or abs(replayed_tree[2][3] - 0.7) > 0.03:
                raise AssertionError(f"split ratios were not restored: {replayed_tree}")
            if [leaf.custom_name for leaf in window.leaves(replayed.get_child())] != ["api", "", "", "logs"]:
                raise AssertionError("pane names were not restored")
            restored_frames.append(replayed)
            for frame in restored_frames + [grid_frame]:
                if isinstance(frame, Gtk.Frame):
                    window.close_page(frame, force=True)
            window.notebook.set_current_page(window.notebook.page_num(window.frame_for_pane(terminal)))

            # SSH manager: creating connections through "Nova…" (the editor's
            # modal run() is simulated; everything else is the real path).
            import hackerterminal.ui as ssh_ui
            from unittest.mock import patch as ssh_patch
            from hackerterminal.connections import ConnectionStore

            ssh_store = ConnectionStore(root / "ssh-test.ini", root / "no-ssh-config")

            def typed(name, destination):
                def fake_run(editor):
                    editor.name_entry.set_text(name)
                    editor.destination.set_text(destination)
                    return Gtk.ResponseType.OK
                return fake_run

            manager = ssh_ui.SSHManagerDialog(window, ssh_store, themes)
            for name in ("Umbrel", "Umbrel"):
                with ssh_patch.object(ssh_ui.ConnectionEditorDialog, "run", typed(name, "umbrel@10.0.0.3")):
                    manager.add()
            created = ssh_store.load_saved()
            if [(c.identifier, c.destination) for c in created] != [("umbrel", "umbrel@10.0.0.3"), ("umbrel-2", "umbrel@10.0.0.3")]:
                raise AssertionError(f"new SSH connections were not saved: {created}")
            if manager.selected_connection().identifier != "umbrel-2":
                raise AssertionError("the new connection was not selected")
            with ssh_patch.object(ssh_ui.ConnectionEditorDialog, "run", typed("Renomeado", "umbrel@10.0.0.4")):
                manager.edit()
            edited = {c.identifier: (c.name, c.destination) for c in ssh_store.load_saved()}
            if edited != {"umbrel": ("Umbrel", "umbrel@10.0.0.3"), "umbrel-2": ("Renomeado", "umbrel@10.0.0.4")}:
                raise AssertionError(f"editing an SSH connection failed: {ssh_store.load_saved()}")
            # Saved password (fake keyring) and key setup.
            fake_keyring: dict[str, str] = {}
            keyring_patches = ssh_patch.multiple(
                ssh_ui.passwords, available=lambda: True,
                has_password=lambda ident: ident in fake_keyring,
                store=lambda ident, label, secret: fake_keyring.__setitem__(ident, secret) or True,
                forget=lambda ident: fake_keyring.pop(ident, None) is not None,
            )
            with keyring_patches:
                def typed_with_password(editor):
                    editor.password.set_text("s3nh@")
                    return Gtk.ResponseType.OK

                with ssh_patch.object(ssh_ui.ConnectionEditorDialog, "run", typed_with_password):
                    manager.edit()  # umbrel-2 is still selected
                if fake_keyring != {"umbrel-2": "s3nh@"}:
                    raise AssertionError(f"password not stored in the keyring: {fake_keyring}")
                if "salva no chaveiro" not in ssh_ui.ConnectionEditorDialog(manager, themes, manager.selected_connection()).password.get_placeholder_text():
                    raise AssertionError("the editor does not say a password is saved")
                saved_connection = manager.selected_connection()
                pages_before_key = window.notebook.get_n_pages()
                pane_with_password = window.connect_ssh(saved_connection)
                key_pane = window.setup_ssh_key(saved_connection)
                if window.notebook.get_n_pages() != pages_before_key + 2:
                    raise AssertionError("SSH tabs were not opened")
                def screen_of(pane):
                    row = pane.terminal.get_cursor_position()[1]
                    return pane.terminal.get_text_range_format(Vte.Format.TEXT, 0, 0, row + 1, 400)[0]

                for pane, expected in ((pane_with_password, "ht-askpass"), (key_pane, "ht-copy-key")):
                    if not wait_for(lambda: expected in screen_of(pane), 15):
                        raise AssertionError(f"{expected} was not typed: {screen_of(pane)[-300:]!r}")
                    if "s3nh@" in screen_of(pane):
                        raise AssertionError("the saved password appeared on screen")
                for pane in (pane_with_password, key_pane):
                    window.close_page(window.frame_for_pane(pane), force=True)
                with ssh_patch.object(ssh_ui, "confirm", lambda *a: True):
                    manager.remove()
                if fake_keyring:
                    raise AssertionError("removing the connection kept its password")
            manager.destroy()

            # SSH: a failing connection stays visible in its own themed tab.
            from hackerterminal.connections import Connection

            pages_before_ssh = window.notebook.get_n_pages()
            red = themes.get("red-alert")
            ssh_pane = window.connect_ssh(Connection("teste", "Teste local", "nobody@127.0.0.1", 1, theme="red-alert"))
            if ssh_pane is None or window.notebook.get_n_pages() != pages_before_ssh + 1:
                raise AssertionError("SSH connection did not open a tab")
            if ssh_pane.theme_override is not red or "Teste local" not in window.tab_labels[ssh_pane].get_text():
                raise AssertionError("SSH tab did not get its theme and name")

            def ssh_screen():
                row = ssh_pane.terminal.get_cursor_position()[1]
                return ssh_pane.terminal.get_text_range_format(Vte.Format.TEXT, 0, 0, row, 200)[0]

            import shutil as _shutil
            if _shutil.which("ssh"):
                if not wait_for(lambda: "port 1" in ssh_screen() or "refused" in ssh_screen().lower(), 15):
                    raise AssertionError(f"ssh error was not shown in the tab: {ssh_screen()[-300:]!r}")
                if window.frame_for_pane(ssh_pane) is None:
                    raise AssertionError("the tab closed after the connection failed")
            other = window.terminals()[0]
            window.preferences_changed()
            if ssh_pane.theme_override is not red or other.theme_override is not None:
                raise AssertionError("the SSH theme leaked to other panes or was lost")
            window.close_page(window.frame_for_pane(ssh_pane), force=True)

            from unittest.mock import patch as mock_patch

            # Command history: recorded from the shell marks, searchable,
            # and "Usar" types the command back without running it.
            from hackerterminal.history import HistoryStore
            from hackerterminal.terminal import PromptMark
            import hackerterminal.ui as history_ui

            window.history_store = HistoryStore(root / "history.jsonl")
            window.new_tab(working_directory=root)  # its own tab: the line is left typed
            history_pane = window.get_active_terminal()
            if not wait_for(lambda: history_pane.shell_running, 10):
                raise AssertionError("history tab shell did not start")
            for command, status in (("echo HISTORICO-OK", 0), ("false", 1), (" echo segredo", 0)):
                window.on_shell_command_done(history_pane, PromptMark(0, 0, 1, command, status, 0.2, True))
            recorded = window.history_store.load()
            if [e.command for e in recorded] != ["false", "echo HISTORICO-OK"]:
                raise AssertionError(f"history recorded {[e.command for e in recorded]}")
            history_dialog = history_ui.HistoryDialog(window, window.history_store, True)
            history_dialog.only_failed.set_active(True)
            if len(history_dialog.model) != 1 or history_dialog.selected_command() != "false":
                raise AssertionError("the failure filter did not work")
            history_dialog.only_failed.set_active(False)
            history_dialog.search.set_text("historico")
            wait_for(lambda: len(history_dialog.model) == 1, 3)
            if history_dialog.selected_command() != "echo HISTORICO-OK":
                raise AssertionError("search did not find the command")
            history_dialog.destroy()

            def choose_first(dialog):
                dialog.search.set_text("HISTORICO")
                wait_for(lambda: len(dialog.model) == 1, 3)
                return Gtk.ResponseType.OK

            with mock_patch.object(history_ui.HistoryDialog, "run", choose_first):
                window.show_command_history(history_pane)

            def typed_line():
                row = history_pane.terminal.get_cursor_position()[1]
                return history_pane.terminal.get_text_range_format(Vte.Format.TEXT, row, 0, row, 200)[0]

            if not wait_for(lambda: "echo HISTORICO-OK" in typed_line(), 5):
                raise AssertionError(f"the command was not typed: {typed_line()!r}")
            wait_for(lambda: False, 0.5)
            if "echo HISTORICO-OK" not in typed_line():
                raise AssertionError("the command ran instead of waiting for Enter")
            preferences.command_history = False
            window.on_shell_command_done(history_pane, PromptMark(0, 0, 1, "nao-grava", 0, 0.1, True))
            preferences.command_history = True
            if any(e.command == "nao-grava" for e in window.history_store.load()):
                raise AssertionError("history recorded with the option off")
            window.close_page(window.frame_for_pane(history_pane), force=True)

            # A second window of the same process: fresh tabs, shared ht-open
            # socket routed to the pane's own window, preferences applied to both.
            second_window = application.open_window(AppConfig(preferences, (), root), restore=False, boot=False)
            if second_window.saved_session is not None or second_window.stack.get_visible_child_name() != "terminal":
                raise AssertionError("a later window restored the session or showed the boot screen")
            if second_window.open_socket != window.open_socket:
                raise AssertionError("windows of one process should share the ht-open socket")
            routed = []
            with mock_patch.object(type(second_window), "open_file_from_pane", lambda w, path, pane_id: routed.append((w, pane_id))):
                second_pane = second_window.get_active_terminal()
                application.route_open(Path("/tmp/x.png"), second_pane.pane_id)
                application.route_open(Path("/tmp/x.png"), window.get_active_terminal().pane_id)
            if routed != [(second_window, second_pane.pane_id), (window, window.get_active_terminal().pane_id)]:
                raise AssertionError(f"ht-open went to the wrong window: {routed}")
            previous_theme = preferences.theme
            preferences.theme = "paper-light"
            window.preferences_changed()
            if second_window.active_theme.identifier != "paper-light":
                raise AssertionError("a preference change did not reach the other window")
            preferences.theme = previous_theme
            window.preferences_changed()
            second_window.closing_window = True
            for pane in second_window.terminals():
                pane.prepare_close()
            second_window.destroy()

            # Drop-down window: undecorated, top of the work area, toggles.
            dropdown = HackerTerminal(
                application, config, store, action_store, SessionStore(root / "session-dropdown.json"),
                themes, profiles, provider, dropdown=True,
            )
            dropdown.hide()
            if dropdown.get_decorated() or not dropdown.get_skip_taskbar_hint() or not dropdown.get_style_context().has_class("dropdown"):
                raise AssertionError("drop-down window is decorated or listed in the taskbar")
            dropdown.toggle_dropdown()
            area = dropdown.dropdown_area()
            if not wait_for(lambda: dropdown.get_visible() and dropdown.get_size()[0] == area[2], 5):
                raise AssertionError(f"drop-down did not span the work area: {dropdown.get_size()} vs {area}")
            preferences.dropdown_autohide = True
            own_dialog = Gtk.Dialog(transient_for=dropdown)
            own_dialog.show()
            dropdown.autohide_dropdown()
            if not dropdown.get_visible():
                raise AssertionError("drop-down hid while its own dialog was open")
            own_dialog.destroy()
            if not dropdown.is_active():
                dropdown.autohide_dropdown()
                if dropdown.get_visible():
                    raise AssertionError("drop-down did not auto-hide after losing focus")
            preferences.dropdown_autohide = False
            dropdown.closing_window = True
            for pane in dropdown.terminals():
                pane.prepare_close()
            dropdown.destroy()

            # Saving and recording the output (fed directly, no shell needed).
            recorded = window.get_active_terminal()
            recorded.terminal.feed(b"antes da gravacao\r\n")
            wait_for(lambda: False, 0.3)
            record_path = root / "gravacao.txt"
            recorded.start_recording(record_path)
            if recorded.terminal.get_scrollback_lines() < 2**31:
                raise AssertionError("recording did not lift the scrollback limit")
            window.update_recording_marks()
            if "GRAVANDO" not in window.status.get_text():
                raise AssertionError("status bar does not show the recording")
            recorded.terminal.feed(b"".join(b"gravada %d\r\n" % index for index in range(1500)))
            wait_for(lambda: False, 1.6)
            recorder = recorded.stop_recording()
            window.update_recording_marks()
            if recorded.terminal.get_scrollback_lines() != preferences.scrollback_lines:
                raise AssertionError("scrollback limit was not restored after recording")
            lines = record_path.read_text(encoding="utf-8").splitlines()
            if "antes da gravacao" in lines or lines.count("gravada 0") != 1 or "gravada 1499" not in lines:
                raise AssertionError(f"recording content is wrong: {lines[:3]} … {lines[-3:]}")
            if recorder.lost_rows or record_path.stat().st_mode & 0o777 != 0o600:
                raise AssertionError("recording lost rows or is not private")
            if "GRAVANDO" in window.status.get_text():
                raise AssertionError("status bar still shows a stopped recording")
            saved = root / "saida.html"
            if recorded.save_output(saved) < 1500 or "gravada 1499" not in saved.read_text(encoding="utf-8"):
                raise AssertionError("saving the scrollback as HTML failed")

            # Long command notifications: drive poll_command with fake /proc data.
            import hackerterminal.terminal as terminal_module

            sent = []
            application.send_notification = lambda key, note: sent.append((key, note))
            watched = window.get_active_terminal()
            running = {"child": (4242, "make")}
            original_child = terminal_module.foreground_child
            terminal_module.foreground_child = lambda _pid: running["child"]
            try:
                watched.shell_running = True
                if watched.poll_command(100.0) is not None:
                    raise AssertionError("a running command was reported as finished")
                running["child"] = None
                if watched.poll_command(130.0) != ("make", 30.0):
                    raise AssertionError("finished command was not reported with its duration")
                window.on_command_finished(watched, "make", 30.0)
                box = window.tab_labels[watched].get_parent()
                if not window.is_active() and not box.get_style_context().has_class("tab-done"):
                    raise AssertionError("finished command did not mark the tab")
                if not window.is_active() and (len(sent) != 1 or not sent[0][0].endswith(watched.pane_id)):
                    raise AssertionError("finished command did not send a notification")
                from hackerterminal.terminal import PromptMark

                failed = PromptMark(5, 2, 1, "make test", 2, 42.0, True)
                sent.clear()
                window.on_shell_command_done(watched, failed)
                if not window.is_active() and not sent:
                    raise AssertionError("shell-reported command did not notify")
                fast = PromptMark(6, 2, 1, "ls", 0, 0.2, True)
                count = len(sent)
                window.on_shell_command_done(watched, fast)
                if len(sent) != count:
                    raise AssertionError("a quick command triggered a notification")
                if not window.focus_pane(watched.pane_id) or window.get_active_terminal() is not watched:
                    raise AssertionError("notification action did not focus the pane")
                window.on_pane_focus(watched)
                if box.get_style_context().has_class("tab-done"):
                    raise AssertionError("finished-command mark was not cleared")
                preferences.notify_commands = False
                window.preferences_changed()
                if window.command_source_id:
                    raise AssertionError("command watch kept polling while disabled")
                preferences.notify_commands = True
                window.preferences_changed()
                if not window.command_source_id:
                    raise AssertionError("command watch did not restart")
            finally:
                terminal_module.foreground_child = original_child
                del application.send_notification

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
            # Saved commands with {fields}: blocked until required fields are filled.
            memory: dict[str, str] = {}
            ping = QuickAction("ping", "Ping", "ping -c {vezes=4} {host}")
            fields_dialog = FieldsDialog(window, ping, memory)
            if fields_dialog.get_widget_for_response(Gtk.ResponseType.OK).get_sensitive():
                raise AssertionError("fields dialog accepted an empty required field")
            fields_dialog.entries["host"].set_text("10.0.0.1; id")
            if fields_dialog.command() != "ping -c 4 '10.0.0.1; id'" or "'10.0.0.1; id'" not in fields_dialog.preview.get_text():
                raise AssertionError(f"fields dialog built {fields_dialog.command()!r}")
            fields_dialog.remember()
            fields_dialog.destroy()
            again = FieldsDialog(window, ping, memory)
            if again.entries["host"].get_text() != "10.0.0.1; id" or not again.get_widget_for_response(Gtk.ResponseType.OK).get_sensitive():
                raise AssertionError("fields dialog did not remember the last value")
            again.destroy()
            window.action_store.save([QuickAction("lab", "Lab", "true")])
            window.action_panel.reload_actions()
            profiles.apply("developer", preferences)
            window.preferences_changed()
            if window.action_store is not action_store or len(window.action_panel.action_buttons) != base_actions:
                raise AssertionError("switching profile did not restore the shared actions")
            # Drop-down shortcut section, against a fake xfconf (never the real one).
            import hackerterminal.ui as ui_module
            import hackerterminal.dropdown as dropdown_module
            from unittest.mock import patch as mock_patch

            fake_xfconf = {"Print": "xfce4-screenshooter"}

            def fake_binding(key):
                return fake_xfconf.get(key)

            def fake_active():
                return next((key for key, value in fake_xfconf.items() if "--dropdown" in value), None)

            def fake_bind(key, command):
                fake_xfconf[key] = command
                return True, "ok"

            def fake_unbind(key):
                fake_xfconf.pop(key, None)
                return True, "ok"

            with mock_patch.multiple(
                ui_module, xfce_available=lambda: True, xfce_binding=fake_binding,
                xfce_dropdown_key=fake_active, bind_xfce=fake_bind, unbind_xfce=fake_unbind,
            ), mock_patch.object(dropdown_module, "launch_command", lambda: "hacker-terminal --dropdown"):
                shortcut_dialog = PreferencesDialog(window, preferences, themes, profiles)
                status = shortcut_dialog.dropdown_status
                if not status.get_text().startswith("○") or not shortcut_dialog.dropdown_bind.get_sensitive():
                    raise AssertionError(f"inactive shortcut not explained: {status.get_text()!r}")
                if shortcut_dialog.dropdown_unbind.get_sensitive():
                    raise AssertionError("nothing to disable, but Desativar is enabled")
                shortcut_dialog.bind_dropdown_key()
                if not status.get_text().startswith("✓ Ativo — aperte F12") or not status.get_style_context().has_class("status-ok"):
                    raise AssertionError(f"active shortcut not shown: {status.get_text()!r}")
                shortcut_dialog.dropdown_key.set_text("Print")
                shortcut_dialog.update_dropdown_status()
                if "xfce4-screenshooter" not in status.get_text() or shortcut_dialog.dropdown_bind.get_sensitive():
                    raise AssertionError("a key used by another program was offered")
                shortcut_dialog.dropdown_key.set_text("<Super>grave")
                shortcut_dialog.bind_dropdown_key()
                if fake_active() != "<Super>grave" or "F12" in fake_xfconf:
                    raise AssertionError(f"switching keys left two bindings: {fake_xfconf}")
                shortcut_dialog.unbind_dropdown_key()
                if fake_active() is not None or not status.get_text().startswith("○"):
                    raise AssertionError("Desativar did not remove the shortcut")
                if fake_xfconf != {"Print": "xfce4-screenshooter"}:
                    raise AssertionError(f"another program's key was touched: {fake_xfconf}")
                shortcut_dialog.destroy()

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
            if window.action_panel is None or len(window.action_panel.action_buttons) != len(DEFAULT_ACTIONS):
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
            if terminal.effects.draw_handler:
                raise AssertionError("effects hook the terminal's drawing while disabled")
            from hackerterminal import effects as effects_module

            effects_module.HAS_CAIRO = False
            terminal.effects.set_enabled(True)
            effects_module.HAS_CAIRO = True
            if terminal.effects.enabled or terminal.effects.draw_handler:
                raise AssertionError("effects were enabled without cairo bindings")
            preferences.effects = True
            window.preferences_changed()
            if not terminal.effects.draw_handler:
                raise AssertionError("enabled effects are not drawn")
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
            import cairo
            import dataclasses as _dataclasses

            layer = terminal.effects
            amber = themes.get("phosphor-amber")
            layer.apply_theme(amber)
            width = terminal.terminal.get_allocated_width()
            height = terminal.terminal.get_allocated_height()
            canvas = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
            painter = cairo.Context(canvas)
            painter.set_source_rgb(0.5, 0.5, 0.5)
            painter.paint()
            layer.on_draw(terminal.terminal, painter)
            canvas.flush()
            pixels = canvas.get_data()
            stride = canvas.get_stride()

            def pixel(x, y):
                offset = y * stride + x * 4
                return pixels[offset + 2], pixels[offset + 1], pixels[offset]  # BGRA

            corner, middle = pixel(0, 0), pixel(width // 2, height // 2)
            if max(corner) > 60:
                raise AssertionError(f"tube corner was not darkened: {corner}")
            if not middle[0] > middle[2]:
                raise AssertionError(f"amber phosphor glow missing in the middle: {middle}")
            if layer.cache_key is None or layer.shade_layer is None:
                raise AssertionError("static CRT layers were not cached")
            cached = layer.shade_layer
            layer.on_draw(terminal.terminal, painter)
            if layer.shade_layer is not cached:
                raise AssertionError("CRT layers were rebuilt on every frame")
            still = _dataclasses.replace(amber, noise=0.0, flicker=0.0)
            layer.apply_theme(still)
            if layer.source_id:
                raise AssertionError("a theme without animation kept a timer running")
            layer.apply_theme(amber)
            if not layer.source_id:
                raise AssertionError("animated CRT theme did not start its timer")
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
