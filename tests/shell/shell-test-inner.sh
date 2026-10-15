#!/bin/bash
set -uo pipefail
WL="iron-test-$$"
gsettings set org.gnome.shell disable-user-extensions false
gsettings set org.gnome.shell enabled-extensions "['iron-test@ironlinux.org','iron-tiling@ironlinux.org','iron-shell@ironlinux.org']"
gsettings set org.gnome.desktop.interface enable-animations false
gnome-shell --headless --wayland --no-x11 --wayland-display "${WL}" --virtual-monitor 1920x1080 > "${OUT}/gnome-shell.log" 2>&1 &
SHELL_PID=$!
cleanup() { kill "${PIDS[@]}" 2>/dev/null; kill "${SHELL_PID}" 2>/dev/null; wait 2>/dev/null; }
PIDS=()
trap cleanup EXIT

ev() { # evaluate JS in the shell; prints the result string
    gdbus call --session --dest org.gnome.Shell --object-path /org/gnome/Shell \
        --method org.gnome.Shell.Eval "$1" 2>&1
}
PASS=0; FAIL=0
check() { if [[ "$2" != ERR:* && "$2" == "$3" ]]; then PASS=$((PASS+1)); echo "ok   $1"; else FAIL=$((FAIL+1)); echo "FAIL $1: expected [$3] got [$2]"; fi; }
# Eval returns (ok, 'json'); decode the JSON so strings compare plainly.
jsval() { ev "$1" | python3 -c '
import ast, json, sys
raw = sys.stdin.read().strip()
try:
    ok, val = ast.literal_eval(raw.replace("(true,", "(True,", 1).replace("(false,", "(False,", 1))
except Exception:
    print("ERR:" + raw); sys.exit()
if not ok:
    print("ERR:" + val); sys.exit()
try:
    v = json.loads(val) if val else ""
except ValueError:
    v = val
print(v if isinstance(v, str) else json.dumps(v, separators=(",", ":")))'; }

for _ in $(seq 1 60); do
    jsval '1' 2>/dev/null | grep -q '^1$' && break; sleep 0.5
done
check "shell eval available" "$(jsval '1')" "1"
for uuid in iron-tiling@ironlinux.org iron-shell@ironlinux.org; do
    check "${uuid} active" "$(jsval "String(Main.extensionManager.lookup('${uuid}')?.state)")" "1"
done
check "iron panel class" "$(jsval "String(Main.panel.has_style_class_name('iron-panel'))")" "true"

for n in A B C D; do
    WAYLAND_DISPLAY="${WL}" GDK_BACKEND=wayland python3 "${HERE}/test-window.py" "iron-test-${n}" >/dev/null 2>&1 &
    PIDS+=($!)
done
for _ in $(seq 1 40); do
    c="$(jsval "String(global.display.list_all_windows().filter(w=>w.title?.startsWith('iron-test-')).length)")"
    [[ "${c}" == 4 ]] && break; sleep 0.5
done
check "4 test windows" "${c}" "4"
sleep 1

TIL="Main.extensionManager.lookup('iron-tiling@ironlinux.org').stateObj"
RECTS="JSON.stringify(global.display.list_all_windows().filter(w=>w.title?.startsWith('iron-test-')).sort((a,b)=>a.title<b.title?-1:1).map(w=>{const r=w.get_frame_rect();return [r.x,r.y,r.width,r.height]}))"
AREA="JSON.stringify((r=>[r.x,r.y,r.width,r.height])(global.workspace_manager.get_active_workspace().get_work_area_for_monitor(0)))"
echo "work area: $(jsval "${AREA}")"

expect_layout() { # name layout -> compare with geometry computed by layout.js inside the shell
    local name="$1" layout="$2"
    ev "${TIL}.setLayout('0:0','${layout}')" >/dev/null
    sleep 1.5
    local got exp
    got="$(jsval "${RECTS}")"
    exp="$(jsval "JSON.stringify((()=>{const ext=${TIL};const s=ext._stateFor('0:0');const rects=ext._rectsFor('0:0',s);const slots=ext._slots.get('0:0');return global.display.list_all_windows().filter(w=>w.title?.startsWith('iron-test-')).sort((a,b)=>a.title<b.title?-1:1).map(w=>{const i=slots.indexOf(w);const r=i<0?w.get_frame_rect():rects[i];return [r.x,r.y,r.width,r.height]})})())")"
    check "${name}: windows match tiles" "${got}" "${exp}"
    echo "     ${layout}: ${got}"
}
expect_layout "two columns" columns-2
expect_layout "three columns" columns-3
expect_layout "2x2 grid" grid-2x2
expect_layout "3x3 grid" grid-3x3

# 2x2: no overlaps and all four windows tiled.
ev "${TIL}.setLayout('0:0','grid-2x2')" >/dev/null; sleep 1.5
check "2x2 all tiled" "$(jsval "String(${TIL}._slots.get('0:0').filter(Boolean).length)")" "4"

# Gap change triggers reflow.
gsettings set org.ironlinux.tiling inner-gap 24; gsettings set org.ironlinux.tiling outer-gap 30; sleep 1.5
check "outer gap applied" "$(jsval "String(global.display.list_all_windows().filter(w=>w.title?.startsWith('iron-test-')).every(w=>w.get_frame_rect().x>=30))")" "true"

# Persistence: layout stored per workspace:monitor.
check "layout persisted" "$(gsettings get org.ironlinux.tiling workspace-layouts | grep -c '"0:0":{"layout":"grid-2x2"')" "1"

# Resizable tiles: simulate an edge drag result and verify neighbours follow.
ev "(()=>{const ext=${TIL};const w=ext._slots.get('0:0')[0];const r=w.get_frame_rect();ext._drag={win:w,moving:false,resizing:true,key:'0:0'};w.move_resize_frame(false,r.x,r.y,r.width+200,r.height);return 1})()" >/dev/null
sleep 1  # let the Wayland client ack the new size, as it would during a real drag
ev "(()=>{const ext=${TIL};const w=ext._slots.get('0:0')[0];ext._onGrabEnd(w,0);return 1})()" >/dev/null
sleep 1.5
check "resize moved column boundary" "$(jsval "String(${TIL}._states.get('0:0').cols[0] > 0.55)")" "true"
check "neighbour follows resize" "$(jsval "(()=>{const L=${TIL}._slots.get('0:0');const a=L[0].get_frame_rect(),b=L[1].get_frame_rect();return String(b.x-(a.x+a.width))})()")" "24"

# Swap with neighbour.
ev "(()=>{const ext=${TIL};const L=ext._slots.get('0:0');L[0].activate(global.get_current_time());return 1})()" >/dev/null; sleep 0.5
before="$(jsval "${TIL}._slots.get('0:0')[0].title")"
ev "${TIL}._swapFocus('right')" >/dev/null; sleep 1
after="$(jsval "${TIL}._slots.get('0:0')[1].title")"
check "swap right" "${after}" "${before}"

# Turning tiling off releases windows.
ev "${TIL}.setLayout('0:0',null)" >/dev/null; sleep 0.5
check "layout none" "$(jsval "String(${TIL}._stateFor('0:0'))")" "null"

# Screenshot for evidence (re-tile first).
ev "${TIL}.setLayout('0:0','grid-2x2')" >/dev/null; sleep 1.5
gdbus call --session --dest org.gnome.Shell.Screenshot --object-path /org/gnome/Shell/Screenshot \
    --method org.gnome.Shell.Screenshot.Screenshot false false "${OUT}/tiling-2x2.png" >/dev/null 2>&1 \
    && echo "screenshot: ${OUT}/tiling-2x2.png"

grep -E "JS ERROR|iron-(tiling|shell)" "${OUT}/gnome-shell.log" | head -20
echo "shell tests: ${PASS} passed, ${FAIL} failed"
[[ ${FAIL} -eq 0 ]]
