// Iron Tiling - pure layout geometry (no GNOME imports, unit-tested with `gjs -m`).
//
// A layout is a grid of `cols` x `rows` tiles whose column widths and row
// heights are stored as ratio arrays that each sum to 1. Users resize tiles by
// dragging window edges, which moves a grid boundary.

export const LAYOUTS = {
    'columns-2': {cols: 2, rows: 1, label: 'Two columns'},
    'columns-3': {cols: 3, rows: 1, label: 'Three columns'},
    'grid-2x2': {cols: 2, rows: 2, label: '2 × 2 grid'},
    'grid-3x3': {cols: 3, rows: 3, label: '3 × 3 grid'},
};

export const MIN_RATIO = 0.08;

export function evenRatios(n) {
    return Array.from({length: n}, () => 1 / n);
}

export function defaultState(layoutId) {
    const def = LAYOUTS[layoutId];
    if (!def)
        return null;
    return {layout: layoutId, cols: evenRatios(def.cols), rows: evenRatios(def.rows)};
}

// Validate/repair a persisted state (from JSON). Returns null if unusable.
export function sanitizeState(s) {
    if (!s || typeof s !== 'object' || !LAYOUTS[s.layout])
        return null;
    const def = LAYOUTS[s.layout];
    const fix = (arr, n) => {
        if (!Array.isArray(arr) || arr.length !== n || arr.some(v => typeof v !== 'number' || !(v > 0)))
            return evenRatios(n);
        const sum = arr.reduce((a, b) => a + b, 0);
        return arr.map(v => v / sum);
    };
    return {layout: s.layout, cols: fix(s.cols, def.cols), rows: fix(s.rows, def.rows)};
}

export function tileCount(state) {
    return state.cols.length * state.rows.length;
}

// Split `length` into integer segments proportional to ratios, separated by `gap`.
function segments(start, length, ratios, gap) {
    const usable = length - gap * (ratios.length - 1);
    const out = [];
    let pos = start;
    let acc = 0;
    for (let i = 0; i < ratios.length; i++) {
        acc += ratios[i];
        // Round cumulative edges so segments never drift or overlap.
        const end = i === ratios.length - 1
            ? start + length
            : Math.round(start + usable * acc + gap * i);
        out.push({start: pos, size: end - pos});
        pos = end + gap;
    }
    return out;
}

// area: {x, y, width, height} work area; returns row-major array of rects.
export function tileRects(area, state, innerGap = 0, outerGap = 0) {
    const ax = area.x + outerGap, ay = area.y + outerGap;
    const aw = Math.max(1, area.width - 2 * outerGap);
    const ah = Math.max(1, area.height - 2 * outerGap);
    const xs = segments(ax, aw, state.cols, innerGap);
    const ys = segments(ay, ah, state.rows, innerGap);
    const rects = [];
    for (const r of ys) {
        for (const c of xs)
            rects.push({x: c.start, y: r.start, width: c.size, height: r.size});
    }
    return rects;
}

export function rectContains(r, x, y) {
    return x >= r.x && x < r.x + r.width && y >= r.y && y < r.y + r.height;
}

export function zoneAt(rects, x, y) {
    return rects.findIndex(r => rectContains(r, x, y));
}

// Move boundary `i` (between element i and i+1) so element i ends at fraction f
// of the total. Keeps every element >= MIN_RATIO.
export function moveBoundary(ratios, i, f) {
    if (i < 0 || i >= ratios.length - 1)
        return ratios.slice();
    const before = ratios.slice(0, i).reduce((a, b) => a + b, 0);
    const pairTotal = ratios[i] + ratios[i + 1];
    let left = f - before;
    left = Math.min(Math.max(left, MIN_RATIO), pairTotal - MIN_RATIO);
    const out = ratios.slice();
    out[i] = left;
    out[i + 1] = pairTotal - left;
    return out;
}

// After the user resized the window in tile `index` to `rect`, return a new
// state whose grid boundaries follow the moved edges. Only the edges that
// actually moved (by more than `threshold` px) are applied.
export function stateAfterResize(state, area, index, oldRect, rect, innerGap = 0, outerGap = 0, threshold = 4) {
    const nCols = state.cols.length;
    const c = index % nCols, r = Math.floor(index / nCols);
    const aw = Math.max(1, area.width - 2 * outerGap);
    const ah = Math.max(1, area.height - 2 * outerGap);
    const ax = area.x + outerGap, ay = area.y + outerGap;
    // Fraction along the axis, accounting for the gaps preceding boundary i.
    const fracX = (px, i) => (px - ax - innerGap * i) / (aw - innerGap * (nCols - 1));
    const fracY = (py, i) => (py - ay - innerGap * i) / (ah - innerGap * (state.rows.length - 1));
    let cols = state.cols, rows = state.rows;

    const right = rect.x + rect.width, oldRight = oldRect.x + oldRect.width;
    const bottom = rect.y + rect.height, oldBottom = oldRect.y + oldRect.height;
    if (Math.abs(right - oldRight) > threshold && c < nCols - 1)
        cols = moveBoundary(cols, c, fracX(right, c));
    if (Math.abs(rect.x - oldRect.x) > threshold && c > 0)
        cols = moveBoundary(cols, c - 1, fracX(rect.x - innerGap, c - 1));
    if (Math.abs(bottom - oldBottom) > threshold && r < state.rows.length - 1)
        rows = moveBoundary(rows, r, fracY(bottom, r));
    if (Math.abs(rect.y - oldRect.y) > threshold && r > 0)
        rows = moveBoundary(rows, r - 1, fracY(rect.y - innerGap, r - 1));
    return {layout: state.layout, cols, rows};
}

// Neighbour tile index in a direction, or -1.
export function neighbour(state, index, dir) {
    const nCols = state.cols.length, nRows = state.rows.length;
    const c = index % nCols, r = Math.floor(index / nCols);
    const [dc, dr] = {left: [-1, 0], right: [1, 0], up: [0, -1], down: [0, 1]}[dir] ?? [0, 0];
    const nc = c + dc, nr = r + dr;
    if (nc < 0 || nc >= nCols || nr < 0 || nr >= nRows || (dc === 0 && dr === 0))
        return -1;
    return nr * nCols + nc;
}

// Edge-snap target for a pointer position on a floating workspace.
// Returns 'left' | 'right' | 'top' | 'top-left' | 'top-right' | 'bottom-left' | 'bottom-right' | null.
export function edgeSnapTarget(area, x, y, margin = 12) {
    const left = x <= area.x + margin, right = x >= area.x + area.width - margin - 1;
    const top = y <= area.y + margin;
    const corner = Math.min(area.height / 4, 200);
    const nearTop = y <= area.y + corner, nearBottom = y >= area.y + area.height - corner;
    if (left)
        return nearTop ? 'top-left' : nearBottom ? 'bottom-left' : 'left';
    if (right)
        return nearTop ? 'top-right' : nearBottom ? 'bottom-right' : 'right';
    if (top)
        return 'top';
    return null;
}

export function edgeSnapRect(area, target, innerGap = 0, outerGap = 0) {
    const half = defaultState('columns-2'), quad = defaultState('grid-2x2');
    switch (target) {
    case 'left': return tileRects(area, half, innerGap, outerGap)[0];
    case 'right': return tileRects(area, half, innerGap, outerGap)[1];
    case 'top-left': return tileRects(area, quad, innerGap, outerGap)[0];
    case 'top-right': return tileRects(area, quad, innerGap, outerGap)[1];
    case 'bottom-left': return tileRects(area, quad, innerGap, outerGap)[2];
    case 'bottom-right': return tileRects(area, quad, innerGap, outerGap)[3];
    case 'top': return {x: area.x, y: area.y, width: area.width, height: area.height};
    default: return null;
    }
}
