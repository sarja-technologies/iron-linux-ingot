#!/bin/bash
# Build Ingot's `gnotch` .deb from an upstream Gnotch checkout at a pinned commit.
#
# Gnotch stays an independent project (https://github.com/crossainthero-lab/Gnotch);
# Ingot only repackages a known-good commit system-wide. The extension is
# installed but NOT enabled; users opt in from Iron Settings or with
# `gnome-extensions enable gnotch@gnotch.dev`.
#
# usage: build-gnotch-deb.sh GNOTCH_SRC_DIR OUT_DIR [EXPECTED_COMMIT]
set -euo pipefail
SRC="$(cd "$1" && pwd)"
OUT="$(mkdir -p "$2" && cd "$2" && pwd)"
PIN="${3:-$(cat "$(dirname "$0")/PINNED_COMMIT")}"
UUID="gnotch@gnotch.dev"
# The checkout may belong to another user when this runs as root during image builds.
git() { command git -c safe.directory="${SRC}" "$@"; }

commit="$(git -C "${SRC}" rev-parse HEAD)"
if [[ "${commit}" != "${PIN}"* ]]; then
    echo "gnotch: ${SRC} is at ${commit}, expected pinned ${PIN}" >&2
    exit 1
fi
version="$(python3 -c "import json,sys;print(json.load(open(sys.argv[1]))['version-name'])" \
    "${SRC}/shell-extension/${UUID}/metadata.json")"
deb_version="${version}+git$(git -C "${SRC}" show -s --format=%cd --date=format:%Y%m%d HEAD).${commit:0:7}"

work="$(mktemp -d)"
trap 'rm -rf "${work}"' EXIT
pkg="${work}/gnotch"
# Export the exact committed tree (never the working copy).
git -C "${SRC}" archive --format=tar "${commit}" | tar -x -C "${work}" --one-top-level=src

S="${work}/src"
install -d "${pkg}/DEBIAN" "${pkg}/usr/share/gnome-shell/extensions" "${pkg}/usr/share/gnotch/service" \
    "${pkg}/usr/share/gnotch/sdk/python" "${pkg}/usr/share/gnotch/addons" "${pkg}/usr/share/dbus-1/services" \
    "${pkg}/usr/bin" "${pkg}/usr/share/doc/gnotch" "${pkg}/usr/share/glib-2.0/schemas"
cp -r "${S}/shell-extension/${UUID}" "${pkg}/usr/share/gnome-shell/extensions/"
# System-wide schema (compiled by the glib trigger), not a per-extension compiled copy.
mv "${pkg}/usr/share/gnome-shell/extensions/${UUID}/schemas/"*.gschema.xml "${pkg}/usr/share/glib-2.0/schemas/"
rm -rf "${pkg}/usr/share/gnome-shell/extensions/${UUID}/schemas"
cp -r "${S}/service/gnotch_service" "${pkg}/usr/share/gnotch/service/"
install -m755 "${S}/service/gnotch-service" "${S}/service/gnotch-ctl" "${pkg}/usr/share/gnotch/service/"
install -m644 "${S}/sdk/python/gnotch_sdk.py" "${pkg}/usr/share/gnotch/sdk/python/"
for a in voice-notes agent-workspace; do
    [[ -d "${S}/addons/${a}" ]] && cp -r "${S}/addons/${a}" "${pkg}/usr/share/gnotch/addons/"
done
find "${pkg}" \( -name __pycache__ -o -name .venv \) -type d -prune -exec rm -rf {} +
ln -s ../share/gnotch/service/gnotch-ctl "${pkg}/usr/bin/gnotch-ctl"
cat > "${pkg}/usr/share/dbus-1/services/org.gnotch.Service1.service" <<'EOF'
[D-BUS Service]
Name=org.gnotch.Service1
Exec=/usr/share/gnotch/service/gnotch-service
EOF
install -m644 "${S}/README.md" "${S}/LICENSE" "${pkg}/usr/share/doc/gnotch/"
echo "${commit}" > "${pkg}/usr/share/doc/gnotch/UPSTREAM_COMMIT"

size="$(du -sk "${pkg}/usr" | cut -f1)"
cat > "${pkg}/DEBIAN/control" <<EOF
Package: gnotch
Version: ${deb_version}
Architecture: all
Maintainer: Iron Linux Developers <crossainthero@gmail.com>
Installed-Size: ${size}
Depends: gnome-shell (>= 50), gnome-shell (<< 51), python3, python3-gi, libglib2.0-bin
Recommends: pipewire-bin
Suggests: whisper.cpp, iron-agent-desktops
Section: gnome
Priority: optional
Homepage: https://github.com/crossainthero-lab/Gnotch
Description: Gnotch - extensible notch for the GNOME top bar
 Compact notch in the top bar that expands into a panel, with an addon
 platform (addons run outside GNOME Shell). Ships the Voice Notes and Agent
 Workspace addons disabled. Packaged for Iron Linux Ingot from upstream
 commit ${commit:0:12}; installed but not enabled.
EOF
dpkg-deb --root-owner-group --build "${pkg}" "${OUT}/gnotch_${deb_version}_all.deb" >/dev/null
echo "${OUT}/gnotch_${deb_version}_all.deb"
