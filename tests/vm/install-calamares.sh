#!/bin/bash
# Drive the Ingot Calamares installer in a disposable VM (guided erase-disk
# install), taking a screenshot at every step for review.
#
#   tests/vm/install-calamares.sh NAME ISO EDITION AGENTS DRIVERS ENCRYPT
#     EDITION full|lite   AGENTS enable|disable   DRIVERS auto|open   ENCRYPT yes|no
#
# Coordinates are for the 1280x800 virtio-vga screen with the installer window
# at its default position (verified against screenshots; review them).
set -euo pipefail
NAME="$1" ISO="$2" EDITION="$3" AGENTS="$4" DRIVERS="$5" ENCRYPT="$6"
PASS="${INGOT_TEST_PASSWORD:-ironpass2026}"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
V="python3 ${ROOT}/tests/vm/vmctl.py"
R="${ROOT}/tests/vm/results/${NAME}"
rm -rf "${R}"; mkdir -p "${R}"
shot() { ${V} shot "${NAME}" "${R}/$1.png" >/dev/null; echo "step $1"; }
click() { ${V} click "${NAME}" "$1" "$2"; sleep "${3:-1}"; }
next() { click 1007 757 3; }
# pick VALUE SECOND_ITEM_VALUE X: choose the second list item if they match, else the first.
pick() { if [[ "$1" == "$2" ]]; then click "$3" 130; else click "$3" 113; fi; }

${V} start "${NAME}" --arch amd64 --iso "${ISO}" --disk "${R}/disk.qcow2" --disk-size 40G --memory 4096 --cpus 4
sleep 95; shot s00-live
click 482 763 15; shot s01-welcome            # installer icon in the dock
next; next; next; shot s02-edition              # welcome -> location -> keyboard -> edition
pick "${EDITION}" lite 380
shot s02b-edition-chosen; next
pick "${AGENTS}" enable 400
shot s03-agents; next
pick "${DRIVERS}" open 400
shot s04-drivers; next
click 334 161 2; shot s05-erase                 # erase disk
if [[ "${ENCRYPT}" == yes ]]; then
    # The passphrase fields enable only after the checkbox; typing too early is lost.
    click 334 577 3; click 550 577 1.5; ${V} type "${NAME}" "${PASS}"; sleep 1
    click 775 577 1.5; ${V} type "${NAME}" "${PASS}"; sleep 2
fi
shot s06-partitions; next
click 426 147 0.8; ${V} type "${NAME}" "tester"; sleep 0.5
for x in 426 632; do click "${x}" 327 0.8; ${V} type "${NAME}" "${PASS}"; sleep 0.5; done
sleep 1; shot s07-users; next
shot s08-summary; next                          # "Install"
click 827 465 10; shot s09-installing          # confirm
for i in $(seq 1 160); do
    sleep 15
    ${V} shot "${NAME}" "${R}/poll.png" >/dev/null
    state=$(python3 -c "
from PIL import Image; im=Image.open('${R}/poll.png').convert('RGB')
f=im.getpixel((160,584)); print('finish' if f[2]>180 and f[0]<120 else 'wait')")
    [[ "${state}" == finish ]] && break
done
cp "${R}/poll.png" "${R}/s10-finish.png"
echo "installer reached Finish after $((i * 15)) s (review s10-finish.png for errors)"
