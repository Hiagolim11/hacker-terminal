"""Unit tests for non-visual Hacker Terminal behavior."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from hackerterminal.actions import ActionStore, QuickAction
from hackerterminal.audio import make_tone
from hackerterminal.cli import build_parser
from hackerterminal.config import ConfigStore, Preferences, clamp, env_enabled
from hackerterminal.logs import setup_logging
from hackerterminal.runtime import Gdk
from hackerterminal.shortcuts import DEFAULT_SHORTCUTS, ShortcutMap, accelerator_label, accelerator_name, parse_accelerator
from hackerterminal.profiles import ProfileManager
from hackerterminal.project import detect_project_context, find_git_root, read_git_branch
from hackerterminal.session import SessionState, SessionStore, SessionTab
from hackerterminal.terminal import (
    normalize_uri_candidate,
    path_from_file_uri,
    process_has_children,
    paste_risks,
    resolve_shell,
    shell_argv,
)
from hackerterminal.themes import ThemeError, ThemeManager, _mix, load_theme, theme_to_ini
import dataclasses


class ConfigurationTests(unittest.TestCase):
    def test_round_trip_and_permissions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nested" / "config.ini"
            store = ConfigStore(path)
            expected = Preferences(
                font="JetBrainsMono Nerd Font Mono",
                font_size=14,
                boot=False,
                effects=False,
                sound=False,
                scrollback_lines=42_000,
                panel_visible=False,
            )
            self.assertTrue(store.save(expected))
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(store.load(), expected)

    def test_invalid_values_are_safely_normalized(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.ini"
            path.write_text(
                "[terminal]\nfont_size=broken\nscrollback_lines=-4\neffects=off\n",
                encoding="utf-8",
            )
            loaded = ConfigStore(path).load()
            self.assertEqual(loaded.font_size, 11)
            self.assertEqual(loaded.scrollback_lines, 1_000)
            self.assertFalse(loaded.effects)

    def test_corrupt_file_falls_back_to_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.ini"
            path.write_text("not-an-ini-file", encoding="utf-8")
            self.assertEqual(ConfigStore(path).load(), Preferences())

    def test_professional_defaults(self) -> None:
        preferences = Preferences()
        self.assertEqual(preferences.profile, "developer")
        self.assertEqual(preferences.theme, "minimal-dark")
        self.assertFalse(preferences.boot)
        self.assertFalse(preferences.effects)
        self.assertFalse(preferences.sound)

    def test_clamp_and_environment_flags(self) -> None:
        self.assertEqual(clamp(2, 6, 32), 6)
        self.assertEqual(clamp(40, 6, 32), 32)
        with patch.dict(os.environ, {"HACKER_TEST_FLAG": "off"}):
            self.assertFalse(env_enabled("HACKER_TEST_FLAG"))


class RuntimeTests(unittest.TestCase):
    def test_parser_accepts_command_and_directory(self) -> None:
        args = build_parser().parse_args(["--working-directory", "/tmp", "-e", "printf", "ok"])
        self.assertEqual(args.working_directory, "/tmp")
        self.assertEqual(args.execute, ["printf", "ok"])

    def test_shell_fallback_ignores_invalid_environment(self) -> None:
        with patch.dict(os.environ, {"SHELL": "/definitely/missing"}):
            self.assertTrue(Path(resolve_shell()).is_file())

    def test_tone_is_atomic_and_optional(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            tone = Path(directory) / "tone.wav"
            self.assertEqual(make_tone(tone, [(440, 0.01)]), tone)
            self.assertGreater(tone.stat().st_size, 44)
        self.assertIsNone(make_tone(Path("/definitely/missing/tone.wav"), [(440, 0.01)]))

    def test_invalid_process_has_no_children(self) -> None:
        self.assertFalse(process_has_children(-1))
        self.assertFalse(process_has_children(999_999_999))

    def test_current_process_has_children_when_child_is_running(self) -> None:
        import subprocess

        child = subprocess.Popen(["sleep", "2"])
        try:
            self.assertTrue(process_has_children(os.getpid()))
        finally:
            child.terminate()
            child.wait()

    def test_file_uri_directory_parsing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            expected = Path(directory)
            self.assertEqual(path_from_file_uri(expected.as_uri()), expected)
            self.assertEqual(path_from_file_uri(expected.as_uri().replace("file://", "file://localhost")), expected)
        self.assertIsNone(path_from_file_uri("https://example.com/project"))

    def test_clickable_uri_normalization(self) -> None:
        self.assertEqual(
            normalize_uri_candidate("https://example.com/docs?q=gtk)."),
            "https://example.com/docs?q=gtk",
        )
        self.assertEqual(normalize_uri_candidate("file:///tmp/project"), "file:///tmp/project")
        self.assertIsNone(normalize_uri_candidate("javascript:alert(1)"))


class ProfileTests(unittest.TestCase):
    def test_profiles_apply_complete_productivity_presets(self) -> None:
        manager = ProfileManager()
        preferences = Preferences()
        profile = manager.apply("retro", preferences)
        self.assertEqual(profile.identifier, "retro")
        self.assertEqual(preferences.theme, "matrix-green")
        self.assertTrue(preferences.boot)
        self.assertTrue(preferences.effects)
        self.assertFalse(preferences.sound)
        self.assertEqual(manager.get("missing").identifier, "developer")


class ProjectContextTests(unittest.TestCase):
    def test_git_branch_and_virtual_environment_detection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            nested = root / "src" / "module"
            nested.mkdir(parents=True)
            git = root / ".git"
            git.mkdir()
            (git / "HEAD").write_text("ref: refs/heads/feature/professional\n", encoding="utf-8")
            (root / ".venv").mkdir()
            self.assertEqual(find_git_root(nested), root)
            self.assertEqual(read_git_branch(root), "feature/professional")
            with patch.dict(os.environ, {}, clear=True):
                context = detect_project_context(nested)
            self.assertEqual(context.branch, "feature/professional")
            self.assertEqual(context.environment, ".venv")


class ActionTests(unittest.TestCase):
    def test_actions_round_trip_order_and_permissions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "actions.ini"
            store = ActionStore(path)
            actions = [
                QuickAction("tests", "Executar testes", "make check", True),
                QuickAction("server", "Servidor", "npm run dev"),
            ]
            self.assertTrue(store.save(actions))
            self.assertEqual(store.load(), actions)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_invalid_actions_fall_back_to_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "actions.ini"
            path.write_text("[action:BAD ID]\nlabel=x\ncommand=y\n", encoding="utf-8")
            actions = ActionStore(path).load()
            self.assertEqual(len(actions), 8)
            self.assertEqual(actions[0].identifier, "identity")

    def test_empty_action_list_is_supported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = ActionStore(Path(directory) / "actions.ini")
            self.assertTrue(store.save([]))
            self.assertEqual(store.load(), [])


class SessionTests(unittest.TestCase):
    def test_session_round_trip_clamps_geometry_and_permissions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            child = root / "project"
            child.mkdir()
            path = root / "session.json"
            store = SessionStore(path)
            self.assertTrue(
                store.save(
                    SessionState(
                        100,
                        9999,
                        9,
                        (SessionTab((root, child), "vertical"),),
                    )
                )
            )
            restored = store.load()
            self.assertIsNotNone(restored)
            self.assertEqual(restored.width, 720)
            self.assertEqual(restored.height, 2160)
            self.assertEqual(restored.active_tab, 0)
            self.assertEqual(restored.directories, (root, child))
            self.assertEqual(restored.tabs[0].orientation, "vertical")
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_corrupt_or_empty_session_is_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "session.json"
            path.write_text("not json", encoding="utf-8")
            store = SessionStore(path)
            self.assertIsNone(store.load())
            store.clear()
            self.assertFalse(path.exists())

    def test_version_one_session_is_migrated(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "session.json"
            path.write_text(
                f'{{"version": 1, "width": 900, "height": 600, '
                f'"active_tab": 0, "directories": ["{root}"]}}',
                encoding="utf-8",
            )
            restored = SessionStore(path).load()
            self.assertIsNotNone(restored)
            self.assertEqual(restored.tabs, (SessionTab((root,)),))

    def test_session_is_limited_to_twenty_panes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = SessionStore(root / "session.json")
            tabs = tuple(SessionTab((root, root), "horizontal") for _ in range(12))
            self.assertTrue(store.save(SessionState(900, 600, 0, tabs)))
            restored = store.load()
            self.assertIsNotNone(restored)
            self.assertEqual(len(restored.directories), 20)
            self.assertEqual(len(restored.tabs), 10)


class ThemeTests(unittest.TestCase):
    def test_color_mix_blends_and_stays_valid(self) -> None:
        self.assertEqual(_mix("#ffffff", "#000000", 0.0), "#000000")
        self.assertEqual(_mix("#ffffff", "#000000", 1.0), "#ffffff")
        self.assertEqual(_mix("#ff0000", "#0000ff", 0.5), "#800080")

    def test_every_builtin_theme_generates_css(self) -> None:
        for theme in ThemeManager(Path(tempfile.mkdtemp())).all():
            css = theme.css().decode()
            self.assertIn(theme.accent, css)
            self.assertNotIn("{", css.split("}")[-1])

    def test_builtin_themes_are_valid_and_complete(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manager = ThemeManager(Path(directory))
            self.assertEqual(len(manager.all()), 5)
            self.assertFalse(manager.errors)
            for theme in manager.all():
                self.assertEqual(len(theme.ansi), 16)
                self.assertTrue(theme.css())

    def test_import_export_and_user_override(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manager = ThemeManager(root / "user")
            source = manager.get("ice-blue").path
            self.assertIsNotNone(source)
            imported = manager.import_theme(source)
            self.assertEqual(imported.identifier, "ice-blue")
            self.assertFalse(imported.builtin)
            exported = root / "exported.ini"
            manager.export_theme("ice-blue", exported)
            self.assertEqual(load_theme(exported).identifier, "ice-blue")
            self.assertEqual(exported.stat().st_mode & 0o777, 0o600)

    def test_invalid_theme_is_rejected_without_breaking_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            user_directory = Path(directory)
            (user_directory / "broken.ini").write_text("[theme]\nid = BAD ID\n", encoding="utf-8")
            manager = ThemeManager(user_directory)
            self.assertEqual(manager.get("missing").identifier, "minimal-dark")
            self.assertEqual(len(manager.errors), 1)
            with self.assertRaises(ThemeError):
                load_theme(user_directory / "broken.ini")


if __name__ == "__main__":
    unittest.main()


class RobustConfigurationTests(unittest.TestCase):
    def test_new_preferences_and_shortcuts_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = ConfigStore(Path(directory) / "config.ini")
            expected = Preferences(
                cursor_shape="ibeam",
                cursor_blink="off",
                opacity=85,
                bold_is_bright=True,
                copy_on_select=True,
                scroll_on_output=True,
                scroll_on_keystroke=False,
                confirm_paste=False,
                bell_notify=False,
                shell="bash --norc",
                shortcuts={"new_tab": "<Primary>t"},
            )
            self.assertTrue(store.save(expected))
            self.assertEqual(store.load(), expected)

    def test_percent_signs_do_not_corrupt_the_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = ConfigStore(Path(directory) / "config.ini")
            preferences = Preferences(font="Fonte 100%", shell="env PS1=%n bash", font_size=15)
            self.assertTrue(store.save(preferences))
            loaded = store.load()
            self.assertEqual(loaded.font, "Fonte 100%")
            self.assertEqual(loaded.shell, "env PS1=%n bash")
            self.assertEqual(loaded.font_size, 15)

    def test_unrelated_sections_survive_a_save(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.ini"
            path.write_text("[extensao]\nchave = valor\n", encoding="utf-8")
            self.assertTrue(ConfigStore(path).save(Preferences()))
            self.assertIn("[extensao]", path.read_text(encoding="utf-8"))

    def test_invalid_choices_are_normalized(self) -> None:
        preferences = Preferences(cursor_shape="estrela", cursor_blink="talvez", opacity=5)
        preferences.normalize()
        self.assertEqual(preferences.cursor_shape, "block")
        self.assertEqual(preferences.cursor_blink, "system")
        self.assertEqual(preferences.opacity, 30)

    def test_log_file_is_private(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(os.environ, {"XDG_STATE_HOME": directory}):
                path = setup_logging()
            self.assertIsNotNone(path)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            setup_logging()  # idempotent: handlers are replaced, not duplicated


class ShortcutTests(unittest.TestCase):
    CTRL = Gdk.ModifierType.CONTROL_MASK
    SHIFT = Gdk.ModifierType.SHIFT_MASK

    def test_defaults_match_documented_keys(self) -> None:
        shortcuts = ShortcutMap()
        self.assertEqual(shortcuts.match(Gdk.KEY_T, self.CTRL | self.SHIFT), "new_tab")
        self.assertEqual(shortcuts.match(Gdk.KEY_t, self.CTRL), None)
        self.assertEqual(shortcuts.match(Gdk.KEY_F11, 0), "fullscreen")
        self.assertFalse(shortcuts.conflicts())

    def test_shifted_symbols_still_zoom(self) -> None:
        shortcuts = ShortcutMap()
        self.assertEqual(shortcuts.match(Gdk.KEY_plus, self.CTRL | self.SHIFT), "zoom_in")
        self.assertEqual(shortcuts.match(Gdk.KEY_equal, self.CTRL), "zoom_in")

    def test_caps_lock_is_ignored(self) -> None:
        state = self.CTRL | self.SHIFT | Gdk.ModifierType.LOCK_MASK
        self.assertEqual(ShortcutMap().match(Gdk.KEY_T, state), "new_tab")

    def test_overrides_disable_and_report_errors(self) -> None:
        shortcuts = ShortcutMap({"new_tab": "<Primary>n", "copy": "", "nope": "F1", "paste": "<Bogus>"})
        self.assertEqual(shortcuts.match(Gdk.KEY_n, self.CTRL), "new_tab")
        self.assertIsNone(shortcuts.match(Gdk.KEY_C, self.CTRL | self.SHIFT))
        self.assertEqual(shortcuts.bindings["paste"], DEFAULT_SHORTCUTS["paste"])
        self.assertEqual(len(shortcuts.errors), 2)
        self.assertEqual(shortcuts.overrides(), {"new_tab": "<Primary>n", "copy": ""})
        self.assertEqual(accelerator_label(""), "Desativado")

    def test_captured_accelerators_round_trip(self) -> None:
        name = accelerator_name(Gdk.KEY_K, self.CTRL | Gdk.ModifierType.MOD1_MASK | Gdk.ModifierType.LOCK_MASK)
        self.assertEqual(name, "<Primary><Alt>k")
        self.assertEqual(parse_accelerator(name), (Gdk.KEY_k, self.CTRL | Gdk.ModifierType.MOD1_MASK))
        self.assertEqual(accelerator_label("<Primary>KP_Add"), "Ctrl+Num +")
        self.assertIsNone(parse_accelerator("<Ctrl>NotAKey"))
        self.assertIsNone(parse_accelerator("<Nope>t"))

    def test_conflicts_are_detected(self) -> None:
        shortcuts = ShortcutMap({"search": "<Primary><Shift>t"})
        self.assertEqual(list(shortcuts.conflicts().values()), [["new_tab", "search"]])


class SafetyTests(unittest.TestCase):
    def test_paste_risks(self) -> None:
        self.assertEqual(paste_risks("ls -la"), [])
        self.assertTrue(paste_risks("ls\nrm -rf build"))
        self.assertTrue(paste_risks("make\n"))
        self.assertTrue(paste_risks("echo \x1b[31m"))
        self.assertEqual(paste_risks("a\tb"), [])

    def test_custom_shell_with_fallback(self) -> None:
        self.assertEqual(Path(shell_argv("sh -c true")[0]).name, "sh")
        self.assertEqual(shell_argv("sh -c true")[1:], ["-c", "true"])
        self.assertEqual(shell_argv("/definitely/missing", warn=False)[-1], "-l")
        self.assertEqual(shell_argv("'unterminated", warn=False)[-1], "-l")


class CustomThemeTests(unittest.TestCase):
    def test_serialized_theme_loads_back_identically(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manager = ThemeManager(Path(directory))
            source = manager.get("amber-crt")
            path = Path(directory) / "copy.ini"
            path.write_text(theme_to_ini(source), encoding="utf-8")
            loaded = load_theme(path)
            self.assertEqual(dataclasses.replace(loaded, path=None), dataclasses.replace(source, path=None, builtin=False))

    def test_save_and_delete_custom_theme(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manager = ThemeManager(Path(directory))
            identifier = manager.unique_identifier("Matrix Green")
            self.assertEqual(identifier, "matrix-green-2")
            theme = dataclasses.replace(
                manager.get("matrix-green"), identifier=identifier, name="Meu", builtin=False, path=None
            )
            saved = manager.save_custom(theme)
            self.assertFalse(saved.builtin)
            self.assertEqual((Path(directory) / f"{identifier}.ini").stat().st_mode & 0o777, 0o600)
            manager.delete_custom(identifier)
            self.assertNotIn(identifier, manager.themes)

    def test_builtin_themes_are_protected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manager = ThemeManager(Path(directory))
            with self.assertRaises(ThemeError):
                manager.save_custom(manager.get("minimal-dark"))
            with self.assertRaises(ThemeError):
                manager.delete_custom("minimal-dark")

    def test_translucent_css(self) -> None:
        css = ThemeManager(Path(tempfile.mkdtemp())).get("minimal-dark").css(0.8).decode()
        self.assertIn("rgba(", css)
