#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd -- "$project_dir"
# Never make noise while testing; the engine still runs through fakesink.
export HACKER_TERMINAL_AUDIO_SINK=fakesink
# Headless runners have no accessibility bus; its warning must not be fatal.
export NO_AT_BRIDGE=1

python3 -m compileall -q hacker_terminal.py hackerterminal tests
python3 -m py_compile bin/ht-open
python3 -m py_compile bin/ht-askpass
sh -n bin/ht-copy-key
test -x bin/ht-askpass
test -x bin/ht-copy-key
zsh -n hackerterminal/shell/zsh/.zshenv 2>/dev/null || ! command -v zsh >/dev/null
bash -n hackerterminal/shell/bash/integration.bash
test -x bin/ht-open
bin/ht-open --help | grep -F "ht-open ARQUIVO" >/dev/null
bash -n run.sh install.sh tests/smoke.sh packaging/build-deb.sh
python3 hacker_terminal.py --help >/dev/null
python3 hacker_terminal.py --version | grep -F "0.17.0" >/dev/null
test "$(python3 hacker_terminal.py --list-themes | grep -c "	interno$")" -eq 16
test "$(python3 hacker_terminal.py --list-profiles | wc -l)" -eq 4
python3 -m unittest -v tests.test_core

test_dir="$(mktemp -d)"
desktop_file="$test_dir/org.hackerterminal.HackerTerminal.desktop"
trap 'rm -rf -- "$test_dir"' EXIT
sed 's|@EXEC@|/usr/bin/hacker-terminal|g' \
  assets/org.hackerterminal.HackerTerminal.desktop > "$desktop_file"
if command -v desktop-file-validate >/dev/null; then
  desktop-file-validate "$desktop_file"
fi
if command -v xmllint >/dev/null; then
  xmllint --noout assets/hacker-terminal.svg \
    packaging/org.hackerterminal.HackerTerminal.metainfo.xml
fi
if command -v convert >/dev/null && command -v identify >/dev/null; then
  convert -background none assets/hacker-terminal.svg -resize 256x256 "$test_dir/icon.png"
  identify "$test_dir/icon.png" | grep -F '256x256' >/dev/null
fi

if [[ -n "${DISPLAY:-}" ]] && command -v xdpyinfo >/dev/null && xdpyinfo >/dev/null 2>&1; then
  G_DEBUG=fatal-warnings python3 tests/gui_smoke.py
  G_DEBUG=fatal-warnings python3 tests/shell_integration.py
elif [[ "${HACKER_TERMINAL_GUI_TEST:-0}" == "1" ]] && command -v xvfb-run >/dev/null; then
  G_DEBUG=fatal-warnings xvfb-run -a python3 tests/gui_smoke.py
  G_DEBUG=fatal-warnings xvfb-run -a python3 tests/shell_integration.py
else
  ./run.sh --diagnose
  printf '%s\n' "SKIP: smoke gráfico (use HACKER_TERMINAL_GUI_TEST=1 com xvfb-run)" >&2
fi
if [[ "${HACKER_TERMINAL_GUI_TEST:-0}" == "1" ]] && command -v dbus-run-session >/dev/null \
    && command -v xvfb-run >/dev/null && command -v xdotool >/dev/null; then
  # Private bus and display: never the user's running Hacker Terminal.
  dbus-run-session -- env HT_PRIVATE_BUS=1 xvfb-run -a python3 tests/single_instance.py
fi
if command -v dbus-run-session >/dev/null && command -v gnome-keyring-daemon >/dev/null; then
  dbus-run-session -- env HT_PRIVATE_BUS=1 python3 tests/ssh_access.py
fi

test_home="$test_dir/home with spaces"
test_data="$test_dir/data with spaces"
mkdir -p "$test_home"
HOME="$test_home" XDG_DATA_HOME="$test_data" ./install.sh
test -x "$test_home/.local/bin/hacker-terminal"
HOME="$test_home" XDG_DATA_HOME="$test_data" "$test_home/.local/bin/hacker-terminal" --version \
  | grep -F '0.17.0' >/dev/null
test -f "$test_data/hacker-terminal/hackerterminal/themes/matrix-green.ini"
test -x "$test_home/.local/bin/ht-open"
test -x "$test_data/hacker-terminal/bin/ht-askpass"
test -x "$test_data/hacker-terminal/bin/ht-copy-key"
test -f "$test_data/hacker-terminal/hackerterminal/shell/zsh/.zshenv"
test -f "$test_data/hacker-terminal/hackerterminal/shell/bash/integration.bash"
"$test_home/.local/bin/ht-open" --help >/dev/null
test -f "$test_data/applications/org.hackerterminal.HackerTerminal.desktop"
test -f "$test_data/icons/hicolor/scalable/apps/hacker-terminal.svg"
desktop-file-validate "$test_data/applications/org.hackerterminal.HackerTerminal.desktop"
HOME="$test_home" XDG_DATA_HOME="$test_data" ./install.sh --uninstall
test ! -e "$test_home/.local/bin/hacker-terminal"
test ! -e "$test_home/.local/bin/ht-open"

if command -v dpkg-deb >/dev/null; then
  artifact="$(./packaging/build-deb.sh "$test_dir/packages")"
  dpkg-deb --info "$artifact" >/dev/null
  dpkg-deb --contents "$artifact" | grep -F './usr/bin/hacker-terminal' >/dev/null
  dpkg-deb --contents "$artifact" | grep -F './usr/bin/ht-open -> ../lib/hacker-terminal/bin/ht-open' >/dev/null
  dpkg-deb --contents "$artifact" | grep -F './usr/lib/hacker-terminal/bin/ht-askpass' >/dev/null
  dpkg-deb --contents "$artifact" | grep -F './usr/lib/hacker-terminal/bin/ht-copy-key' >/dev/null
  dpkg-deb --contents "$artifact" | grep -F './usr/lib/hacker-terminal/hackerterminal/shell/zsh/.zshenv' >/dev/null
  dpkg-deb --contents "$artifact" | grep -F './usr/lib/hacker-terminal/hackerterminal/shell/bash/integration.bash' >/dev/null
  dpkg-deb --contents "$artifact" \
    | grep -F './usr/lib/hacker-terminal/hackerterminal/themes/matrix-green.ini' >/dev/null
  dpkg-deb --extract "$artifact" "$test_dir/package-root"
  python3 "$test_dir/package-root/usr/lib/hacker-terminal/hacker_terminal.py" --version \
    | grep -F '0.17.0' >/dev/null
  desktop-file-validate \
    "$test_dir/package-root/usr/share/applications/org.hackerterminal.HackerTerminal.desktop"
fi
