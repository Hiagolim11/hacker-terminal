#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

if ! python3 -c 'import gi' >/dev/null 2>&1; then
  printf '%s\n' "PyGObject nao encontrado. No Debian/Kali: sudo apt install python3-gi" >&2
  exit 1
fi

cd -- "$project_dir"
exec python3 hacker_terminal.py "$@"
