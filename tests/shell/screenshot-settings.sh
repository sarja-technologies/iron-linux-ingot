#!/bin/bash
# Render Iron Settings pages inside an isolated headless GNOME Shell and save screenshots.
# usage: tests/shell/screenshot-settings.sh [outdir]
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "${HERE}/../.." && pwd)"
export OUT="${1:-${ROOT}/tests/vm/results/settings}"
mkdir -p "${OUT}"
T="$(mktemp -d "${TMPDIR:-/tmp}/iron-settings-shot.XXXXXX")"
trap 'rm -rf "${T}"' EXIT
export HOME="${T}/home" XDG_CONFIG_HOME="${T}/config" XDG_DATA_HOME="${T}/data" XDG_CACHE_HOME="${T}/cache"
mkdir -p "${HOME}" "${XDG_DATA_HOME}/gnome-shell/extensions" "${T}/schemas"
cp -r "${ROOT}/desktop/shell/extensions/"* "${HERE}/iron-test@ironlinux.org" "${XDG_DATA_HOME}/gnome-shell/extensions/"
cp "${ROOT}/agent-desktops/data/org.ironlinux.AgentDesktops1.xml" "${XDG_DATA_HOME}/gnome-shell/extensions/iron-shell@ironlinux.org/"
cp /usr/share/glib-2.0/schemas/*.xml "${ROOT}/desktop/shell/extensions/iron-tiling@ironlinux.org/schemas/"*.xml "${T}/schemas/"
cp "${ROOT}/desktop/defaults/90_iron-ingot.gschema.override" "${T}/schemas/"
glib-compile-schemas "${T}/schemas"
export GSETTINGS_SCHEMA_DIR="${T}/schemas" IRON_SETTINGS_LIB="${ROOT}/apps/iron-settings" ROOT
# shellcheck disable=SC2016 # the inner script is expanded by the inner shell
exec dbus-run-session -- bash -c '
set -u
WL=iron-shot-$$
gsettings set org.gnome.shell disable-user-extensions false
gsettings set org.gnome.shell enabled-extensions "[\"iron-test@ironlinux.org\",\"iron-tiling@ironlinux.org\",\"iron-shell@ironlinux.org\"]"
gsettings set org.gnome.desktop.background picture-uri "file://${ROOT}/build-area/branding/ingot-dawn.jpg"
gsettings set org.gnome.desktop.background picture-uri-dark "file://${ROOT}/build-area/branding/ingot-dawn.jpg"
gnome-shell --headless --wayland --no-x11 --wayland-display "$WL" --virtual-monitor 1600x1000 > "$OUT/shell.log" 2>&1 &
SP=$!
for _ in $(seq 1 60); do gdbus call --session --dest org.gnome.Shell --object-path /org/gnome/Shell --method org.gnome.Shell.Eval 1 2>/dev/null | grep -q true && break; sleep 0.5; done
shot() { gdbus call --session --dest org.gnome.Shell.Screenshot --object-path /org/gnome/Shell/Screenshot --method org.gnome.Shell.Screenshot.Screenshot false false "$1" >/dev/null; }
sleep 2; shot "$OUT/00-desktop.png"
WAYLAND_DISPLAY="$WL" GDK_BACKEND=wayland python3 "$ROOT/apps/iron-settings/bin/iron-settings" --page appearance > "$OUT/app.log" 2>&1 &
AP=$!
sleep 4
for p in appearance tiling agents hardware updates about; do
  WAYLAND_DISPLAY="$WL" GDK_BACKEND=wayland python3 "$ROOT/apps/iron-settings/bin/iron-settings" --page "$p" >> "$OUT/app.log" 2>&1
  sleep 2.5; shot "$OUT/settings-$p.png"; echo "shot $p"
done
kill $AP $SP 2>/dev/null; wait 2>/dev/null
grep -E "Traceback|Error|Warning" "$OUT/app.log" | head -20 || true
'
