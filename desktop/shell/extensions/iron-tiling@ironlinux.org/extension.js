// Iron Tiling - first-party tiling for Iron Linux Ingot (GNOME Shell 49/50).
//
// Model: every (workspace, monitor) pair may have a layout. When it does, the
// normal windows on it are assigned to tiles in order and kept there. When it
// does not, the workspace floats but drag-to-snap (edge snap, or holding the
// snap modifier to pick a zone of the snap layout) is still available.

import GLib from 'gi://GLib';
import Meta from 'gi://Meta';
import Shell from 'gi://Shell';
import St from 'gi://St';
import Clutter from 'gi://Clutter';

import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';

import * as L from './layout.js';

const LAYOUT_KEYS = {
    'layout-none': null,
    'layout-columns-2': 'columns-2',
    'layout-columns-3': 'columns-3',
    'layout-grid-2x2': 'grid-2x2',
    'layout-grid-3x3': 'grid-3x3',
};
const MOVE_KEYS = {
    'swap-left': 'left', 'swap-right': 'right', 'swap-up': 'up', 'swap-down': 'down',
};
const MODIFIERS = {
    ctrl: Clutter.ModifierType.CONTROL_MASK,
    alt: Clutter.ModifierType.MOD1_MASK,
    shift: Clutter.ModifierType.SHIFT_MASK,
    super: Clutter.ModifierType.SUPER_MASK | Clutter.ModifierType.MOD4_MASK,
};
const ANIM_MS = 160;
const RESIZE_OPS = new Set(Object.entries(Meta.GrabOp)
    .filter(([k]) => /RESIZING/.test(k)).map(([, v]) => v));
const NONE = 'none'; // explicit "no tiling" override for a workspace

function isTileable(win) {
    return win &&
        win.get_window_type() === Meta.WindowType.NORMAL &&
        !win.is_skip_taskbar() &&
        !win.get_transient_for() &&
        !win.is_on_all_workspaces() &&
        !win.minimized &&
        !win.is_fullscreen() &&
        win.allows_move();
}

class Overlay {
    constructor() {
        this._actors = [];
    }

    show(rects, active) {
        this.hide();
        for (let i = 0; i < rects.length; i++) {
            const r = rects[i];
            const a = new St.Widget({
                style_class: i === active ? 'iron-tiling-zone iron-tiling-zone-active' : 'iron-tiling-zone',
                x: r.x, y: r.y, width: r.width, height: r.height,
                reactive: false,
            });
            Main.layoutManager.uiGroup.add_child(a);
            this._actors.push(a);
        }
    }

    hide() {
        for (const a of this._actors)
            a.destroy();
        this._actors = [];
    }
}

export default class IronTilingExtension extends Extension {
    enable() {
        this._settings = this.getSettings();
        this._states = new Map(); // key "ws:mon" -> {layout, cols, rows} | {layout: 'none'}
        this._slots = new Map(); // key -> Array<Meta.Window|null>
        this._winKey = new Map(); // Meta.Window -> key
        this._winSignals = new Map(); // Meta.Window -> [ids]
        this._overlay = new Overlay();
        this._drag = null;
        this._reflowIds = new Map();
        this._handles = [];

        this._loadStates();

        const connect = (obj, sig, fn) => this._handles.push([obj, obj.connect(sig, fn)]);
        connect(global.display, 'window-created', (_d, win) => this._onWindowCreated(win));
        connect(global.display, 'grab-op-begin', (_d, win, op) => this._onGrabBegin(win, op));
        connect(global.display, 'grab-op-end', (_d, win, op) => this._onGrabEnd(win, op));
        connect(global.display, 'workareas-changed', () => this._reflowAll());
        connect(Main.layoutManager, 'monitors-changed', () => this._reflowAll());
        connect(global.workspace_manager, 'workspace-removed', () => this._rebuildAll());
        connect(global.workspace_manager, 'workspaces-reordered', () => this._rebuildAll());
        for (const k of ['inner-gap', 'outer-gap'])
            connect(this._settings, `changed::${k}`, () => this._reflowAll());
        const reload = () => {
            if (this._savingLayouts)
                return;
            this._loadStates();
            this._rebuildAll();
        };
        connect(this._settings, 'changed::workspace-layouts', reload);
        connect(this._settings, 'changed::default-layout', reload);

        for (const [name, layout] of Object.entries(LAYOUT_KEYS))
            this._addKey(name, () => this._setLayoutForFocus(layout));
        for (const [name, dir] of Object.entries(MOVE_KEYS))
            this._addKey(name, () => this._swapFocus(dir));
        this._addKey('toggle-float', () => this._toggleFloatFocus());
        this._addKey('cycle-layout', () => this._cycleLayoutForFocus());

        // Adopt already-open windows (e.g. after a shell restart / extension reload).
        for (const actor of global.get_window_actors())
            this._trackWindow(actor.meta_window);
        this._rebuildAll();
    }

    disable() {
        for (const name of [...Object.keys(LAYOUT_KEYS), ...Object.keys(MOVE_KEYS), 'toggle-float', 'cycle-layout'])
            Main.wm.removeKeybinding(name);
        for (const [obj, id] of this._handles)
            obj.disconnect(id);
        this._handles = [];
        for (const [win, ids] of this._winSignals)
            ids.forEach(id => win.disconnect(id));
        this._winSignals.clear();
        for (const id of this._reflowIds.values())
            GLib.source_remove(id);
        this._reflowIds.clear();
        this._endDrag();
        this._overlay.hide();
        this._overlay = null;
        this._settings = null;
        this._states = this._slots = this._winKey = null;
    }

    // ---- settings / persistence ------------------------------------------

    _addKey(name, handler) {
        Main.wm.addKeybinding(name, this._settings, Meta.KeyBindingFlags.NONE,
            Shell.ActionMode.NORMAL, handler);
    }

    _loadStates() {
        this._states.clear();
        let data = {};
        try {
            data = JSON.parse(this._settings.get_string('workspace-layouts')) ?? {};
        } catch (e) {
            console.warn(`iron-tiling: ignoring invalid workspace-layouts: ${e}`);
        }
        for (const [key, s] of Object.entries(data)) {
            const st = s?.layout === NONE ? {layout: NONE} : L.sanitizeState(s);
            if (st)
                this._states.set(key, st);
        }
        const def = this._settings.get_string('default-layout');
        this._defaultLayout = L.LAYOUTS[def] ? def : null;
    }

    _saveStates() {
        const obj = {};
        for (const [k, v] of this._states)
            obj[k] = v;
        this._savingLayouts = true;
        this._settings.set_string('workspace-layouts', JSON.stringify(obj));
        this._savingLayouts = false;
    }

    _stateFor(key) {
        if (this._states.has(key)) {
            const st = this._states.get(key);
            return st.layout === NONE ? null : st;
        }
        if (this._defaultLayout) {
            const st = L.defaultState(this._defaultLayout);
            this._states.set(key, st);
            return st;
        }
        return null;
    }

    // ---- geometry helpers --------------------------------------------------

    _keyOf(win) {
        const ws = win.get_workspace();
        if (!ws)
            return null;
        return `${ws.index()}:${win.get_monitor()}`;
    }

    _areaFor(key) {
        const [wsIdx, mon] = key.split(':').map(Number);
        const ws = global.workspace_manager.get_workspace_by_index(wsIdx);
        if (!ws || mon >= global.display.get_n_monitors())
            return null;
        return ws.get_work_area_for_monitor(mon);
    }

    _gaps() {
        return [this._settings.get_int('inner-gap'), this._settings.get_int('outer-gap')];
    }

    _rectsFor(key, state) {
        const area = this._areaFor(key);
        if (!area || !state)
            return null;
        const [ig, og] = this._gaps();
        return L.tileRects(area, state, ig, og);
    }

    // ---- window tracking ---------------------------------------------------

    _onWindowCreated(win) {
        // Wait for the first frame so the window has its real size/monitor.
        const actor = win.get_compositor_private();
        if (!actor) {
            this._trackWindow(win);
            return;
        }
        const id = actor.connect('first-frame', () => {
            actor.disconnect(id);
            if (!this._states)
                return;
            this._trackWindow(win);
            const key = this._keyOf(win);
            if (key && this._stateFor(key) && isTileable(win) && !this._isFloating(win))
                this._insert(win, key, -1);
        });
    }

    _trackWindow(win) {
        if (!win || this._winSignals.has(win) || win.get_window_type() !== Meta.WindowType.NORMAL)
            return;
        const ids = [
            win.connect('unmanaged', () => this._untrackWindow(win)),
            win.connect('workspace-changed', () => this._relocate(win)),
            win.connect('notify::minimized', () => this._relocate(win)),
            win.connect('notify::fullscreen', () => this._relocate(win)),
        ];
        // Some windows switch monitor without a workspace change.
        ids.push(win.connect('position-changed', () => {
            if (this._drag?.win === win)
                return;
            const key = this._winKey.get(win);
            if (key && key !== this._keyOf(win))
                this._relocate(win);
        }));
        this._winSignals.set(win, ids);
    }

    _untrackWindow(win) {
        this._remove(win);
        const ids = this._winSignals.get(win);
        if (ids)
            ids.forEach(id => win.disconnect(id));
        this._winSignals.delete(win);
    }

    _isFloating(win) {
        return win._ironTilingFloat === true;
    }

    _relocate(win) {
        const oldKey = this._winKey.get(win);
        const newKey = this._keyOf(win);
        if (oldKey === newKey && isTileable(win))
            return;
        this._remove(win);
        if (newKey && isTileable(win) && !this._isFloating(win) && this._stateFor(newKey))
            this._insert(win, newKey, -1);
    }

    _slotsFor(key) {
        const state = this._stateFor(key);
        if (!state)
            return null;
        let slots = this._slots.get(key);
        const n = L.tileCount(state);
        if (!slots) {
            slots = new Array(n).fill(null);
            this._slots.set(key, slots);
        } else if (slots.length !== n) {
            // Layout changed: keep window order, drop extras to floating.
            const wins = slots.filter(Boolean);
            slots = new Array(n).fill(null);
            wins.forEach((w, i) => {
                if (i < n)
                    slots[i] = w;
                else
                    this._winKey.delete(w);
            });
            this._slots.set(key, slots);
        }
        return slots;
    }

    // Insert into tile `index` (or the first free tile if -1). Windows beyond
    // the tile count stay floating - predictable for fixed grids.
    _insert(win, key, index) {
        const slots = this._slotsFor(key);
        if (!slots)
            return false;
        const i = index >= 0 ? index : slots.indexOf(null);
        if (i < 0)
            return false;
        const occupant = slots[i];
        const prev = this._winKey.get(win) === key ? slots.indexOf(win) : -1;
        if (prev >= 0)
            slots[prev] = occupant && occupant !== win ? occupant : null;
        else if (occupant && occupant !== win)
            this._winKey.delete(occupant);
        slots[i] = win;
        this._winKey.set(win, key);
        this._scheduleReflow(key);
        return true;
    }

    _remove(win) {
        const key = this._winKey.get(win);
        if (!key)
            return;
        this._winKey.delete(win);
        const slots = this._slots.get(key);
        if (!slots)
            return;
        const i = slots.indexOf(win);
        if (i >= 0) {
            // Compact: later windows shift forward to fill the gap.
            slots.splice(i, 1);
            slots.push(null);
        }
        this._scheduleReflow(key);
    }

    _rebuildAll() {
        if (!this._states)
            return;
        this._slots.clear();
        this._winKey.clear();
        const wins = global.display.list_all_windows()
            .filter(w => isTileable(w) && !this._isFloating(w))
            .sort((a, b) => a.get_stable_sequence() - b.get_stable_sequence());
        for (const w of wins) {
            this._trackWindow(w);
            const key = this._keyOf(w);
            if (key && this._stateFor(key))
                this._insert(w, key, -1);
        }
    }

    // ---- placement ---------------------------------------------------------

    _scheduleReflow(key) {
        if (this._reflowIds.has(key))
            return;
        this._reflowIds.set(key, GLib.idle_add(GLib.PRIORITY_DEFAULT_IDLE, () => {
            this._reflowIds.delete(key);
            this._reflow(key);
            return GLib.SOURCE_REMOVE;
        }));
    }

    _reflowAll() {
        if (!this._slots)
            return;
        for (const key of this._slots.keys())
            this._scheduleReflow(key);
    }

    _reflow(key) {
        const state = this._stateFor(key);
        const slots = this._slots?.get(key);
        if (!state || !slots)
            return;
        const rects = this._rectsFor(key, state);
        if (!rects)
            return;
        slots.forEach((win, i) => {
            if (win && rects[i])
                this._place(win, rects[i]);
        });
    }

    _place(win, rect, animate = true) {
        if (win.is_maximized())
            win.unmaximize();
        const old = win.get_frame_rect();
        let {x, y, width, height} = rect;
        if (!win.allows_resize()) {
            // Fixed-size windows are centred in their tile instead.
            x += Math.max(0, Math.floor((width - old.width) / 2));
            y += Math.max(0, Math.floor((height - old.height) / 2));
            width = old.width;
            height = old.height;
        }
        if (old.x === x && old.y === y && old.width === width && old.height === height)
            return;
        win.move_resize_frame(false, x, y, width, height);
        const actor = win.get_compositor_private();
        if (animate && actor && !this._drag) {
            // Slide from the old position; size changes immediately. GPU-composited
            // translation only, and St scales the duration to 0 when animations are off.
            actor.remove_transition('translation-x');
            actor.remove_transition('translation-y');
            actor.translation_x = old.x - x;
            actor.translation_y = old.y - y;
            actor.ease({
                translation_x: 0, translation_y: 0,
                duration: ANIM_MS, mode: Clutter.AnimationMode.EASE_OUT_QUAD,
            });
        }
    }

    // ---- layout commands ---------------------------------------------------

    _focusKey() {
        const win = global.display.get_focus_window();
        if (win && this._keyOf(win))
            return this._keyOf(win);
        const ws = global.workspace_manager.get_active_workspace();
        return `${ws.index()}:${global.display.get_current_monitor()}`;
    }

    setLayout(key, layoutId) {
        const prev = this._states.get(key);
        if (layoutId)
            this._states.set(key, prev?.layout === layoutId ? prev : L.defaultState(layoutId));
        else if (this._defaultLayout)
            this._states.set(key, {layout: NONE}); // override the default layout
        else
            this._states.delete(key);
        this._saveStates();
        const [wsIdx, mon] = key.split(':').map(Number);
        this._slots.delete(key);
        for (const [w, k] of [...this._winKey]) {
            if (k === key)
                this._winKey.delete(w);
        }
        if (!this._stateFor(key)) {
            this._notify(`Tiling off on workspace ${wsIdx + 1}`);
            return;
        }
        const wins = global.display.list_all_windows()
            .filter(w => isTileable(w) && !this._isFloating(w) &&
                w.get_workspace()?.index() === wsIdx && w.get_monitor() === mon)
            .sort((a, b) => a.get_stable_sequence() - b.get_stable_sequence());
        wins.forEach(w => this._insert(w, key, -1));
        this._notify(`${L.LAYOUTS[layoutId].label} on workspace ${wsIdx + 1}`);
    }

    _setLayoutForFocus(layoutId) {
        this.setLayout(this._focusKey(), layoutId);
    }

    _cycleLayoutForFocus() {
        const key = this._focusKey();
        const ids = [null, ...Object.keys(L.LAYOUTS)];
        const cur = this._stateFor(key)?.layout ?? null;
        this.setLayout(key, ids[(ids.indexOf(cur) + 1) % ids.length]);
    }

    _swapFocus(dir) {
        const win = global.display.get_focus_window();
        const key = win && this._winKey.get(win);
        if (!key)
            return;
        const slots = this._slots.get(key);
        const i = slots.indexOf(win);
        const j = L.neighbour(this._stateFor(key), i, dir);
        if (j < 0)
            return;
        [slots[i], slots[j]] = [slots[j], slots[i]];
        this._scheduleReflow(key);
    }

    _toggleFloatFocus() {
        const win = global.display.get_focus_window();
        if (!win || !isTileable(win))
            return;
        win._ironTilingFloat = !this._isFloating(win);
        if (win._ironTilingFloat) {
            this._remove(win);
        } else {
            const key = this._keyOf(win);
            if (key && this._stateFor(key))
                this._insert(win, key, -1);
        }
    }

    _notify(text) {
        Main.osdWindowManager.showAll(null, text, null, null);
    }

    // ---- drag to snap / resize --------------------------------------------

    _onGrabBegin(win, op) {
        if (!win || !this._settings.get_boolean('enabled'))
            return;
        const moving = op === Meta.GrabOp.MOVING || op === Meta.GrabOp.MOVING_UNCONSTRAINED;
        const resizing = RESIZE_OPS.has(op);
        const key = this._winKey.get(win);
        this._drag = {win, op, moving, resizing, key, target: null};
        if (moving) {
            this._drag.timer = GLib.timeout_add(GLib.PRIORITY_DEFAULT, 30, () => {
                this._updateDrag();
                return GLib.SOURCE_CONTINUE;
            });
        }
    }

    _snapModifierHeld(mods) {
        const m = MODIFIERS[this._settings.get_string('snap-modifier')] ?? MODIFIERS.ctrl;
        return (mods & m) !== 0;
    }

    _updateDrag() {
        const d = this._drag;
        if (!d)
            return;
        const [px, py, mods] = global.get_pointer();
        const mon = Math.max(0, Main.layoutManager.monitors.findIndex(m =>
            px >= m.x && px < m.x + m.width && py >= m.y && py < m.y + m.height));
        const ws = global.workspace_manager.get_active_workspace();
        const key = `${ws.index()}:${mon}`;
        const area = ws.get_work_area_for_monitor(mon);
        const [ig, og] = this._gaps();
        const state = this._stateFor(key);

        if (state || this._snapModifierHeld(mods)) {
            const st = state ?? L.defaultState(this._settings.get_string('snap-layout')) ?? L.defaultState('columns-2');
            const rects = L.tileRects(area, st, ig, og);
            const zone = L.zoneAt(rects, px, py);
            d.target = zone >= 0 ? {kind: 'zone', key, zone, rect: rects[zone], tiled: !!state} : null;
            this._overlay.show(rects, zone);
            return;
        }
        if (this._settings.get_boolean('edge-snap')) {
            const t = L.edgeSnapTarget(area, px, py);
            const rect = t && L.edgeSnapRect(area, t, ig, og);
            d.target = rect ? {kind: 'edge', edge: t, rect} : null;
            this._overlay.show(rect ? [rect] : [], rect ? 0 : -1);
            return;
        }
        d.target = null;
        this._overlay.hide();
    }

    _endDrag() {
        if (this._drag?.timer)
            GLib.source_remove(this._drag.timer);
        this._drag = null;
        this._overlay?.hide();
    }

    _onGrabEnd(win, _op) {
        const d = this._drag;
        if (!d || d.win !== win) {
            this._endDrag();
            return;
        }
        if (d.moving) {
            this._updateDrag();
            const t = d.target;
            this._endDrag();
            if (t?.kind === 'zone' && t.tiled) {
                if (this._winKey.get(win) && this._winKey.get(win) !== t.key)
                    this._remove(win);
                win._ironTilingFloat = false;
                this._insert(win, t.key, t.zone);
            } else if (t?.kind === 'edge' && t.edge === 'top') {
                this._remove(win);
                win.maximize();
            } else if (t) {
                // Snap on a floating workspace: place the window but keep it floating.
                this._remove(win);
                this._place(win, t.rect, false);
            } else if (d.key) {
                // Dragged a tiled window to nowhere: return it to its tile.
                this._scheduleReflow(d.key);
            }
            return;
        }
        this._endDrag();
        if (d.resizing && d.key) {
            const state = this._stateFor(d.key);
            const slots = this._slots.get(d.key);
            const idx = slots ? slots.indexOf(win) : -1;
            const area = this._areaFor(d.key);
            if (state && idx >= 0 && area) {
                const [ig, og] = this._gaps();
                const oldRect = L.tileRects(area, state, ig, og)[idx];
                const ns = L.stateAfterResize(state, area, idx, oldRect, win.get_frame_rect(), ig, og);
                this._states.set(d.key, ns);
                this._saveStates();
            }
            this._scheduleReflow(d.key);
        }
    }
}
