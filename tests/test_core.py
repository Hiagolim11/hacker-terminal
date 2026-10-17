"""Unit tests for non-visual Hacker Terminal behavior."""

from __future__ import annotations

import shlex
import subprocess
import sys
import array
import json
import os
import tempfile
import time
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

from hackerterminal.actions import ActionStore, QuickAction
from hackerterminal.audio import make_tone
from hackerterminal.cli import build_parser
from hackerterminal.config import ConfigStore, Preferences, clamp, env_enabled
from hackerterminal.logs import setup_logging
from hackerterminal.runtime import Gdk
from hackerterminal.shortcuts import DEFAULT_SHORTCUTS, ShortcutMap, accelerator_label, accelerator_name, parse_accelerator
from hackerterminal.profiles import ProfileError, ProfileManager, load_profile, profile_from_preferences, profile_to_ini, slugify
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
            import socket

            local = expected.as_uri().replace("file://", f"file://{socket.gethostname()}")
            self.assertEqual(path_from_file_uri(local), expected)
            remote = expected.as_uri().replace("file://", "file://servidor-remoto")
            self.assertIsNone(path_from_file_uri(remote))  # an SSH session's directory
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
            self.assertEqual(len(actions), 10)
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
            self.assertEqual(len(manager.all()), 16)  # 5 classic + 8 phosphor + red alert, light, high contrast
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


class CustomProfileTests(unittest.TestCase):
    def manager(self, directory: str) -> ProfileManager:
        return ProfileManager(Path(directory) / "profiles")

    def test_capture_save_reload_and_apply(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manager = self.manager(directory)
            current = Preferences(
                theme="amber-crt", font="Hack", font_size=14, shell="bash --norc",
                cursor_shape="ibeam", opacity=80, effects=True, panel_visible=False,
            )
            identifier = manager.unique_identifier("Pentest Lab!")
            self.assertEqual(identifier, "pentest-lab")
            profile = profile_from_preferences(identifier, "Pentest Lab!", "Testes", current, directory, True)
            saved = manager.save_custom(profile)
            self.assertFalse(saved.builtin)
            path = Path(directory) / "profiles" / "pentest-lab.ini"
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            reloaded = self.manager(directory).get("pentest-lab")
            self.assertEqual(reloaded.shell, "bash --norc")
            self.assertEqual(reloaded.opacity, 80)

            target = Preferences()
            manager.apply("pentest-lab", target)
            self.assertEqual(
                (target.profile, target.theme, target.font, target.font_size, target.shell),
                ("pentest-lab", "amber-crt", "Hack", 14, "bash --norc"),
            )
            self.assertEqual((target.cursor_shape, target.opacity, target.effects), ("ibeam", 80, True))
            self.assertFalse(target.panel_visible)
            self.assertEqual(manager.working_directory("pentest-lab"), Path(directory).resolve())
            self.assertEqual(manager.actions_path("pentest-lab"), path.with_suffix(".actions"))
            self.assertIsNone(manager.actions_path("developer"))

    def test_builtin_profiles_keep_personal_settings(self) -> None:
        manager = ProfileManager(Path(tempfile.mkdtemp()))
        preferences = Preferences(font="Hack", shell="fish", cursor_shape="underline", opacity=70)
        manager.apply("focus", preferences)
        self.assertEqual((preferences.font, preferences.shell), ("Hack", "fish"))
        self.assertEqual((preferences.cursor_shape, preferences.opacity), ("underline", 70))

    def test_custom_profile_without_font_or_shell_resets_them(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manager = self.manager(directory)
            manager.save_custom(profile_from_preferences("plain", "Plain", "", Preferences()))
            preferences = Preferences(font="Hack", shell="fish")
            manager.apply("plain", preferences)
            self.assertIsNone(preferences.font)
            self.assertEqual(preferences.shell, "")

    def test_invalid_and_conflicting_files_are_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory) / "profiles"
            folder.mkdir()
            (folder / "broken.ini").write_text("[profile]\nid = Bad Id\nname = x\n", encoding="utf-8")
            (folder / "cursor.ini").write_text("[profile]\nid = c\nname = c\ncursor_shape = star\n", encoding="utf-8")
            (folder / "dev.ini").write_text("[profile]\nid = developer\nname = Hijack\n", encoding="utf-8")
            manager = ProfileManager(folder)
            self.assertEqual(len(manager.errors), 3)
            self.assertTrue(manager.get("developer").builtin)
            self.assertEqual(len(manager.all()), 4)

    def test_builtins_are_protected_and_delete_removes_actions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manager = self.manager(directory)
            with self.assertRaises(ProfileError):
                manager.save_custom(manager.get("developer"))
            with self.assertRaises(ProfileError):
                manager.delete_custom("retro")
            manager.save_custom(profile_from_preferences("lab", "Lab", "", Preferences(), "~", True))
            actions = manager.actions_path("lab")
            self.assertTrue(ActionStore(actions).save([QuickAction("x", "X", "true")]))
            manager.delete_custom("lab")
            self.assertFalse(actions.exists())
            self.assertNotIn("lab", manager.profiles)

    def test_accented_names_become_readable_identifiers(self) -> None:
        self.assertEqual(slugify("Laboratório Ágil"), "laboratorio-agil")
        manager = ProfileManager(Path(tempfile.mkdtemp()))
        self.assertEqual(manager.unique_identifier("日本"), "perfil")
        self.assertEqual(manager.unique_identifier("Focus"), "focus-2")

    def test_missing_directory_falls_back_to_home(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manager = self.manager(directory)
            manager.save_custom(profile_from_preferences("gone", "Gone", "", Preferences(), "/definitely/missing"))
            self.assertEqual(manager.working_directory("gone"), Path.home())

    def test_ini_round_trip_with_special_characters(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            profile = profile_from_preferences(
                "pct", "Uso 100%", "linha\nquebrada", Preferences(shell="env X=%y bash")
            )
            path = Path(directory) / "pct.ini"
            path.write_text(profile_to_ini(profile), encoding="utf-8")
            loaded = load_profile(path)
            self.assertEqual((loaded.name, loaded.description, loaded.shell), ("Uso 100%", "linha quebrada", "env X=%y bash"))


def write_wav(path: Path, samples: list[int], rate: int = 48_000) -> None:
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(array.array("h", samples).tobytes())


class KeySoundTests(unittest.TestCase):
    def setUp(self) -> None:
        self.cache = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {"XDG_CACHE_HOME": self.cache.name, "HACKER_TERMINAL_AUDIO_SINK": "fakesink"})
        self.env.start()

    def tearDown(self) -> None:
        self.env.stop()
        self.cache.cleanup()

    def test_synthesis_is_deterministic_and_bounded(self) -> None:
        from hackerterminal import keysound
        first = keysound.synthesize("blue", "press", "normal", 3)
        self.assertEqual(first, keysound.synthesize("blue", "press", "normal", 3))
        self.assertNotEqual(first, keysound.synthesize("blue", "press", "normal", 4))
        self.assertEqual(len(first), int(keysound.RATE * 0.075))
        self.assertLessEqual(max(abs(value) for value in first), 32_767)
        self.assertGreater(len(keysound.synthesize("red", "press", "space", 1)), len(first))

    def test_switches_have_distinct_character(self) -> None:
        import math
        from hackerterminal import keysound

        def mean_frequency(samples):
            energy = sum(value * value for value in samples)
            slope = sum((samples[i] - samples[i - 1]) ** 2 for i in range(1, len(samples)))
            return math.sqrt(slope / energy) * keysound.RATE / (2 * math.pi)

        def average(switch, kind="press", size="normal"):
            return sum(mean_frequency(keysound.synthesize(switch, kind, size, seed)) for seed in range(3)) / 3

        self.assertGreater(average("blue"), 1.8 * average("red"))  # the click jacket is bright
        self.assertGreater(average("red", "release"), average("red"))  # top-out is higher than bottom-out
        self.assertLess(average("red", size="space"), average("red"))  # big keys are deeper

        brown = keysound.synthesize("brown", "press", "normal", 5)
        peak = max(abs(value) for value in brown)
        onset = next(index for index, value in enumerate(brown) if abs(value) > 0.5 * peak)
        self.assertGreater(onset / keysound.RATE * 1000, 4)  # tactile tick, then bottom-out

    def test_synth_bank_cache_round_trip(self) -> None:
        from hackerterminal import keysound
        built = keysound.synth_bank("red")
        cached = keysound.synth_bank("red")
        self.assertEqual(built.sounds, cached.sounds)
        self.assertEqual(len(cached.sounds), len(keysound.KINDS) * len(keysound.SIZES))
        (Path(self.cache.name) / "hacker-terminal" / "keysounds" / f"red-v{keysound.SYNTH_VERSION}.pcm").write_bytes(b"junk")
        self.assertEqual(keysound.synth_bank("red").sounds, built.sounds)  # corrupt cache is rebuilt

    def test_key_sizes(self) -> None:
        from hackerterminal.keysound import key_size
        self.assertEqual(key_size(Gdk.KEY_space), "space")
        self.assertEqual(key_size(Gdk.KEY_Return), "enter")
        self.assertEqual(key_size(Gdk.KEY_BackSpace), "large")
        self.assertEqual(key_size(Gdk.KEY_a), "normal")

    def test_folder_pack(self) -> None:
        from hackerterminal import keysound
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            write_wav(folder / "press1.wav", [1000] * 480)
            write_wav(folder / "press2.wav", [2000] * 480, rate=44_100)
            write_wav(folder / "space-press.wav", [3000] * 480)
            write_wav(folder / "release.wav", [4000] * 480)
            (folder / "notes.txt").write_text("ignored", encoding="utf-8")
            bank = keysound.load_pack(folder)
            self.assertEqual(len(bank.sounds[("press", "normal")]), 2)
            self.assertAlmostEqual(len(bank.sounds[("press", "normal")][1]), 522, delta=4)  # resampled to 48 kHz
            self.assertIn(("press", "space"), bank.sounds)
            self.assertIsNotNone(bank.pick("release", "enter", 40))  # falls back to the normal size
            empty = folder / "empty"
            empty.mkdir()
            for invalid in (empty, folder / "missing"):
                with self.assertRaises(keysound.PackError):
                    keysound.load_pack(invalid)

    def test_mechvibes_single_and_multi_packs(self) -> None:
        from hackerterminal import keysound
        with tempfile.TemporaryDirectory() as directory:
            single = Path(directory) / "single"
            single.mkdir()
            write_wav(single / "sound.wav", [100] * 4800 + [200] * 4800)
            (single / "config.json").write_text(json.dumps({
                "name": "Cherry  MX Blue", "key_define_type": "single", "sound": "sound.wav",
                "defines": {"30": [0, 100], "57": [100, 100], "61000": [0, 50], "bad": [0, 1]},
            }), encoding="utf-8")
            bank = keysound.load_pack(single)
            self.assertEqual(bank.name, "Cherry MX Blue")
            self.assertEqual(bank.pick("press", "normal", 30 + 8)[0], 100)  # KEY_A
            self.assertEqual(bank.pick("press", "space", 57 + 8)[0], 200)   # KEY_SPACE
            self.assertEqual(len(bank.pick("press", "normal", 103 + 8)), 2400)  # KEY_UP via uiohook code
            self.assertIsNone(bank.pick("release", "normal", 38))

            multi = Path(directory) / "multi"
            multi.mkdir()
            write_wav(multi / "a.wav", [7] * 100)
            (multi / "config.json").write_text(json.dumps({
                "key_define_type": "multi", "defines": {"30": "a.wav", "31": None},
            }), encoding="utf-8")
            self.assertEqual(keysound.load_pack(multi).pick("press", "normal", 38)[0], 7)

            escape = Path(directory) / "escape"
            escape.mkdir()
            (escape / "config.json").write_text(json.dumps({
                "key_define_type": "multi", "defines": {"30": "../single/sound.wav"},
            }), encoding="utf-8")
            with self.assertRaises(keysound.PackError):
                keysound.load_pack(escape)

    def test_engine_keeps_playing_after_silence(self) -> None:
        """Regression: each output stream used to play once and then go mute."""
        from hackerterminal.keysound import KeySoundEngine
        from hackerterminal.runtime import GLib, load_gst
        Gst = load_gst()
        engine = KeySoundEngine()
        loop = GLib.MainLoop()
        engine.on_loaded.append(loop.quit)
        guard = GLib.timeout_add_seconds(10, loop.quit)
        engine.configure("blue", 50, release=False)
        loop.run()
        GLib.source_remove(guard)
        self.assertIsNotNone(engine.bank)
        self.assertIsNotNone(engine.mixer)  # warmed up before the first key
        blocks: list[bool] = []

        def probe(_pad, info):
            buffer = info.get_buffer()
            ok, mapped = buffer.map(Gst.MapFlags.READ)
            if ok:
                blocks.append(any(mapped.data))
                buffer.unmap(mapped)
            return Gst.PadProbeReturn.OK

        engine.mixer.sink.get_static_pad("sink").add_probe(Gst.PadProbeType.BUFFER, probe)

        def wait(milliseconds: int) -> None:
            GLib.timeout_add(milliseconds, loop.quit)
            loop.run()

        def sounding_runs() -> int:
            runs, previous = 0, False
            for loud in blocks:
                runs += loud and not previous
                previous = loud
            return runs

        def wait_for_runs(expected: int) -> None:
            context = GLib.MainContext.default()
            deadline = time.monotonic() + 2
            while sounding_runs() < expected and time.monotonic() < deadline:
                context.iteration(False)
                time.sleep(0.002)
            wait(120)  # let the sound finish before the next key

        wait(100)
        for keycode in (38, 39, 40):
            engine.press(keycode, Gdk.KEY_a)
            engine.press(keycode, Gdk.KEY_a)  # auto-repeat stays silent
            engine.release(keycode, Gdk.KEY_a)  # release sound disabled
            wait_for_runs(keycode - 37)
            wait(150)  # long silence between keys
        self.assertEqual(sounding_runs(), 3)
        self.assertEqual(engine.mixer.volume.get_property("volume"), 0.5)

        engine.last_activity -= 100
        engine._check_idle()
        self.assertTrue(engine.paused)
        engine.press(41, Gdk.KEY_d)
        self.assertFalse(engine.paused)
        wait_for_runs(4)
        self.assertEqual(sounding_runs(), 4)  # resumes after the idle pause
        engine.shutdown()

    def test_mixer_overlaps_and_clips_safely(self) -> None:
        from hackerterminal import keysound
        from hackerterminal.runtime import load_gst
        Gst = load_gst()
        Gst.init(None)
        mixer = keysound._Mixer()
        try:
            loud = array.array("h", [30_000] * (keysound.CHUNK + 10))
            mixer.add(loud)
            mixer.add(loud)
            block = array.array("h")
            block.frombytes(mixer.next_block())
            self.assertEqual(block[0], 32_767)  # clipped, not wrapped around
            tail = array.array("h")
            tail.frombytes(mixer.next_block())
            self.assertEqual(len(tail), keysound.CHUNK)
            self.assertEqual(tail[9], 32_767)
            self.assertEqual(tail[10], 0)
            self.assertFalse(mixer.busy())
            self.assertEqual(mixer.next_block(), keysound.SILENCE)
        finally:
            mixer.stop()

    def test_broken_pack_falls_back_to_synth(self) -> None:
        from hackerterminal.keysound import KeySoundEngine
        from hackerterminal.runtime import GLib
        engine = KeySoundEngine()
        loop = GLib.MainLoop()
        engine.on_loaded.append(loop.quit)
        guard = GLib.timeout_add_seconds(10, loop.quit)
        engine.configure("pack:does-not-exist", 70, True)
        loop.run()
        GLib.source_remove(guard)
        self.assertIsNotNone(engine.last_error)
        self.assertIsNotNone(engine.bank)
        engine.shutdown()

    def test_key_sound_preferences_round_trip_and_validation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = ConfigStore(Path(directory) / "config.ini")
            store.save(Preferences(key_switch="pack:cherry-mx-blue", key_volume=35, key_release=False))
            loaded = store.load()
            self.assertEqual((loaded.key_switch, loaded.key_volume, loaded.key_release), ("pack:cherry-mx-blue", 35, False))
        for bad in ("purple", "pack:", "pack:../../etc"):
            preferences = Preferences(key_switch=bad, key_volume=500)
            preferences.normalize()
            self.assertEqual((preferences.key_switch, preferences.key_volume), ("brown", 100))


FIXTURES = Path(__file__).resolve().parent / "fixtures"


def make_xlsx(path: Path, sheet_xml: str, shared: list[str] | None = None, with_dimension: str | None = None) -> None:
    """A minimal hand-written workbook, independent of any spreadsheet library."""
    import zipfile

    dimension = f'<dimension ref="{with_dimension}"/>' if with_dimension else ""
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("xl/workbook.xml", (
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            '<sheets><sheet name="Dados" sheetId="1" r:id="rId1"/></sheets></workbook>'
        ))
        archive.writestr("xl/_rels/workbook.xml.rels", (
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Target="worksheets/sheet1.xml" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet"/></Relationships>'
        ))
        if shared is not None:
            items = "".join(f"<si><t>{text}</t></si>" for text in shared)
            archive.writestr("xl/sharedStrings.xml", f'<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">{items}</sst>')
        archive.writestr("xl/worksheets/sheet1.xml", (
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            f"{dimension}<sheetData>{sheet_xml}</sheetData></worksheet>"
        ))


class DocumentTests(unittest.TestCase):
    def test_real_libreoffice_xlsx_and_ods(self) -> None:
        from hackerterminal.documents import load_spreadsheet

        expected = [
            ["Produto", "Qtd", "Preço", "Data", "Hora", "Pago", "Obs"],
            ["Café ☕", "3", "12.5", "15/10/2026", "14:30:00", "VERDADEIRO", "ção, ñ, 日本"],
            ["Pão", "10", "0.75", "02/01/2026 08:05", "07:00:00", "FALSO"],
        ]
        for name, decimal in (("vendas.xlsx", "."), ("vendas.ods", ",")):
            sheets = load_spreadsheet(FIXTURES / name)
            self.assertEqual([sheet.name for sheet in sheets], ["Vendas", "Resumo", "Vazia"], name)
            vendas = sheets[0]
            rows = [[cell.replace(decimal, ".") if cell.replace(decimal, "").isdigit() else cell for cell in row]
                    for row in vendas.rows[:3]]
            self.assertEqual(rows, expected, name)
            self.assertEqual(vendas.rows[3][6], "linha\nquebrada")
            self.assertEqual(vendas.rows[5], ["Total", "15"])  # cached formula result
            self.assertEqual(vendas.rows[7], ["mesclada"])
            self.assertEqual(vendas.rows[8][9], "célula distante")
            self.assertEqual((vendas.total_rows, vendas.total_columns, vendas.truncated), (9, 10, False))
            self.assertEqual(sheets[1].rows[1][1].replace(",", "."), "6.08")  # cross-sheet formula
            self.assertEqual((sheets[2].rows, sheets[2].total_rows), ([], 0))

    def test_csv_dialects_and_encodings(self) -> None:
        from hackerterminal.documents import load_spreadsheet

        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            (folder / "ponto.csv").write_text("nome;valor\nAção;1,5\n", encoding="utf-8")
            (folder / "windows.csv").write_bytes("nome,cidade\nJoão,São Paulo\n".encode("cp1252"))
            (folder / "dados.tsv").write_text("a\tb\n1\t2\n", encoding="utf-8")
            (folder / "aspas.csv").write_text('id,obs\n1,"vírgula, e\nlinha"\n', encoding="utf-8")
            self.assertEqual(load_spreadsheet(folder / "ponto.csv")[0].rows, [["nome", "valor"], ["Ação", "1,5"]])
            self.assertEqual(load_spreadsheet(folder / "windows.csv")[0].rows[1], ["João", "São Paulo"])
            self.assertEqual(load_spreadsheet(folder / "dados.tsv")[0].rows, [["a", "b"], ["1", "2"]])
            self.assertEqual(load_spreadsheet(folder / "aspas.csv")[0].rows[1], ["1", "vírgula, e\nlinha"])

    def test_large_csv_is_streamed_and_estimated(self) -> None:
        from hackerterminal import documents

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "grande.csv"
            path.write_text("".join(f"{index},x\n" for index in range(documents.MAX_ROWS + 250)), encoding="utf-8")
            sheet = documents.load_spreadsheet(path)[0]
            self.assertEqual(len(sheet.rows), documents.MAX_ROWS)
            self.assertEqual((sheet.total_prefix, sheet.total_rows), ("≈", documents.MAX_ROWS + 250))
            self.assertTrue(sheet.truncated)

    def test_xlsx_edge_cases(self) -> None:
        from hackerterminal import documents

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "mao.xlsx"
            make_xlsx(path, (
                '<row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1"><f>SUM(1,2)</f></c>'
                '<c r="C1" t="inlineStr"><is><t>em linha</t></is></c><c r="D1" t="b"><v>1</v></c></row>'
                '<row r="3"><c r="AB3"><v>2.50</v></c></row>'
            ), shared=["olá"])
            sheet = documents.load_spreadsheet(path)[0]
            self.assertEqual(sheet.rows[0], ["olá", "=SUM(1,2)", "em linha", "VERDADEIRO"])
            self.assertEqual(sheet.rows[2][27], "2.5")
            self.assertEqual(documents.column_name(27), "AB")

            rows = "".join(f'<row r="{index}"><c r="A{index}"><v>{index}</v></c></row>' for index in range(1, 301))
            make_xlsx(path, rows)
            with patch.object(documents, "MAX_ROWS", 50), patch.object(documents, "MAX_SCAN_ROWS", 120):
                sheet = documents.load_spreadsheet(path)[0]
            self.assertEqual((len(sheet.rows), sheet.total_prefix), (50, ">"))  # no <dimension>: bounded scan
            make_xlsx(path, rows, with_dimension="A1:A300")
            with patch.object(documents, "MAX_ROWS", 50):
                sheet = documents.load_spreadsheet(path)[0]
            self.assertEqual((len(sheet.rows), sheet.total_rows, sheet.total_prefix), (50, 300, ""))

    def test_hostile_or_broken_files_fail_cleanly(self) -> None:
        from hackerterminal import documents

        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            (folder / "quebrado.xlsx").write_bytes(b"PK\x03\x04 nada aqui")
            (folder / "texto.ods").write_text("não é zip", encoding="utf-8")
            (folder / "planilha.xls").write_bytes(b"\xd0\xcf\x11\xe0")
            make_xlsx(folder / "bomba.xlsx", "<row r='1'><c r='A1'><v>1</v></c></row>")
            for name in ("quebrado.xlsx", "texto.ods", "planilha.xls"):
                with self.assertRaises(documents.DocumentError, msg=name):
                    documents.load_spreadsheet(folder / name)
            with patch.object(documents, "MAX_MEMBER_BYTES", 10):
                with self.assertRaises(documents.DocumentError):
                    documents.load_spreadsheet(folder / "bomba.xlsx")
            with patch.object(documents, "MAX_FILE_BYTES", 10):
                with self.assertRaises(documents.DocumentError):
                    documents.load_spreadsheet(FIXTURES / "vendas.ods")

    def test_kinds_and_terminal_file_matching(self) -> None:
        import re as regex

        from hackerterminal.documents import kind_of
        from hackerterminal.terminal import FILE_PATTERN, resolve_viewable

        self.assertEqual(kind_of(Path("a.PNG")), "image")
        self.assertEqual(kind_of(Path("a.ods")), "spreadsheet")
        self.assertIsNone(kind_of(Path("a.txt")))
        pattern = regex.compile(FILE_PATTERN.replace("(?i:", "(?:"), regex.I)
        found = lambda text: [match.group(0) for match in pattern.finditer(text)]  # noqa: E731
        self.assertEqual(found("foto.png  dados.CSV  notas.txt"), ["foto.png", "dados.CSV"])
        self.assertEqual(found("~/docs/plan.ods)"), ["~/docs/plan.ods"])
        self.assertEqual(found("https://site/x.png arquivo.pngx"), [])
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            (folder / "imagem.png").write_bytes(b"x")
            (folder / "texto.txt").write_text("x")
            self.assertEqual(resolve_viewable("imagem.png", folder), (folder / "imagem.png").resolve())
            self.assertIsNone(resolve_viewable("texto.txt", folder))
            self.assertIsNone(resolve_viewable("sumiu.png", folder))


class OpenServerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runtime = tempfile.TemporaryDirectory(prefix="ht-")
        self.env = patch.dict(os.environ, {"XDG_RUNTIME_DIR": self.runtime.name})
        self.env.start()

    def tearDown(self) -> None:
        self.env.stop()
        self.runtime.cleanup()

    def run_client(self, socket_path: Path | None, *names: str, cwd: Path | None = None):
        import subprocess

        environment = {key: value for key, value in os.environ.items() if key != "HACKER_TERMINAL_SOCKET"}
        if socket_path is not None:
            environment["HACKER_TERMINAL_SOCKET"] = str(socket_path)
            environment["HACKER_TERMINAL_PANE"] = "pane-1"
        client = Path(__file__).resolve().parents[1] / "bin" / "ht-open"
        return subprocess.run([str(client), *names], env=environment, cwd=cwd, capture_output=True, text=True, timeout=10)

    def test_client_server_round_trip(self) -> None:
        from hackerterminal.openserver import OpenServer
        from hackerterminal.runtime import GLib

        received = []
        server = OpenServer(lambda path, pane: received.append((path, pane)))
        socket_path = server.start()
        try:
            self.assertIsNotNone(socket_path)
            self.assertEqual(socket_path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(socket_path.parent.stat().st_mode & 0o777, 0o700)
            result = self.run_client(socket_path, "gradiente.png", "faltando.csv", cwd=FIXTURES)
            self.assertEqual(result.returncode, 1)
            self.assertIn("arquivo não encontrado: faltando.csv", result.stderr)
            context = GLib.MainContext.default()
            deadline = time.monotonic() + 5
            while not received and time.monotonic() < deadline:
                context.iteration(False)
            self.assertEqual(received, [((FIXTURES / "gradiente.png").resolve(), "pane-1")])
        finally:
            server.stop()
        self.assertFalse(socket_path.exists())

    def test_client_outside_the_terminal_and_bad_requests(self) -> None:
        import json
        import socket as sockets

        from hackerterminal.openserver import OpenServer

        result = self.run_client(None, "x.png")
        self.assertEqual(result.returncode, 2)
        self.assertIn("dentro do Hacker Terminal", result.stderr)
        server = OpenServer(lambda *_args: None)
        socket_path = server.start()
        try:
            for payload, error in (
                (b"lixo\n", "pedido inválido"),
                (json.dumps({"action": "exec", "path": "/bin/sh"}).encode() + b"\n", "ação desconhecida"),
                (json.dumps({"action": "open", "path": "relativo.png"}).encode() + b"\n", "absoluto"),
                (json.dumps({"action": "open", "path": "/definitely/missing.png"}).encode() + b"\n", "não encontrado"),
            ):
                with sockets.socket(sockets.AF_UNIX) as client:
                    client.connect(str(socket_path))
                    client.sendall(payload)
                    reply = json.loads(client.recv(4096).decode())
                self.assertFalse(reply["ok"])
                self.assertIn(error, reply["error"])
        finally:
            server.stop()

    def test_unsafe_directory_and_stale_sockets(self) -> None:
        from hackerterminal.constants import APP_NAME
        from hackerterminal.openserver import OpenServer

        directory = Path(self.runtime.name) / APP_NAME
        directory.mkdir(mode=0o700)
        stale = directory / "999999999.sock"
        stale.write_text("")
        server = OpenServer(lambda *_args: None)
        socket_path = server.start()
        self.assertFalse(stale.exists())  # left by a dead process
        server.stop()
        directory.chmod(0o777)  # writable by others: must not be used
        try:
            socket_path = server.start()
            self.assertIsNotNone(socket_path)
            self.assertNotEqual(socket_path.parent, directory)  # fell back to a private directory
        finally:
            server.stop()
            directory.chmod(0o700)


class PhosphorThemeTests(unittest.TestCase):
    PHOSPHOR = (
        "phosphor-amber", "phosphor-green", "phosphor-scanlines", "phosphor-vintage",
        "phosphor-1977", "phosphor-mainframe", "phosphor-dos", "phosphor-futuristic",
    )

    def manager(self) -> ThemeManager:
        return ThemeManager(Path(tempfile.mkdtemp()))

    def test_all_phosphor_themes_load_with_crt_settings(self) -> None:
        manager = self.manager()
        self.assertFalse(manager.errors)
        for identifier in self.PHOSPHOR:
            theme = manager.get(identifier)
            self.assertEqual(theme.identifier, identifier)
            self.assertFalse(theme.rain, identifier)
            self.assertGreater(theme.curvature, 0, identifier)
            self.assertGreater(theme.glow, 0, identifier)
            # Inverse video selection, like a real tube.
            self.assertEqual(theme.selection_foreground, theme.terminal_background, identifier)

    def test_monochrome_tubes_use_a_single_hue(self) -> None:
        import colorsys

        manager = self.manager()
        for identifier in set(self.PHOSPHOR) - {"phosphor-dos"}:
            theme = manager.get(identifier)
            hues = set()
            for color in theme.ansi[1:7] + theme.ansi[9:14]:
                red, green, blue = (int(color[index:index + 2], 16) / 255 for index in (1, 3, 5))
                hues.add(colorsys.rgb_to_hsv(red, green, blue)[0])
            # Integer rounding of scaled colors moves the hue by a hair only.
            self.assertLess(max(hues) - min(hues), 0.02, f"{identifier}: {sorted(hues)}")

    def test_existing_themes_are_unchanged(self) -> None:
        theme = self.manager().get("matrix-green")
        self.assertTrue(theme.rain)
        self.assertEqual((theme.glow, theme.vignette, theme.noise, theme.flicker, theme.curvature), (0, 0, 0, 0, 0))
        self.assertIsNone(theme.font)
        self.assertEqual(theme.tube_padding, 2)

    def test_tube_corners_never_cover_text(self) -> None:
        import math

        for identifier in self.PHOSPHOR:
            theme = self.manager().get(identifier)
            padding, radius = theme.tube_padding, theme.tube_radius
            # The first glyph's corner (padding, padding) must lie inside the corner arc.
            self.assertLessEqual(math.hypot(radius - padding, radius - padding), radius, identifier)
            self.assertIn(f"padding: {padding}px", theme.css().decode())

    def test_crt_values_round_trip_and_are_validated(self) -> None:
        manager = self.manager()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "copy.ini"
            source = manager.get("phosphor-vintage")
            path.write_text(theme_to_ini(source), encoding="utf-8")
            loaded = load_theme(path)
            self.assertEqual(dataclasses.replace(loaded, path=None), dataclasses.replace(source, path=None, builtin=False))
            text = theme_to_ini(source)
            for broken in (text.replace("noise = 0.4", "noise = 1.5"), text.replace("rain = false", "rain = talvez"),
                           text.replace("glow = 0.5", "glow = muito")):
                path.write_text(broken, encoding="utf-8")
                with self.assertRaises(ThemeError):
                    load_theme(path)

    def test_crt_profile(self) -> None:
        preferences = Preferences()
        ProfileManager().apply("crt", preferences)
        self.assertEqual((preferences.theme, preferences.effects, preferences.panel_visible), ("phosphor-amber", True, False))


class LongCommandTests(unittest.TestCase):
    def test_duration_format(self) -> None:
        from hackerterminal.terminal import format_duration

        self.assertEqual(format_duration(9.6), "10 s")
        self.assertEqual(format_duration(125), "2 min 05 s")
        self.assertEqual(format_duration(3 * 3600 + 7 * 60), "3 h 07 min")

    def test_foreground_child_reads_proc(self) -> None:
        import subprocess

        from hackerterminal.terminal import foreground_child

        child = subprocess.Popen(["sleep", "2"])
        try:
            found = foreground_child(os.getpid())
            self.assertEqual(found, (child.pid, "sleep"))
        finally:
            child.terminate()
            child.wait()
        self.assertIsNone(foreground_child(-1))
        self.assertIsNone(foreground_child(999_999_999))

    def test_preferences_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = ConfigStore(Path(directory) / "config.ini")
            store.save(Preferences(notify_commands=False, notify_after=1))
            loaded = store.load()
            self.assertEqual((loaded.notify_commands, loaded.notify_after), (False, 3))  # clamped


class SplitLayoutSessionTests(unittest.TestCase):
    def test_layout_validation(self) -> None:
        from hackerterminal.session import valid_layout

        self.assertTrue(valid_layout(0, 1))
        self.assertTrue(valid_layout(["horizontal", ["vertical", 0, 1], ["vertical", 2, 3]], 4))
        for broken in (["diagonal", 0, 1], ["horizontal", 0, 0], ["horizontal", 0], ["vertical", 0, True], "0"):
            self.assertFalse(valid_layout(broken, 2), broken)
        self.assertFalse(valid_layout(["horizontal", 0, 1], 3))  # a leaf is missing

    def test_grid_round_trip_and_hostile_files(self) -> None:
        import json

        with tempfile.TemporaryDirectory() as directory:
            folders = [Path(directory) / name for name in "abcd"]
            for folder in folders:
                folder.mkdir()
            store = SessionStore(Path(directory) / "session.json")
            grid = ["horizontal", ["vertical", 0, 1], ["vertical", 2, 3]]
            store.save(SessionState(900, 600, 0, (SessionTab(tuple(folders), None, grid),)))
            loaded = store.load()
            self.assertEqual((loaded.tabs[0].directories, loaded.tabs[0].tree()), (tuple(folders), grid))
            self.assertEqual(json.loads(store.path.read_text())["version"], 3)

            def load_with(tab: dict):
                store.path.write_text(json.dumps({"version": 3, "tabs": [tab]}), encoding="utf-8")
                return store.load().tabs[0]

            tampered = load_with({"directories": [str(f) for f in folders], "layout": ["horizontal", 0, 0]})
            self.assertEqual((len(tampered.directories), tampered.tree()), (1, 0))
            folders[2].rmdir()
            missing = load_with({"directories": [str(f) for f in folders], "layout": grid})
            self.assertEqual((missing.directories, missing.tree()), ((folders[0],), 0))
            too_many = load_with({"directories": [str(folders[0])] * 9, "layout": 0})
            self.assertLessEqual(len(too_many.directories), 4)

    def test_split_ratios_and_pane_names(self) -> None:
        import json
        from hackerterminal.session import clean_name, valid_layout

        self.assertTrue(valid_layout(["horizontal", 0, ["vertical", 1, 2, 0.25], 0.7], 3))
        for ratio in (0.0, 1.5, True, "0.5", None):
            self.assertFalse(valid_layout(["horizontal", 0, 1, ratio], 2), ratio)
        self.assertEqual(clean_name("  web\x1b[31m\n  logs  "), "web [31m logs")
        self.assertEqual(len(clean_name("x" * 200)), 40)
        self.assertEqual(clean_name(42), "")
        with tempfile.TemporaryDirectory() as directory:
            folders = [Path(directory) / name for name in "abc"]
            for folder in folders:
                folder.mkdir()
            store = SessionStore(Path(directory) / "session.json")
            tree = ["horizontal", 0, ["vertical", 1, 2, 0.25], 0.7]
            store.save(SessionState(900, 600, 0, (SessionTab(tuple(folders), None, tree, ("api", "", "logs")),)))
            loaded = store.load().tabs[0]
            self.assertEqual((loaded.tree(), loaded.names), (tree, ("api", "", "logs")))
            payload = json.loads(store.path.read_text())
            payload["tabs"][0]["names"] = ["a\u0007b", 5]
            store.path.write_text(json.dumps(payload), encoding="utf-8")
            self.assertEqual(store.load().tabs[0].names, ("a b", ""))
            store.save(SessionState(900, 600, 0, (SessionTab((folders[0],)),)))
            self.assertNotIn("names", json.loads(store.path.read_text())["tabs"][0])

    def test_version_two_files_still_load(self) -> None:
        import json

        with tempfile.TemporaryDirectory() as directory:
            left, right = Path(directory) / "l", Path(directory) / "r"
            left.mkdir()
            right.mkdir()
            store = SessionStore(Path(directory) / "session.json")
            store.path.write_text(json.dumps({
                "version": 2, "tabs": [{"directories": [str(left), str(right)], "orientation": "vertical"}],
            }), encoding="utf-8")
            self.assertEqual(store.load().tabs[0].tree(), ["vertical", 0, 1])


class ShellIntegrationTests(unittest.TestCase):
    def test_parse_mark(self) -> None:
        from hackerterminal.terminal import parse_mark

        self.assertEqual(parse_mark("1|7|2|1530|2|make %7C tee log%3B ok %25"), (7, 2, 1.53, 2, "make | tee log; ok %"))
        self.assertEqual(parse_mark("1|8||0|1|"), (8, None, 0.0, 1, ""))
        for broken in ("", "1", "2|1|0|0|1|x", "1|x|0|0|1|y", "1;1;0;0;1;z"):
            self.assertIsNone(parse_mark(broken), broken)
        self.assertEqual(parse_mark("1|1|0|0|99|x")[3], 10)  # prompt height is bounded

    def test_command_rows(self) -> None:
        from hackerterminal.terminal import PromptMark, command_extra_rows

        self.assertEqual(command_extra_rows(PromptMark(10, 4, 1, "ls"), 80), 0)
        self.assertEqual(command_extra_rows(PromptMark(10, 70, 1, "x" * 10), 80), 0)   # fills the row exactly
        self.assertEqual(command_extra_rows(PromptMark(10, 70, 1, "x" * 11), 80), 1)   # wraps once
        self.assertEqual(command_extra_rows(PromptMark(10, 2, 1, "for i\ndo\ndone"), 80), 2)

    def test_launch_adapts_only_plain_bash_and_zsh(self) -> None:
        import hackerterminal.terminal as terminal_module
        from hackerterminal.terminal import SHELL_DIRECTORY, integration_launch

        with patch.object(terminal_module, "HAS_TERMPROPS", False):
            self.assertEqual(integration_launch(["/bin/bash", "-l"], ""), (["/bin/bash", "-l"], {}))
        self.enterContext(patch.object(terminal_module, "HAS_TERMPROPS", True))
        with patch.dict(os.environ, {"ZDOTDIR": "/meu/zdotdir"}):
            argv, env = integration_launch(["/usr/bin/zsh", "-l"], "")
        self.assertEqual(argv, ["/usr/bin/zsh", "-l"])
        self.assertEqual(env["ZDOTDIR"], str(SHELL_DIRECTORY / "zsh"))
        self.assertEqual(env["HACKER_TERMINAL_ZDOTDIR"], "/meu/zdotdir")
        argv, env = integration_launch(["/bin/bash", "-l"], "")
        self.assertEqual(argv, ["/bin/bash", "--init-file", str(SHELL_DIRECTORY / "bash" / "integration.bash"), "-i"])
        self.assertEqual(integration_launch(["/bin/bash", "--norc"], "bash --norc"), (["/bin/bash", "--norc"], {}))
        self.assertEqual(integration_launch(["/usr/bin/fish", "-l"], ""), (["/usr/bin/fish", "-l"], {}))
        with patch.dict(os.environ, {"HACKER_TERMINAL_SHELL_INTEGRATION": "0"}):
            self.assertEqual(integration_launch(["/bin/bash", "-l"], ""), (["/bin/bash", "-l"], {}))

    def test_scripts_are_valid_shell(self) -> None:
        import shutil
        import subprocess

        from hackerterminal.terminal import SHELL_DIRECTORY

        subprocess.run(["bash", "-n", str(SHELL_DIRECTORY / "bash" / "integration.bash")], check=True)
        if shutil.which("zsh"):
            subprocess.run(["zsh", "-n", str(SHELL_DIRECTORY / "zsh" / ".zshenv")], check=True)


class ConnectionTests(unittest.TestCase):
    def test_validation_blocks_option_injection(self) -> None:
        from hackerterminal.connections import Connection, ConnectionError, validate

        validate(Connection("ok", "Servidor", "kali@10.0.0.5", 2222, "~/.ssh/id_ed25519", "-J bastiao -A"))
        for bad in (
            Connection("x", "X", "-oProxyCommand=id"),
            Connection("x", "X", "user@-evil"),
            Connection("x", "X", "dois hosts"),
            Connection("x", "X", "host", port=70000),
            Connection("x", "X", "host", options="outrohost"),
            Connection("x", "X", "host", options="-o 'sem fim"),
            Connection("X Y", "X", "host"),
        ):
            with self.assertRaises(ConnectionError, msg=bad):
                validate(bad)

    def test_command_line_is_quoted(self) -> None:
        from hackerterminal.connections import Connection

        connection = Connection("c", "C", "me@host", 2200, "~/chave com espaço", "-o 'User=x y'")
        line = connection.command_line()
        self.assertIn("-p 2200", line)
        self.assertIn("'User=x y'", line)
        self.assertEqual(connection.command()[-1], "me@host")
        self.assertTrue(connection.command()[4].endswith("chave com espaço"))

    def test_reads_ssh_config_hosts(self) -> None:
        from hackerterminal.connections import read_ssh_config

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config"
            path.write_text(
                "# comentário\nHost web db\n  User root\nHost\tlab\nHost=bastiao\nHost *.interno prod-? !x\nHost *\n",
                encoding="utf-8",
            )
            names = [host.name for host in read_ssh_config(path)]
            self.assertEqual(names, ["web", "db", "lab", "bastiao"])
            self.assertTrue(all(host.from_ssh_config for host in read_ssh_config(path)))
        self.assertEqual(read_ssh_config(Path("/definitely/missing")), [])

    def test_store_round_trip_and_ssh_config_merge(self) -> None:
        from hackerterminal.connections import Connection, ConnectionStore

        with tempfile.TemporaryDirectory() as directory:
            ssh_config = Path(directory) / "config"
            ssh_config.write_text("Host lab web\n", encoding="utf-8")
            store = ConnectionStore(Path(directory) / "ssh.ini", ssh_config)
            saved = Connection("prod", "Produção", "web", 22, theme="red-alert", confirm=True)
            self.assertTrue(store.save([saved, Connection("cfg", "lab", "lab", from_ssh_config=True)]))
            self.assertEqual(store.path.stat().st_mode & 0o777, 0o600)
            loaded = store.load()
            self.assertEqual(loaded[0], saved)
            self.assertEqual([c.name for c in loaded[1:]], ["lab"])  # "web" is already saved
            self.assertEqual(store.unique_identifier("Produção — banco", set()), "producao-banco")
            self.assertEqual(store.unique_identifier("Produção", {"producao"}), "producao-2")
            promoted = store.promote(loaded[1], {"prod"})
            self.assertFalse(promoted.from_ssh_config)
            self.assertNotIn("password", store.path.read_text(encoding="utf-8"))
            store.path.write_text("[ssh:mal]\nname = x\ndestination = -oProxyCommand=id\n", encoding="utf-8")
            self.assertEqual(store.load_saved(), [])  # invalid entries are skipped


class CommandFieldTests(unittest.TestCase):
    def test_fields_and_defaults(self) -> None:
        from hackerterminal.actions import Field, fields

        self.assertEqual(
            fields("ping -c {vezes=4} {host} {host} {extra=}"),
            [Field("vezes", "4"), Field("host"), Field("extra", "")],
        )
        self.assertTrue(Field("host").required)
        self.assertFalse(Field("extra", "").required)

    def test_shell_syntax_is_not_mistaken_for_fields(self) -> None:
        from hackerterminal.actions import fields

        for command in ("awk '{print $1}' f", "echo ${HOME} ${x:-y}", "cp a.{txt,bak}", "f() { ls; }", "echo {1..3}", "echo \\{x}"):
            self.assertEqual(fields(command), [], command)

    def test_values_cannot_run_as_code(self) -> None:
        from hackerterminal.actions import fill

        self.assertEqual(fill("nmap -sV {alvo}", {"alvo": "1.2.3.4; id"}), "nmap -sV '1.2.3.4; id'")
        self.assertEqual(fill("ping -c {n=4} {h}", {"h": "x"}), "ping -c 4 x")
        self.assertEqual(fill("curl {url} {flags=}", {"url": "h"}), "curl h ")
        self.assertEqual(
            fill('echo "oi {nome}" \'{nome}\'', {"nome": 'a"$(id)`b`\\'}),
            'echo "oi a\\"\\$(id)\\`b\\`\\\\" \'{nome}\'',
        )
        command = fill('printf "%s|%s\\n" {a} "{b}"', {"a": "x y", "b": "$(touch /tmp/pwned) `id`"})
        result = subprocess.run(["bash", "-c", command], capture_output=True, text=True, check=True)
        self.assertEqual(result.stdout, "x y|$(touch /tmp/pwned) `id`\n")


class DropdownTests(unittest.TestCase):
    def test_geometry_spans_work_area_top(self) -> None:
        from hackerterminal.dropdown import geometry

        self.assertEqual(geometry((0, 32, 1920, 1048), 45), (0, 32, 1920, 471))
        self.assertEqual(geometry((1920, 0, 1280, 1024), 200), (1920, 0, 1280, 921))  # clamped to 90%
        self.assertEqual(geometry((0, 0, 800, 400), 10), (0, 0, 800, 240))  # 25% but never below 240 px

    def test_preferences_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = ConfigStore(Path(directory) / "config.ini")
            preferences = Preferences(dropdown_height=99, dropdown_autohide=True)
            preferences.normalize()
            self.assertEqual(preferences.dropdown_height, 90)
            store.save(preferences)
            loaded = store.load()
            self.assertEqual((loaded.dropdown_height, loaded.dropdown_autohide), (90, True))

    def test_xfce_binding_never_steals_a_taken_key(self) -> None:
        from hackerterminal import dropdown

        calls = []

        def fake_run(argv, **_kwargs):
            calls.append(argv)
            stdout = "xfce4-screenshooter" if argv[-1].endswith("/Print") else ""
            writing = "-s" in argv
            return subprocess.CompletedProcess(argv, 0 if stdout or writing else 1, stdout, "")

        with patch.object(dropdown.subprocess, "run", fake_run):
            ok, message = dropdown.bind_xfce("Print", "hacker-terminal --dropdown")
            self.assertFalse(ok)
            self.assertIn("xfce4-screenshooter", message)
            self.assertEqual(len(calls), 1)  # only the lookup, nothing written
            ok, _message = dropdown.bind_xfce("F12", "hacker-terminal --dropdown")
            self.assertTrue(ok)
            self.assertEqual(calls[-1][-6:], ["/commands/custom/F12", "-n", "-t", "string", "-s", "hacker-terminal --dropdown"])

    def test_finds_and_removes_only_our_binding(self) -> None:
        from hackerterminal import dropdown

        listing = (
            "/commands/custom/<Alt>F1      xfce4-popup-whiskermenu --pointer\n"
            "/commands/custom/<Super>grave /usr/bin/hacker-terminal --dropdown\n"
        )
        bindings = {"F12": "", "Print": "xfce4-screenshooter", "<Super>grave": "/usr/bin/hacker-terminal --dropdown"}
        calls = []

        def fake_run(argv, **_kwargs):
            calls.append(argv)
            if "-l" in argv:
                return subprocess.CompletedProcess(argv, 0, listing, "")
            value = bindings.get(argv[argv.index("-p") + 1].removeprefix("/commands/custom/"), "")
            return subprocess.CompletedProcess(argv, 0 if value or "-r" in argv else 1, value, "")

        with patch.object(dropdown.subprocess, "run", fake_run):
            self.assertEqual(dropdown.xfce_dropdown_key(), "<Super>grave")
            self.assertFalse(dropdown.unbind_xfce("Print")[0])  # someone else's key
            self.assertFalse(any("-r" in call for call in calls))
            self.assertTrue(dropdown.unbind_xfce("<Super>grave")[0])
            self.assertEqual(calls[-1][-2:], ["/commands/custom/<Super>grave", "-r"])
        with patch.object(dropdown.subprocess, "run", side_effect=OSError("sem xfconf")):
            self.assertIsNone(dropdown.xfce_dropdown_key())

    def test_launch_command_mentions_dropdown(self) -> None:
        from hackerterminal.dropdown import launch_command

        self.assertTrue(launch_command().endswith("--dropdown"))


class AccessibleThemeTests(unittest.TestCase):
    def test_contrast_helpers(self) -> None:
        from hackerterminal.themes import contrast_ratio, luminance

        self.assertAlmostEqual(contrast_ratio("#000000", "#ffffff"), 21.0, places=2)
        self.assertAlmostEqual(contrast_ratio("#777777", "#777777"), 1.0)
        self.assertLess(luminance("#111315"), luminance("#f6f4ef"))

    def test_light_theme_is_readable_and_light(self) -> None:
        from hackerterminal.themes import contrast_ratio

        theme = ThemeManager().get("paper-light")
        self.assertFalse(theme.dark)
        self.assertFalse(theme.rain)
        background = theme.terminal_background
        self.assertGreaterEqual(contrast_ratio(theme.terminal_foreground, background), 7)
        for index, color in enumerate(theme.ansi[1:], start=1):
            self.assertGreaterEqual(contrast_ratio(color, background), 4.5, f"ANSI {index}: {color}")
        self.assertGreaterEqual(contrast_ratio(theme.muted, theme.surface), 4.5)
        self.assertGreaterEqual(contrast_ratio(theme.accent, theme.background), 4.5)

    def test_high_contrast_theme_meets_aaa(self) -> None:
        from hackerterminal.themes import contrast_ratio

        theme = ThemeManager().get("high-contrast")
        self.assertTrue(theme.dark and theme.high_contrast)
        for index, color in enumerate(theme.ansi[1:], start=1):
            self.assertGreaterEqual(contrast_ratio(color, theme.terminal_background), 7, f"ANSI {index}: {color}")
        self.assertGreaterEqual(contrast_ratio(theme.selection_foreground, theme.selection_background), 7)
        self.assertIn(b".pane-inactive { opacity: 1.0; }", theme.css())
        self.assertIn(b".pane-inactive { opacity: 0.62; }", ThemeManager().get("minimal-dark").css())
        self.assertFalse(any(other.high_contrast for other in ThemeManager().all() if other.identifier != theme.identifier))


class SSHAccessTests(unittest.TestCase):
    def test_copy_id_options_translate_what_ssh_copy_id_cannot_take(self) -> None:
        from hackerterminal.connections import copy_id_options

        self.assertEqual(
            copy_id_options("-J bastiao -A -X -o 'User=x y' -oConnectTimeout=3 -i ~/outra"),
            ["-o", "ProxyJump=bastiao", "-o", "User=x y", "-o", "ConnectTimeout=3"],
        )
        self.assertEqual(copy_id_options("-o 'aberto"), [])

    def test_key_setup_command(self) -> None:
        from hackerterminal.connections import Connection

        helper = Path("/opt/ht/bin/ht-copy-key")
        default = Connection("u", "Umbrel", "umbrel@10.0.0.3").key_setup_command(helper)
        self.assertEqual(
            shlex.split(default),
            [str(helper), "Umbrel", str(Path("~/.ssh/id_ed25519").expanduser()), "umbrel@10.0.0.3"],
        )
        custom = Connection("p", "Produção; rm", "root@h", 2222, "~/chaves/prod key", "-J b").key_setup_command(helper)
        self.assertEqual(
            shlex.split(custom)[1:],
            ["Produção; rm", str(Path("~/chaves/prod key").expanduser()), "-p", "2222", "-o", "ProxyJump=b", "root@h"],
        )

    def test_askpass_command_carries_only_the_identifier(self) -> None:
        from hackerterminal.connections import Connection

        connection = Connection("umbrel", "Umbrel", "umbrel@10.0.0.3")
        self.assertEqual(connection.command_line(), "ssh umbrel@10.0.0.3")
        line = connection.command_line(Path("/opt/ht/bin/ht-askpass"))
        self.assertEqual(
            shlex.split(line),
            ["env", "SSH_ASKPASS=/opt/ht/bin/ht-askpass", "SSH_ASKPASS_REQUIRE=force",
             "HACKER_TERMINAL_SSH_ID=umbrel", "ssh", "umbrel@10.0.0.3"],
        )

    def test_passwords_degrade_without_libsecret(self) -> None:
        from hackerterminal import passwords

        with patch.object(passwords, "Secret", None):
            self.assertFalse(passwords.available())
            self.assertIsNone(passwords.lookup("x"))
            self.assertFalse(passwords.store("x", "X", "senha"))
            self.assertFalse(passwords.forget("x"))


class LazyStartupTests(unittest.TestCase):
    def test_gstreamer_is_not_loaded_until_a_sound_plays(self) -> None:
        code = (
            "import sys\n"
            "import hackerterminal.ui, hackerterminal.keysound, hackerterminal.audio\n"
            "from hackerterminal.audio import SoundPlayer\n"
            "player = SoundPlayer(None, 0.3)\n"
            "print('gi.repository.Gst' in sys.modules)\n"
        )
        result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True,
                                cwd=Path(__file__).resolve().parent.parent)
        self.assertEqual(result.stdout.strip(), "False")
