#!/bin/bash
# Log in to an installed Ingot VM at GDM as the test user, open the terminal
# from the dock and start a root shell on the serial console, so that
# `tests/vm/vmctl.py run NAME "cmd"` works. Also turns off the idle lock for
# the test user (typing into a locked screen is lost).
#
#   tests/vm/installed-shell.sh NAME [USER_PASSWORD]
#
# Coordinates are for the 1280x800 screen with the default Ingot dock
# (Firefox, Files, Terminal, ...); the user list must show one user.
set -euo pipefail
NAME="$1" PASS="${2:-${INGOT_TEST_PASSWORD:-ironpass2026}}"
V="python3 $(cd "$(dirname "$0")" && pwd)/vmctl.py"
${V} click "${NAME}" 640 351; sleep 2              # the (only) user
${V} type "${NAME}" "${PASS}"; ${V} key "${NAME}" ret
sleep 20
${V} click "${NAME}" 609 763; sleep 6              # Terminal in the dock
${V} type "${NAME}" "sudo systemd-run -u iron-test-shell -p TTYPath=/dev/ttyS0 -p StandardInput=tty -p StandardOutput=tty -p StandardError=tty -p Environment=TERM=dumb /bin/bash -i"
${V} key "${NAME}" ret
sleep 25                                           # the guest consumes typed keys slowly
${V} type "${NAME}" "${PASS}"; ${V} key "${NAME}" ret
for _ in $(seq 1 30); do
    if ${V} run "${NAME}" "id -u" --timeout 5 2>/dev/null | grep -qx 0; then
        uid=$(${V} run "${NAME}" "loginctl list-sessions --no-legend | awk '\$3 != \"gdm\" && \$3 != \"\" {print \$2; exit}'" --timeout 10 | tail -n 1)
        ${V} run "${NAME}" "runuser -u \$(id -nu ${uid}) -- env DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/${uid}/bus sh -c 'gsettings set org.gnome.desktop.session idle-delay 0; gsettings set org.gnome.desktop.screensaver lock-enabled false'" --timeout 20 >/dev/null
        echo "root shell ready on ${NAME}'s serial console"
        exit 0
    fi
    sleep 2
done
echo "no root shell on the serial console (see a screenshot: vmctl.py shot ${NAME})" >&2
exit 1
