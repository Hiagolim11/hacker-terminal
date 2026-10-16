"""Real shells with the integration hooks, in a throwaway home (run under Xvfb)."""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hackerterminal.config import AppConfig, Preferences
from hackerterminal.runtime import Gtk, Vte
from hackerterminal.terminal import TerminalPane
from hackerterminal.themes import ThemeManager


def pump(seconds: float) -> None:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        Gtk.main_iteration_do(False)


def check(shell: str) -> None:
    home = Path(tempfile.mkdtemp(prefix=f"ht-{shell}-"))
    # A two-line prompt and a startup file that clobbers PROMPT_COMMAND, as
    # Kali's .bashrc does, to make sure the hooks survive both.
    (home / ".bashrc").write_text('PS1="\\u@\\h\\n\\$ "\nPROMPT_COMMAND="PROMPT_COMMAND=echo"\n', encoding="utf-8")
    (home / ".zshrc").write_text("PROMPT=$'%n@%m\\n%# '\nfunction zle-line-init() { : }\nzle -N zle-line-init\n", encoding="utf-8")
    os.environ.update({"HOME": str(home), "SHELL": shutil.which(shell)})
    pane = TerminalPane(
        AppConfig(Preferences(), (), home), lambda *a: None, lambda *a: None, lambda: None,
        ThemeManager(home / "themes").get("minimal-dark"),
    )
    done = []
    pane.on_command_done = lambda _pane, mark: done.append((mark.command, mark.exit_status))
    window = Gtk.Window()
    window.set_default_size(900, 500)
    window.add(pane)
    window.show_all()
    pane.spawn()

    def wait_for(count: int) -> None:
        deadline = time.monotonic() + 10
        while len(pane.prompts) < count and time.monotonic() < deadline:
            Gtk.main_iteration_do(False)

    wait_for(1)
    assert pane.prompts, f"{shell}: no prompt mark (hooks not loaded)"
    assert pane.prompts[0].prompt_lines == 2, f"{shell}: two-line prompt not measured"
    for index, command in enumerate(["printf 'a\\nb\\n'", "false", "", "seq 2"]):
        pane.terminal.feed_child(command.encode() + b"\r")
        wait_for(index + 2)
        pump(0.2)
    assert done == [("printf 'a\\nb\\n'", 0), ("false", 1), ("seq 2", 0)], f"{shell}: {done}"
    rows = pane.output_rows(0)
    text = pane.terminal.get_text_range_format(Vte.Format.TEXT, rows[0], 0, rows[1], 200)[0]
    assert text.rstrip("\n") == "a\nb", f"{shell}: wrong output range {text!r}"
    mark, lines = pane.copy_last_output()
    assert (mark.command, lines) == ("seq 2", 2), f"{shell}: copy_last_output gave {(mark.command, lines)}"
    # After a clear the screen no longer ends at the cursor (VTE may even keep
    # blank lines above the new prompt): the computed top row must be at or
    # above the prompt, with only blank rows in between.
    pane.terminal.feed_child(b"printf '\\033[H\\033[2J\\033[3J'\r")
    wait_for(len(pane.prompts) + 1)
    pump(0.3)
    top = pane.top_visible_row()
    first = pane.prompts[-1].first_row
    assert top <= first < top + pane.terminal.get_row_count(), f"{shell}: top row {top}, prompt {first}"
    between = [
        pane.terminal.get_text_range_format(Vte.Format.TEXT, row, 0, row, 200)[0].strip()
        for row in range(int(top), first)
    ]
    assert not any(between), f"{shell}: text between the top row and the prompt: {between}"
    assert pane.terminal.get_text_range_format(Vte.Format.TEXT, first, 0, first, 200)[0].strip(), f"{shell}: no prompt at {first}"
    window.destroy()
    print(f"{shell}: ok")


def main() -> int:
    from hackerterminal.terminal import HAS_TERMPROPS

    if not HAS_TERMPROPS:
        print("SKIP: VTE sem termprops (anterior à 0.78); integração com o shell desativada")
        return 0
    shells = [shell for shell in ("bash", "zsh") if shutil.which(shell)]
    for shell in shells:
        check(shell)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
