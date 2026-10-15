#!/bin/bash
# Build Iron's GDM theme gresource: Yaru's shell theme + Ingot login styling and
# background. Registered via the gdm-theme.gresource alternative (no gnome-shell fork).
# usage: build-gdm-theme.sh YARU_GRESOURCE IRON_CSS LOGIN_PNG OUT_GRESOURCE
set -euo pipefail
src="$1" css="$2" bg="$3" out="$4"
work="$(mktemp -d)"
trap 'rm -rf "${work}"' EXIT
prefix=/org/gnome/shell/theme
mkdir -p "${work}/files"
{
    echo '<?xml version="1.0" encoding="UTF-8"?>'
    echo "<gresources><gresource prefix=\"${prefix}\">"
    while read -r path; do
        rel="${path#"${prefix}"/}"
        mkdir -p "${work}/files/$(dirname "${rel}")"
        gresource extract "${src}" "${path}" > "${work}/files/${rel}"
        echo "<file>${rel}</file>"
    done < <(gresource list "${src}")
    echo "<file>iron-login.png</file>"
    echo "</gresource></gresources>"
} > "${work}/theme.gresource.xml"
cat "${css}" >> "${work}/files/gdm.css"
cp "${bg}" "${work}/files/iron-login.png"
mkdir -p "$(dirname "${out}")"
glib-compile-resources --sourcedir="${work}/files" --target="${out}" "${work}/theme.gresource.xml"
echo "built ${out}"
