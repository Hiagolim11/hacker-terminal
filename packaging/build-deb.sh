#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
output_dir="${1:-$project_dir/dist}"
version="$(sed -n 's/^VERSION = "\([0-9][0-9.]*\)"$/\1/p' "$project_dir/hackerterminal/constants.py")"
package="hacker-terminal"
maintainer="${DEB_MAINTAINER:-Hacker Terminal Contributors <noreply@localhost>}"
export SOURCE_DATE_EPOCH="${SOURCE_DATE_EPOCH:-1791936000}"

if [[ -z "$version" ]]; then
  printf '%s\n' "Nao foi possivel determinar a versao do aplicativo." >&2
  exit 1
fi

for command in dpkg-deb find gzip install sed touch; do
  command -v "$command" >/dev/null || { printf 'Dependencia de build ausente: %s\n' "$command" >&2; exit 1; }
done

build_dir="$(mktemp -d)"
trap 'rm -rf -- "$build_dir"' EXIT
package_root="$build_dir/${package}_${version}_all"

install -d \
  "$package_root/DEBIAN" \
  "$package_root/usr/bin" \
  "$package_root/usr/lib/$package" \
  "$package_root/usr/lib/$package/hackerterminal" \
  "$package_root/usr/lib/$package/hackerterminal/themes" \
  "$package_root/usr/share/applications" \
  "$package_root/usr/share/doc/$package" \
  "$package_root/usr/share/icons/hicolor/scalable/apps" \
  "$package_root/usr/share/metainfo"

install -m 755 "$project_dir/hacker_terminal.py" "$package_root/usr/lib/$package/hacker_terminal.py"
install -D -m 755 "$project_dir/bin/ht-open" "$package_root/usr/lib/$package/bin/ht-open"
install -D -m 755 "$project_dir/bin/ht-askpass" "$package_root/usr/lib/$package/bin/ht-askpass"
install -D -m 755 "$project_dir/bin/ht-copy-key" "$package_root/usr/lib/$package/bin/ht-copy-key"
ln -s "../lib/$package/bin/ht-open" "$package_root/usr/bin/ht-open"
while IFS= read -r -d '' source; do
  install -D -m 644 "$project_dir/$source" "$package_root/usr/lib/$package/$source"
done < <(cd "$project_dir" && find hackerterminal -name '*.py' -not -path '*/__pycache__/*' -print0)
install -D -m 644 "$project_dir/hackerterminal/shell/zsh/.zshenv" \
  "$package_root/usr/lib/$package/hackerterminal/shell/zsh/.zshenv"
install -D -m 644 "$project_dir/hackerterminal/shell/bash/integration.bash" \
  "$package_root/usr/lib/$package/hackerterminal/shell/bash/integration.bash"
for source in "$project_dir"/hackerterminal/themes/*.ini; do
  install -m 644 "$source" "$package_root/usr/lib/$package/hackerterminal/themes/$(basename "$source")"
done
while IFS= read -r -d '' source; do
  install -D -m 644 "$project_dir/$source" "$package_root/usr/lib/$package/$source"
done < <(cd "$project_dir" && find hackerterminal/soundpacks -type f -print0)
install -m 644 "$project_dir/assets/hacker-terminal.svg" \
  "$package_root/usr/share/icons/hicolor/scalable/apps/hacker-terminal.svg"
install -m 644 "$project_dir/packaging/org.hackerterminal.HackerTerminal.metainfo.xml" \
  "$package_root/usr/share/metainfo/org.hackerterminal.HackerTerminal.metainfo.xml"
{
  cat "$project_dir/LICENSE"
  printf '\n========================================================================\n'
  printf 'usr/lib/%s/hackerterminal/soundpacks\n\n' "$package"
  cat "$project_dir/hackerterminal/soundpacks/LICENSE"
} > "$package_root/usr/share/doc/$package/copyright"
chmod 644 "$package_root/usr/share/doc/$package/copyright"
install -m 644 "$project_dir/README.md" "$package_root/usr/share/doc/$package/README.md"

sed 's|@EXEC@|/usr/bin/hacker-terminal|g' \
  "$project_dir/assets/org.hackerterminal.HackerTerminal.desktop" \
  > "$package_root/usr/share/applications/org.hackerterminal.HackerTerminal.desktop"
chmod 644 "$package_root/usr/share/applications/org.hackerterminal.HackerTerminal.desktop"

cat > "$package_root/usr/bin/hacker-terminal" <<'EOF'
#!/bin/sh
exec /usr/bin/python3 /usr/lib/hacker-terminal/hacker_terminal.py "$@"
EOF
chmod 755 "$package_root/usr/bin/hacker-terminal"

cat > "$package_root/DEBIAN/control" <<EOF
Package: $package
Version: $version
Section: utils
Priority: optional
Architecture: all
Maintainer: $maintainer
Depends: python3 (>= 3.10), python3-gi, python3-gi-cairo, gir1.2-gtk-3.0, gir1.2-vte-2.91, hicolor-icon-theme
Recommends: gir1.2-secret-1, librsvg2-common, python3-gst-1.0, gstreamer1.0-plugins-base, gstreamer1.0-plugins-good, fonts-hack
Description: professional native terminal for Linux
 Hacker Terminal is a lightweight GTK 3 and VTE terminal with tabs, split
 panes, session restoration, project context, history search, validated custom
 themes and optional retro visual effects.
EOF
chmod 644 "$package_root/DEBIAN/control"

cat > "$package_root/DEBIAN/postinst" <<'EOF'
#!/bin/sh
set -e
if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database -q /usr/share/applications || true
fi
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
  gtk-update-icon-cache -q -t -f /usr/share/icons/hicolor || true
fi
EOF
chmod 755 "$package_root/DEBIAN/postinst"

cat > "$package_root/DEBIAN/postrm" <<'EOF'
#!/bin/sh
set -e
if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database -q /usr/share/applications || true
fi
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
  gtk-update-icon-cache -q -t -f /usr/share/icons/hicolor || true
fi
EOF
chmod 755 "$package_root/DEBIAN/postrm"

gzip -n -9 -c "$project_dir/CHANGELOG.md" > "$package_root/usr/share/doc/$package/changelog.gz"
chmod 644 "$package_root/usr/share/doc/$package/changelog.gz"
find "$package_root" -exec touch --date="@$SOURCE_DATE_EPOCH" {} +
mkdir -p -- "$output_dir"
artifact="$output_dir/${package}_${version}_all.deb"
dpkg-deb --root-owner-group -Zxz -z9 --build "$package_root" "$artifact" >&2
printf '%s\n' "$artifact"
