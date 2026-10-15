#!/bin/bash
# Integration tests for the Ingot shell extensions inside a real, isolated,
# headless GNOME Shell (own D-Bus session, HOME and dconf; no host impact).
# usage: tests/shell/run-shell-tests.sh [outdir]
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "${HERE}/../.." && pwd)"
OUT="${1:-${ROOT}/tests/vm/results/shell}"
mkdir -p "${OUT}"
T="$(mktemp -d "${TMPDIR:-/tmp}/iron-shell-test.XXXXXX")"
trap 'rm -rf "${T}"' EXIT
export HOME="${T}/home" XDG_CONFIG_HOME="${T}/config" XDG_DATA_HOME="${T}/data" XDG_CACHE_HOME="${T}/cache" XDG_STATE_HOME="${T}/state"
mkdir -p "${HOME}" "${XDG_CONFIG_HOME}" "${XDG_CACHE_HOME}" "${XDG_STATE_HOME}"
EXT="${XDG_DATA_HOME}/gnome-shell/extensions"
mkdir -p "${EXT}"
cp -r "${ROOT}/desktop/shell/extensions/"* "${HERE}/iron-test@ironlinux.org" "${EXT}/"
cp "${ROOT}/agent-desktops/data/org.ironlinux.AgentDesktops1.xml" "${EXT}/iron-shell@ironlinux.org/"
glib-compile-schemas "${EXT}/iron-tiling@ironlinux.org/schemas"
export GSETTINGS_SCHEMA_DIR="${EXT}/iron-tiling@ironlinux.org/schemas:/usr/share/glib-2.0/schemas"
export OUT HERE
exec dbus-run-session -- bash "${HERE}/shell-test-inner.sh"
