#!/bin/bash
# Pointer and multi-monitor integration tests for Iron Tiling, in a headless
# GNOME Shell with two virtual monitors. Drags use a Clutter virtual pointer
# (and keyboard for the snap modifier): the events travel the same path as a
# physical mouse — GTK's titlebar sends xdg_toplevel.move, mutter starts the
# grab op, and the extension reacts to it.
set -uo pipefail
WL="iron-ptr-$$"
gsettings set org.gnome.shell disable-user-extensions false
gsettings set org.gnome.shell enabled-extensions "['iron-test@ironlinux.org','iron-tiling@ironlinux.org']"
gsettings set org.gnome.desktop.interface enable-animations false
gnome-shell --headless --wayland --no-x11 --wayland-display "${WL}" \
    --virtual-monitor 1920x1080 --virtual-monitor 1280x800 > "${OUT}/gnome-shell-pointer.log" 2>&1 &
SHELL_PID=$!
PIDS=()
cleanup() { kill "${PIDS[@]}" 2>/dev/null; kill "${SHELL_PID}" 2>/dev/null; wait 2>/dev/null; }
trap cleanup EXIT

ev() { gdbus call --session --dest org.gnome.Shell --object-path /org/gnome/Shell \
        --method org.gnome.Shell.Eval "$1" 2>&1; }
PASS=0; FAIL=0
check() { if [[ "$2" != ERR:* && "$2" == "$3" ]]; then PASS=$((PASS+1)); echo "ok   $1"; else FAIL=$((FAIL+1)); echo "FAIL $1: expected [$3] got [$2]"; fi; }
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

for _ in $(seq 1 60); do jsval '1' 2>/dev/null | grep -q '^1$' && break; sleep 0.5; done
check "shell eval available" "$(jsval '1')" "1"
check "two monitors" "$(jsval "JSON.stringify(Main.layoutManager.monitors.map(m=>[m.x,m.y,m.width,m.height]))")" \
    "[[0,0,1920,1080],[1920,0,1280,800]]"

# Virtual input devices, kept on globalThis between Eval calls.
ev "(()=>{const C=imports.gi.Clutter;const seat=C.get_default_backend().get_default_seat();
globalThis.ironPtr=seat.create_virtual_device(C.InputDeviceType.POINTER_DEVICE);
globalThis.ironKbd=seat.create_virtual_device(C.InputDeviceType.KEYBOARD_DEVICE);return 1})()" >/dev/null
T="imports.gi.GLib.get_monotonic_time()"
move() { ev "globalThis.ironPtr.notify_absolute_motion(${T},$1,$2)" >/dev/null; }
button() { ev "globalThis.ironPtr.notify_button(${T},1,imports.gi.Clutter.ButtonState.$1)" >/dev/null; }
ctrl() { ev "globalThis.ironKbd.notify_keyval(${T},imports.gi.Clutter.KEY_Control_L,imports.gi.Clutter.KeyState.$1)" >/dev/null; }
# drag X0 Y0 X1 Y1 [ctrl]: press, travel in steps (GTK needs motion past its
# drag threshold before it asks the compositor to move), release.
drag() {
    move "$1" "$2"; sleep 0.3; button PRESSED; sleep 0.2
    local i x y
    for i in $(seq 1 24); do
        x=$(( $1 + ($3 - $1) * i / 24 )); y=$(( $2 + ($4 - $2) * i / 24 ))
        move "${x}" "${y}"; sleep 0.04
        [[ "${5:-}" == ctrl && ${i} -eq 6 ]] && ctrl PRESSED
    done
    sleep 0.4; button RELEASED; sleep 0.2
    [[ "${5:-}" == ctrl ]] && ctrl RELEASED
    sleep 1
}

for n in A B C; do
    WAYLAND_DISPLAY="${WL}" GDK_BACKEND=wayland python3 "${HERE}/test-window.py" "iron-ptr-${n}" >/dev/null 2>&1 &
    PIDS+=($!)
    sleep 0.7
done
W="(t=>global.display.list_all_windows().find(w=>w.title===t))"
for _ in $(seq 1 40); do
    c="$(jsval "String(global.display.list_all_windows().filter(w=>w.title?.startsWith('iron-ptr-')).length)")"
    [[ "${c}" == 3 ]] && break; sleep 0.5
done
check "3 test windows" "${c}" "3"
TIL="Main.extensionManager.lookup('iron-tiling@ironlinux.org').stateObj"
RECT() { jsval "JSON.stringify((r=>[r.x,r.y,r.width,r.height])(${W}('$1').get_frame_rect()))"; }
MON() { jsval "String(${W}('$1').get_monitor())"; }
# Point on a window's titlebar (frame top, client-side decorations).
raise() { ev "${W}('$1').activate(global.get_current_time())" >/dev/null; sleep 0.5; }
TITLE_XY() { raise "$1"; jsval "(r=>Math.round(r.x+r.width/2)+' '+Math.round(r.y+18))(${W}('$1').get_frame_rect())"; }

# Independent layouts per monitor.
ev "${TIL}.setLayout('0:0','columns-2')" >/dev/null
ev "${TIL}.setLayout('0:1','columns-2')" >/dev/null
sleep 1.5
# columns-2 has two tiles: the third window stays floating.
check "monitor 0: two tiled, one floating" "$(jsval "String(${TIL}._slots.get('0:0').filter(Boolean).length)")" "2"
TILED_A="$(jsval "String(${TIL}._slots.get('0:0').includes(${W}('iron-ptr-A')))")"
check "window A is tiled" "${TILED_A}" "true"
check "both monitor layouts persisted" \
    "$(gsettings get org.ironlinux.tiling workspace-layouts | grep -o '"0:[01]":{"layout":"columns-2"' | wc -l)" "2"

# 1. Real drag of a tiled window into the left tile of the second monitor.
read -r X Y <<<"$(TITLE_XY iron-ptr-A)"
drag "${X}" "${Y}" 2240 400
check "drag moved window to monitor 1" "$(MON iron-ptr-A)" "1"
check "dragged window tiled on monitor 1" "$(jsval "String(${TIL}._slots.get('0:1').includes(${W}('iron-ptr-A')))")" "true"
check "monitor 1 left tile geometry" "$(jsval "(()=>{const e=${TIL};const r=${W}('iron-ptr-A').get_frame_rect();const t=e._rectsFor('0:1',e._stateFor('0:1'))[0];return String(r.x===t.x&&r.y===t.y&&r.width===t.width&&r.height===t.height)})()")" "true"
check "monitor 0 keeps its other tiled window" "$(jsval "String(${TIL}._slots.get('0:0').filter(Boolean).length)")" "1"
echo "     A on monitor 1: $(RECT iron-ptr-A)"

# 2. Snap-modifier drag on a floating monitor 0 places into the snap layout zone.
ev "${TIL}.setLayout('0:0',null)" >/dev/null; sleep 1
gsettings set org.ironlinux.tiling snap-layout columns-2
read -r X Y <<<"$(TITLE_XY iron-ptr-B)"
drag "${X}" "${Y}" 1500 600 ctrl
check "ctrl-drag snapped into right half" "$(jsval "(r=>String(r.x>=960&&r.x<1000&&r.width>880&&r.width<960))(${W}('iron-ptr-B').get_frame_rect())")" "true"
check "ctrl-drag kept monitor 0 floating" "$(jsval "String(${TIL}._stateFor('0:0'))")" "null"
echo "     B after ctrl-drag: $(RECT iron-ptr-B)"

# 3. Edge snap: drag to the left screen edge of monitor 0.
gsettings set org.ironlinux.tiling edge-snap true
read -r X Y <<<"$(TITLE_XY iron-ptr-C)"
drag "${X}" "${Y}" 2 540
check "edge snap to left half" "$(jsval "(r=>String(r.x<40&&r.width>880&&r.width<=960&&r.height>1000))(${W}('iron-ptr-C').get_frame_rect())")" "true"
echo "     C after edge snap: $(RECT iron-ptr-C)"

# 4. Dragging a tiled window to nowhere returns it to its tile.
read -r X Y <<<"$(TITLE_XY iron-ptr-A)"
before="$(RECT iron-ptr-A)"
ev "${TIL}.setLayout('0:1','columns-2')" >/dev/null
drag "${X}" "${Y}" "$((X + 30))" "$((Y + 5))"
sleep 1
check "short drag of a tiled window snaps back" "$(RECT iron-ptr-A)" "${before}"

gdbus call --session --dest org.gnome.Shell.Screenshot --object-path /org/gnome/Shell/Screenshot \
    --method org.gnome.Shell.Screenshot.Screenshot false false "${OUT}/tiling-two-monitors.png" >/dev/null 2>&1 \
    && echo "screenshot: ${OUT}/tiling-two-monitors.png"
grep -E "JS ERROR|iron-tiling" "${OUT}/gnome-shell-pointer.log" | head -20
echo "pointer tests: ${PASS} passed, ${FAIL} failed"
[[ ${FAIL} -eq 0 ]]
