#!/bin/bash
# End-to-end test of an Agent Desktop (VM-backed by default, or a container)
# inside an installed Ingot VM (VM agents use nested KVM): start, guest readiness, instructions and their reported state,
# an approval-gated root command, preview, export, persistence across a clean
# stop/start, and clean shutdown timing.
#
#   tests/vm/test-agent-vm.sh NAME [vm|container]
#
# NAME must be a running installed Ingot VM with Agent Desktops enabled, the
# VM agent image built (`sudo iron-agent image build --vm`), the test user
# logged in with the terminal focused, and a root serial shell
# (tests/vm/installed-shell.sh). Agent commands are typed into the user's
# terminal because polkit only authorises the active desktop session.
# Results: tests/vm/results/NAME/agent-BACKEND/.
set -euo pipefail
NAME="$1" BACKEND="${2:-vm}"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
V="python3 ${ROOT}/tests/vm/vmctl.py"
W="${ROOT}/tests/vm/results/${NAME}/agent-${BACKEND}"
rm -rf "${W}"; mkdir -p "${W}"

cat > "${W}/guest.sh" <<'EOF'
exec > /tmp/agent-vm-test.log 2>&1
ok() { echo "PASS  $*"; }
bad() { echo "FAIL  $*"; }
j() { python3 -c "
import json, sys
from gi.repository import Gio
b = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
r = b.call_sync('org.ironlinux.AgentDesktops1', '/org/ironlinux/AgentDesktops1', 'org.ironlinux.AgentDesktops1',
                'ListAgents', None, None, 0, -1, None)
a = [x for x in json.loads(r.unpack()[0]) if x['id'] == sys.argv[1]][0]
t = a.get('task') or {}
print(a['state'], a.get('guest_ready'), t.get('task'), t.get('state'), t.get('summary', '')[:120])" "$A"; }
ready() { for _ in $(seq 1 120); do j | grep -q '^running True' && return 0; sleep 2; done; return 1; }
task_end() { # N: wait until task N is done/failed, print its state
    for _ in $(seq 1 90); do s=$(j); set -- $s; [ "$3" = "$N" ] && [ "$4" != working ] && { echo "$4"; return; }; sleep 1; done; echo timeout; }
A=$(iron-agent create agent-test --preset light --backend @BACKEND@) && ok "create $A" || bad create
iron-agent start "$A"
t0=$(date +%s); ready && ok "guest ready in $(( $(date +%s) - t0 )) s" || bad "guest never ready: $(j)"
# Sent the moment the guest reports ready: the desktop may still be starting.
iron-agent send "$A" 'echo first > ~/outbox/first.txt; echo persisted > ~/workspace/keep.txt; sync'
N=1; s=$(task_end); [ "$s" = "done" ] && ok "task 1 done" || bad "task 1: $s ($(j))"
iron-agent send "$A" 'echo about-to-fail; false'
N=2; s=$(task_end); [ "$s" = failed ] && ok "task 2 (exit 1) reported failed" || bad "task 2: $s"
iron-agent send "$A" 'iron-elevate id -u'
for _ in $(seq 1 150); do R=$(iron-agent approvals | awk 'NR==1{print $1}'); [ -n "$R" ] && break; sleep 1; done
[ -n "$R" ] && ok "approval requested: $R" || bad "no approval request"
echo APPROVAL-PENDING; sleep 6
iron-agent approve "$R"
N=3; s=$(task_end); [ "$s" = "done" ] && ok "approved root command ran" || bad "task 3: $s"
echo APPROVAL-DECIDED; sleep 6
iron-agent preview "$A" /tmp/agent-vm-preview.png && ok preview || bad preview
mkdir -p ~/agent-vm-export; rm -f ~/agent-vm-export/first.txt
iron-agent export "$A" first.txt ~/agent-vm-export >/dev/null && [ "$(cat ~/agent-vm-export/first.txt)" = first ] \
    && ok export || bad export
t0=$(date +%s); iron-agent stop "$A"; d=$(( $(date +%s) - t0 ))
[ "$d" -lt 25 ] && ok "clean stop in $d s" || bad "stop took $d s (fallback kill?)"
iron-agent start "$A"; ready || bad "not ready after restart"
iron-agent send "$A" 'cat ~/workspace/keep.txt'
N=1; s=$(task_end); [ "$s" = "done" ] && j | grep -q persisted && ok "workspace persisted across restart" || bad "persistence: $(j)"
iron-agent stop "$A"; iron-agent delete "$A" && ok delete || bad delete
echo TEST-END
EOF
sed -i "s/@BACKEND@/${BACKEND}/" "${W}/guest.sh"
B=$(base64 -w0 "${W}/guest.sh")
${V} run "${NAME}" "echo ${B} | base64 -d > /tmp/agent-vm-test.sh; chmod 644 /tmp/agent-vm-test.sh; rm -f /tmp/agent-vm-test.log" --timeout 20 >/dev/null
${V} type "${NAME}" "sh /tmp/agent-vm-test.sh"; ${V} key "${NAME}" ret
wait_for() { for _ in $(seq 1 400); do ${V} run "${NAME}" "grep -q $1 /tmp/agent-vm-test.log" --timeout 10 >/dev/null 2>&1 && return 0; sleep 2; done; return 1; }
wait_for APPROVAL-PENDING && ${V} shot "${NAME}" "${W}/approval-banner.png" >/dev/null
wait_for APPROVAL-DECIDED && ${V} shot "${NAME}" "${W}/after-approve.png" >/dev/null
wait_for TEST-END || echo "FAIL  guest script did not finish" >> "${W}/report.txt"
${V} run "${NAME}" "cat /tmp/agent-vm-test.log" --timeout 20 | tee -a "${W}/report.txt"
${V} run "${NAME}" "base64 -w0 /tmp/agent-vm-preview.png; echo" --timeout 60 | tail -n 1 | base64 -d > "${W}/agent-preview.png" || true
fails=$(grep -c '^FAIL' "${W}/report.txt" || true)
echo "${fails} failure(s); evidence in ${W}"
exit $(( fails > 0 ))
