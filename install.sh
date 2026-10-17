#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
data_home="${XDG_DATA_HOME:-$HOME/.local/share}"
app_dir="$data_home/hacker-terminal"
bin_dir="${HOME}/.local/bin"
desktop_dir="$data_home/applications"
icon_dir="$data_home/icons/hicolor/scalable/apps"

uninstall() {
  # Only remove ht-open when it is our own link, never a user's command.
  [ "$(readlink -- "$bin_dir/ht-open" 2>/dev/null)" = "$app_dir/bin/ht-open" ] && rm -f -- "$bin_dir/ht-open"
  rm -f -- "$bin_dir/hacker-terminal" "$desktop_dir/hacker-terminal.desktop" \
    "$desktop_dir/org.hackerterminal.HackerTerminal.desktop" \
    "$icon_dir/hacker-terminal.svg"
  rm -rf -- "$app_dir"
  command -v update-desktop-database >/dev/null && update-desktop-database "$desktop_dir" >/dev/null 2>&1 || true
  command -v gtk-update-icon-cache >/dev/null && gtk-update-icon-cache -f -t "$data_home/icons/hicolor" >/dev/null 2>&1 || true
  printf '%s\n' "Hacker Terminal removido da conta atual."
}

if [[ "${1:-}" == "--uninstall" ]]; then
  uninstall
  exit 0
fi

if [[ "${1:-}" == "--check" ]]; then
  exec "$project_dir/run.sh" --diagnose
fi

if [[ $# -gt 0 ]]; then
  printf 'Uso: %s [--check|--uninstall]\n' "$0" >&2
  exit 2
fi

for command in python3 install sed; do
  command -v "$command" >/dev/null || { printf 'Dependencia ausente: %s\n' "$command" >&2; exit 1; }
done

"$project_dir/run.sh" --diagnose

mkdir -p -- "$app_dir" "$bin_dir" "$desktop_dir" "$icon_dir"
install -m 755 "$project_dir/hacker_terminal.py" "$app_dir/hacker_terminal.py"
# Only the code folder is replaced (modules removed in a new version must
# not linger); sound packs and other data next to it stay untouched.
rm -rf -- "$app_dir/hackerterminal"
while IFS= read -r -d '' source; do
  install -D -m 644 "$project_dir/$source" "$app_dir/$source"
done < <(cd "$project_dir" && find hackerterminal -name '*.py' -not -path '*/__pycache__/*' -print0)
install -D -m 644 "$project_dir/hackerterminal/shell/zsh/.zshenv" "$app_dir/hackerterminal/shell/zsh/.zshenv"
install -D -m 644 "$project_dir/hackerterminal/shell/bash/integration.bash" "$app_dir/hackerterminal/shell/bash/integration.bash"
install -d "$app_dir/hackerterminal/themes"
for source in "$project_dir"/hackerterminal/themes/*.ini; do
  install -m 644 "$source" "$app_dir/hackerterminal/themes/$(basename "$source")"
done
install -m 644 "$project_dir/assets/hacker-terminal.svg" "$icon_dir/hacker-terminal.svg"
launcher="$bin_dir/hacker-terminal"
escaped_launcher="${launcher//\\/\\\\}"
escaped_launcher="${escaped_launcher//&/\\&}"
escaped_launcher="${escaped_launcher//|/\\|}"
sed "s|@EXEC@|\"$escaped_launcher\"|g" \
  "$project_dir/assets/org.hackerterminal.HackerTerminal.desktop" \
  > "$desktop_dir/org.hackerterminal.HackerTerminal.desktop"
chmod 644 "$desktop_dir/org.hackerterminal.HackerTerminal.desktop"
rm -f -- "$desktop_dir/hacker-terminal.desktop"

install -d "$app_dir/bin"
install -m 755 "$project_dir/bin/ht-open" "$app_dir/bin/ht-open"
install -m 755 "$project_dir/bin/ht-askpass" "$app_dir/bin/ht-askpass"
install -m 755 "$project_dir/bin/ht-copy-key" "$app_dir/bin/ht-copy-key"
if [ -e "$bin_dir/ht-open" ] && [ "$(readlink -- "$bin_dir/ht-open")" != "$app_dir/bin/ht-open" ]; then
  printf '%s\n' "Aviso: $bin_dir/ht-open já existe e não foi alterado." >&2
else
  ln -sfn "$app_dir/bin/ht-open" "$bin_dir/ht-open"
fi

cat > "$bin_dir/hacker-terminal" <<EOF
#!/bin/sh
exec python3 "$app_dir/hacker_terminal.py" "\$@"
EOF
chmod 755 "$bin_dir/hacker-terminal"

if command -v desktop-file-validate >/dev/null; then
  desktop-file-validate "$desktop_dir/org.hackerterminal.HackerTerminal.desktop"
fi
command -v update-desktop-database >/dev/null && update-desktop-database "$desktop_dir" >/dev/null 2>&1 || true
command -v gtk-update-icon-cache >/dev/null && gtk-update-icon-cache -f -t "$data_home/icons/hicolor" >/dev/null 2>&1 || true

printf '%s\n' "Instalado para a conta atual. Abra pelo menu ou execute: hacker-terminal"
