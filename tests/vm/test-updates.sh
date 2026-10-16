#!/bin/bash
# shellcheck disable=SC2015 # pass/fail never fail, so A && pass || fail is an if/else
# End-to-end test of the Iron package source (docs/UPDATES.md) against an
# installed Ingot VM: upgrade, rollback, and refusal of untrusted or hostile
# repositories. Everything is local: the host serves the repositories over
# HTTP on 127.0.0.1, which the guest reaches as 10.0.2.2 (QEMU user network).
#
#   tests/vm/test-updates.sh NAME BASE_DEBS NEW_DEBS
#
#   NAME       a running VM (tests/vm/vmctl.py) with a root shell on its serial
#              console (see tests/vm/installed-shell.sh)
#   BASE_DEBS  directory with the Iron .debs the VM has installed
#   NEW_DEBS   directory with a newer build of the same packages
#
# Needs sudo on the host only to read the build's development signing key
# (.work/keys), which the installed image trusts. Results: report.txt in
# tests/vm/results/NAME/updates/.
set -euo pipefail
NAME="$1" BASE="$(realpath "$2")" NEW="$(realpath "$3")"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
V="python3 ${ROOT}/tests/vm/vmctl.py"
PUB="${ROOT}/tools/ingot-publish"
W="${ROOT}/tests/vm/results/${NAME}/updates"
PORT="${INGOT_TEST_PORT:-8089}"
URL="http://10.0.2.2:${PORT}"
rm -rf "${W}"; mkdir -p "${W}"
REPORT="${W}/report.txt"; : > "${REPORT}"
fails=0
pass() { echo "PASS  $*" | tee -a "${REPORT}"; }
fail() { echo "FAIL  $*" | tee -a "${REPORT}"; fails=$((fails + 1)); }
# vm CMD: run in the guest, output to the log; returns the guest exit status.
vm() { echo "### $*" >> "${W}/guest.log"; ${V} run "${NAME}" "$*" --timeout "${T:-600}" >> "${W}/guest.log" 2>&1; }
vm_out() { ${V} run "${NAME}" "$*" --timeout 120 2>/dev/null | tail -n 1; }

# --- host: keys and repositories -----------------------------------------
sudo cp -r "${ROOT}/.work/keys" "${W}/keys"
sudo chown -R "$(id -u):$(id -g)" "${W}/keys"
chmod 700 "${W}/keys"
gpgconf --homedir "${W}/keys" --kill gpg-agent 2>/dev/null || true

# good: base + new, signed with the trusted key
"${PUB}" --repo "${W}/srv/good" --gnupghome "${W}/keys" add "${BASE}"/*.deb >/dev/null
"${PUB}" --repo "${W}/srv/good" --gnupghome "${W}/keys" add "${NEW}"/*.deb >/dev/null
"${PUB}" --repo "${W}/srv/good" verify --keyring "${W}/keys/archive.pub.gpg"

# untrusted: the same packages signed with a key the image does not trust
mkdir -m700 "${W}/evil-keys"
gpg --homedir "${W}/evil-keys" --batch --passphrase '' --quick-gen-key "Not Iron <evil@example.invalid>" ed25519 sign 1d 2>/dev/null
"${PUB}" --repo "${W}/srv/untrusted" --gnupghome "${W}/evil-keys" add "${NEW}"/*.deb >/dev/null

# hostile: correctly signed with the trusted key (a compromised or careless
# publisher) but listing a replacement for an Ubuntu package and a
# non-Iron package that merely starts with "iron".
mk_deb() { # NAME VERSION
    local d="${W}/fake/$1"; mkdir -p "${d}/DEBIAN"
    printf 'Package: %s\nVersion: %s\nArchitecture: all\nMaintainer: test <t@example.invalid>\nDescription: hostile test package\n' "$1" "$2" > "${d}/DEBIAN/control"
    dpkg-deb --root-owner-group --build "${d}" "${W}/fake/$1_$2_all.deb" >/dev/null
}
mk_deb bash 999.0
mk_deb ironic-evil 1.0
"${PUB}" --repo "${W}/srv/hostile" --gnupghome "${W}/keys" add "${W}"/fake/*.deb "${NEW}"/*.deb >/dev/null
gpgconf --homedir "${W}/keys" --kill gpg-agent 2>/dev/null || true
gpgconf --homedir "${W}/evil-keys" --kill gpg-agent 2>/dev/null || true

python3 -m http.server -b 127.0.0.1 -d "${W}/srv" "${PORT}" > "${W}/http.log" 2>&1 &
HTTP=$!
trap 'kill ${HTTP} 2>/dev/null || true' EXIT
sleep 1

base_v=$(dpkg-deb -f "$(ls "${BASE}"/iron-base-files_*.deb)" Version)
new_v=$(dpkg-deb -f "$(ls "${NEW}"/iron-base-files_*.deb)" Version)
echo "base ${base_v}  new ${new_v}" | tee -a "${REPORT}"

# --- guest -------------------------------------------------------------------
own="\$(dpkg-query -W -f='\${Package} \${Status}\n' 'iron-*' 'ingot-*' 2>/dev/null | awk '/ok installed/{print \$1}')"
inst_v() { vm_out "dpkg-query -W -f='\${Version}' iron-base-files"; }

[[ "$(inst_v)" == "${base_v}" ]] && pass "VM has the base version installed" || fail "VM version is $(inst_v), expected ${base_v}"
vm "iron-update status" && pass "iron-update status (unconfigured)" || fail "iron-update status"

vm "iron-update set-source ${URL}/good" || fail "set-source good"
vm "iron-update verify" && pass "verify: trusted repository accepted" || fail "verify: trusted repository rejected"
vm "cat /etc/apt/sources.list.d/iron.sources /etc/apt/preferences.d/iron-archive.pref"
vm "apt-get update -o Dir::Etc::SourceList=/etc/apt/sources.list.d/iron.sources -o Dir::Etc::SourceParts=- -o APT::Get::List-Cleanup=0"
vm "iron-update status | grep -F 'Update available: ${new_v}'" && pass "status reports the update" || fail "status does not report ${new_v}"
T=1200 vm "DEBIAN_FRONTEND=noninteractive apt-get install -y -o Dpkg::Use-Pty=0 --only-upgrade ${own}" \
    && pass "upgrade ran" || fail "upgrade failed"
[[ "$(inst_v)" == "${new_v}" ]] && pass "upgraded to ${new_v}" || fail "after upgrade: $(inst_v)"
vm "dpkg-query -W -f='\${Package} \${Version}\n' 'iron-*' 'ingot-*' 2>/dev/null; dpkg --audit"
vm "iron-update versions | grep -F '${base_v}'" && pass "versions lists the base version" || fail "versions"
vm "iron-update rollback ${base_v}" && pass "rollback dry run" || fail "rollback dry run"
[[ "$(inst_v)" == "${new_v}" ]] && pass "dry run changed nothing" || fail "dry run changed the system"
T=1200 vm "DEBIAN_FRONTEND=noninteractive iron-update rollback ${base_v} --yes" && pass "rollback ran" || fail "rollback failed"
[[ "$(inst_v)" == "${base_v}" ]] && pass "rolled back to ${base_v}" || fail "after rollback: $(inst_v)"
vm "dpkg --audit && systemctl is-system-running" || true

vm "iron-update set-source ${URL}/untrusted" || fail "set-source untrusted"
if vm "iron-update verify"; then fail "verify accepted a repository signed by an untrusted key"
else pass "verify: untrusted key rejected"; fi
vm "apt-cache policy iron-base-files | grep -F '${new_v}'" \
    && fail "untrusted repository's packages became visible" || pass "untrusted packages not visible to APT"

vm "iron-update set-source ${URL}/hostile" || fail "set-source hostile"
vm "iron-update verify" || true
vm "apt-cache policy bash ironic-evil"
cand=$(vm_out "apt-cache policy bash | awk '/Candidate:/{print \$2}'")
[[ "${cand}" != "999.0" ]] && pass "hostile bash 999.0 is not a candidate (candidate ${cand})" || fail "hostile bash is the candidate"
if vm "apt-get -s install ironic-evil"; then fail "ironic-evil installable from the Iron source"
else pass "ironic-evil (not an Iron package) refused"; fi
vm "apt-get -s install iron-base-files=${new_v}" && pass "real Iron packages still installable from it" || fail "Iron packages blocked"

vm "iron-update remove-source && apt-get update -qq" || true
vm "iron-update status" || true
echo "guest requests:" >> "${REPORT}"; cut -d'"' -f2 "${W}/http.log" | sort | uniq -c | sort -rn | head -n 20 >> "${REPORT}"
echo "${fails} failure(s); log ${W}/guest.log" | tee -a "${REPORT}"
exit $(( fails > 0 ))
