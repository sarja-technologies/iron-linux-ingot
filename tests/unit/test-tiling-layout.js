// Run: gjs -m tests/unit/test-tiling-layout.js
import System from 'system';
import * as L from '../../desktop/shell/extensions/iron-tiling@ironlinux.org/layout.js';

let failures = 0, passed = 0;
function check(name, cond, detail = '') {
    if (cond) {
        passed++;
    } else {
        failures++;
        print(`FAIL ${name} ${detail}`);
    }
}
const eq = (a, b) => JSON.stringify(a) === JSON.stringify(b);
const near = (a, b, e = 1e-9) => Math.abs(a - b) < e;
const area = {x: 0, y: 32, width: 1920, height: 1048};

// Every layout tiles the area exactly: no overlap, full coverage with gaps 0.
for (const id of Object.keys(L.LAYOUTS)) {
    const s = L.defaultState(id);
    const rects = L.tileRects(area, s, 0, 0);
    check(`${id} count`, rects.length === L.LAYOUTS[id].cols * L.LAYOUTS[id].rows);
    const total = rects.reduce((a, r) => a + r.width * r.height, 0);
    check(`${id} coverage`, total === area.width * area.height, `${total}`);
    for (let i = 0; i < rects.length; i++) {
        for (let j = i + 1; j < rects.length; j++) {
            const a = rects[i], b = rects[j];
            const overlap = a.x < b.x + b.width && b.x < a.x + a.width && a.y < b.y + b.height && b.y < a.y + a.height;
            check(`${id} no overlap ${i},${j}`, !overlap);
        }
    }
}

// Gaps: outer margin respected and inner gap exact between neighbours.
{
    const r = L.tileRects(area, L.defaultState('columns-3'), 10, 16);
    check('gap outer left', r[0].x === 16);
    check('gap outer top', r[0].y === 48);
    check('gap inner', r[1].x - (r[0].x + r[0].width) === 10);
    check('gap inner 2', r[2].x - (r[1].x + r[1].width) === 10);
    check('gap outer right', r[2].x + r[2].width === 1920 - 16);
    check('gap outer bottom', r[0].y + r[0].height === 32 + 1048 - 16);
}

// 2x2 row-major order: two windows above, two below.
{
    const r = L.tileRects(area, L.defaultState('grid-2x2'));
    check('2x2 order top', r[0].y === r[1].y && r[0].x < r[1].x);
    check('2x2 order bottom', r[2].y === r[3].y && r[2].y > r[0].y);
}

// 3x3: three per row.
{
    const r = L.tileRects(area, L.defaultState('grid-3x3'));
    check('3x3 rows', r[0].y === r[2].y && r[3].y > r[2].y && r[6].y > r[3].y && r[8].y === r[6].y);
}

// zoneAt
{
    const r = L.tileRects(area, L.defaultState('columns-2'));
    check('zoneAt left', L.zoneAt(r, 10, 100) === 0);
    check('zoneAt right', L.zoneAt(r, 1900, 100) === 1);
    check('zoneAt outside', L.zoneAt(r, 10, 0) === -1);
}

// moveBoundary clamps to MIN_RATIO and preserves the sum.
{
    const out = L.moveBoundary([0.5, 0.5], 0, 0.99);
    check('clamp', near(out[1], L.MIN_RATIO), JSON.stringify(out));
    check('sum', near(out[0] + out[1], 1));
    const out3 = L.moveBoundary([1 / 3, 1 / 3, 1 / 3], 1, 0.8);
    check('3col boundary', near(out3[0], 1 / 3) && near(out3[1], 0.8 - 1 / 3) && near(out3[2], 0.2), JSON.stringify(out3));
}

// Resizing the left tile's right edge moves the column boundary.
{
    const s = L.defaultState('columns-2');
    const rects = L.tileRects(area, s, 8, 8);
    const old = rects[0];
    const resized = {...old, width: old.width + 300};
    const ns = L.stateAfterResize(s, area, 0, old, resized, 8, 8);
    const nr = L.tileRects(area, ns, 8, 8);
    check('resize follows edge', Math.abs(nr[0].x + nr[0].width - (resized.x + resized.width)) <= 1,
        `${nr[0].x + nr[0].width} vs ${resized.x + resized.width}`);
    check('resize neighbour shrinks', nr[1].width < rects[1].width);
    check('resize keeps gap', nr[1].x - (nr[0].x + nr[0].width) === 8);
}

// Resizing the right tile's left edge moves the same boundary.
{
    const s = L.defaultState('columns-3');
    const rects = L.tileRects(area, s, 8, 8);
    const old = rects[2];
    const resized = {...old, x: old.x - 200, width: old.width + 200};
    const ns = L.stateAfterResize(s, area, 2, old, resized, 8, 8);
    const nr = L.tileRects(area, ns, 8, 8);
    check('left-edge resize', Math.abs(nr[2].x - resized.x) <= 1, `${nr[2].x} vs ${resized.x}`);
    check('left-edge untouched first col', near(ns.cols[0], 1 / 3));
}

// Grid row resize.
{
    const s = L.defaultState('grid-2x2');
    const rects = L.tileRects(area, s, 0, 0);
    const old = rects[0];
    const ns = L.stateAfterResize(s, area, 0, old, {...old, height: old.height - 200}, 0, 0);
    check('row resize', ns.rows[0] < 0.5 && near(ns.rows[0] + ns.rows[1], 1));
}

// sanitizeState repairs bad input.
{
    check('sanitize bad layout', L.sanitizeState({layout: 'cube'}) === null);
    const s = L.sanitizeState({layout: 'columns-2', cols: [2, 2], rows: 'x'});
    check('sanitize normalises', eq(s.cols, [0.5, 0.5]) && eq(s.rows, [1]));
}

// Neighbours.
{
    const s = L.defaultState('grid-3x3');
    check('neigh right', L.neighbour(s, 4, 'right') === 5);
    check('neigh up', L.neighbour(s, 4, 'up') === 1);
    check('neigh edge', L.neighbour(s, 2, 'right') === -1);
}

// Edge snap.
{
    check('edge left', L.edgeSnapTarget(area, 0, 500) === 'left');
    check('edge top-right', L.edgeSnapTarget(area, 1919, 40) === 'top-right');
    check('edge top', L.edgeSnapTarget(area, 900, 33) === 'top');
    check('edge none', L.edgeSnapTarget(area, 900, 500) === null);
    const r = L.edgeSnapRect(area, 'right', 0, 0);
    check('edge rect right', r.x === 960 && r.width === 960);
}

print(`tiling-layout: ${passed} passed, ${failures} failed`);
if (failures)
    System.exit(1);
