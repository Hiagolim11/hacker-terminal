"""Unit tests for non-visual Hacker Terminal behavior."""

from __future__ import annotations

import array
import json
import os
import tempfile
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
            self.assertEqual(len(manager.all()), 3)

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

    def test_engine_plays_without_repeat_and_reaches_the_sink(self) -> None:
        from hackerterminal.keysound import KeySoundEngine
        from hackerterminal.runtime import GLib, Gst
        engine = KeySoundEngine()
        loop = GLib.MainLoop()
        engine.on_loaded.append(loop.quit)
        GLib.timeout_add_seconds(10, loop.quit)
        engine.configure("blue", 50, release=False)
        loop.run()
        self.assertIsNotNone(engine.bank)
        self.assertEqual(len(engine.voices), 8)  # warmed up before the first key
        arrived = []
        for voice in engine.voices:
            voice.sink.get_static_pad("sink").add_probe(
                Gst.PadProbeType.BUFFER, lambda *_args: arrived.append(1) or Gst.PadProbeReturn.OK
            )
        engine.press(38, Gdk.KEY_a)
        engine.press(38, Gdk.KEY_a)  # auto-repeat
        engine.release(38, Gdk.KEY_a)  # release sound disabled
        engine.press(39, Gdk.KEY_s)
        GLib.timeout_add(300, loop.quit)
        loop.run()
        self.assertEqual(len(arrived), 2)
        self.assertEqual(engine.voices[0].volume.get_property("volume"), 0.5)
        engine.last_activity -= 100
        engine._check_idle()
        self.assertTrue(engine.paused)
        engine.press(40, Gdk.KEY_d)
        self.assertFalse(engine.paused)
        engine.shutdown()

    def test_broken_pack_falls_back_to_synth(self) -> None:
        from hackerterminal.keysound import KeySoundEngine
        from hackerterminal.runtime import GLib
        engine = KeySoundEngine()
        loop = GLib.MainLoop()
        engine.on_loaded.append(loop.quit)
        GLib.timeout_add_seconds(10, loop.quit)
        engine.configure("pack:does-not-exist", 70, True)
        loop.run()
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
