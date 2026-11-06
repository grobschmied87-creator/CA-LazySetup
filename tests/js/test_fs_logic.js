// node-Test der Palettenlogik (palette/fs_logic.js) – wird von test_fs_120.py aufgerufen
'use strict';
var path = require('path'), assert = require('assert');
var LG = require(path.join(__dirname, '..', '..', 'palette', 'fs_logic.js'));
var n = 0;
function t(name, fn) { fn(); n++; }
function near(a, b, eps, msg) { assert.ok(Math.abs(a - b) <= (eps || 1e-6), (msg || '') + ' ' + a + ' != ' + b); }

var sq = [[0, 0], [100, 0], [100, 50], [0, 50]];
var model = { sheet: { name: 'S', length: 1000, width: 500 }, parts: [
  { key: 'A#1', outer: sq, start: { pt: [100, 25], dir: [1, 0] },
    tabs: [{ pt: [50, 0], bridge: false }, { pt: [0, 25], bridge: true }] },
  { key: 'B#1', outer: [[0, 63], [100, 63], [100, 120], [0, 120]], start: { pt: [50, 120], dir: [0, 1] }, tabs: [] }] };

t('closestOnPoly snaps and gives arc length', function () {
  var h = LG.closestOnPoly(sq, [30, -7]);
  near(h.pt[0], 30); near(h.pt[1], 0); near(h.d, 7); near(h.s, 30);
  h = LG.closestOnPoly(sq, [110, 40]);
  near(h.pt[0], 100); near(h.pt[1], 40); near(h.s, 140);
  near(LG.perimeter(sq), 300);
});
t('view round trip, y flipped, zoom keeps point under cursor', function () {
  var v = LG.makeView(1000, 500, 1024, 524, 12);
  near(v.scale, 1); var s = LG.toScreen(v, [0, 0]); near(s[0], 12); near(s[1], 512);
  var w = LG.toWorld(v, LG.toScreen(v, [123, 45])); near(w[0], 123); near(w[1], 45);
  var before = LG.toWorld(v, [300, 200]), z = LG.zoomAt(v, 300, 200, 2), after = LG.toWorld(z, [300, 200]);
  near(z.scale, 2); near(before[0], after[0]); near(before[1], after[1]);
  var p = LG.pan(v, 10, -5); near(p.ox, v.ox + 10); near(p.oy, v.oy - 5);
});
t('hitTest priorities: start > tab/bridge > contour > none', function () {
  var v = { scale: 2, ox: 0, oy: 0 };
  assert.strictEqual(LG.hitTest(model, v, [101, 26], 8).type, 'start');
  var h = LG.hitTest(model, v, [51, 1], 8); assert.strictEqual(h.type, 'tab'); assert.strictEqual(h.key, 'A#1');
  assert.strictEqual(LG.hitTest(model, v, [1, 24], 8).type, 'bridge');
  h = LG.hitTest(model, v, [70, 2], 8); assert.strictEqual(h.type, 'contour'); near(h.pt[1], 0); near(h.s, 70);
  assert.strictEqual(LG.hitTest(model, v, [50, 25], 8).type, 'none');
  h = LG.hitTest(model, v, [70, 62], 8); assert.strictEqual(h.key, 'B#1');      // nächste Kontur gewinnt
});
t('clickOp maps hits to edits', function () {
  assert.deepStrictEqual(LG.clickOp({ type: 'contour', key: 'A#1', pt: [70, 0] }, {}, [70, 2]),
    { op: 'tab_add', key: 'A#1', pt: [70, 0] });
  assert.strictEqual(LG.clickOp({ type: 'tab', key: 'A#1', pt: [50, 0] }, {}, [50, 1]).op, 'tab_del');
  assert.strictEqual(LG.clickOp({ type: 'bridge', key: 'A#1', pt: [0, 25] }, {}, [0, 25]).op, 'bridge_del');
  assert.deepStrictEqual(LG.clickOp({ type: 'none' }, { shift: true }, [50, 56]), { op: 'bridge_add', pt: [50, 56] });
  assert.strictEqual(LG.clickOp({ type: 'contour', key: 'A#1' }, { alt: true }, [1, 2]).op, 'bridge_add');
  assert.strictEqual(LG.clickOp({ type: 'none' }, {}, [1, 2]), null);
  assert.strictEqual(LG.clickOp({ type: 'start', key: 'A#1' }, {}, [1, 2]), null);
});
t('drag snaps to own contour and builds move ops', function () {
  var q = LG.snapToPart(model, 'A#1', [60, 58]);         // näher an B, rastet trotzdem auf A ein
  near(q[0], 60); near(q[1], 50);
  assert.deepStrictEqual(LG.dragOp('tab', 'A#1', [50, 0], q), { op: 'tab_move', key: 'A#1', pt: [50, 0], to: q });
  assert.strictEqual(LG.dragOp('start', 'A#1', [100, 25], [100, 10]).op, 'start_set');
  assert.strictEqual(LG.dragOp('pan', null, [0, 0], [1, 1]), null);
});
t('1.3.0: quer liegendes Rohteil – Bildschirm = Maschinentisch, Welt = Materialsystem', function () {
  // Material 1000 × 500 quer: Maschine 500 (X) × 1000 (Y); Maschine (x, y) = (500 − v, u)
  var v = LG.makeView(1000, 500, 524, 1024, 12, 'quer');
  near(v.scale, 1); assert.ok(v.quer && v.mw === 500);
  var s = LG.toScreen(v, [0, 0]); near(s[0], 12 + 500); near(s[1], 1012);           // Materialursprung rechts vorn
  s = LG.toScreen(v, [1000, 0]); near(s[0], 512); near(s[1], 12);                    // Länge zeigt nach +Y (oben)
  var w = LG.toWorld(v, LG.toScreen(v, [123, 45])); near(w[0], 123); near(w[1], 45);
  var m = LG.toMachine(v, [123, 45]); near(m[0], 455); near(m[1], 123);
  var b = LG.fromMachine(v, m); near(b[0], 123); near(b[1], 45);
  var d = LG.dirToMachine(v, [1, 0]); near(d[0], 0); near(d[1], 1);
  var before = LG.toWorld(v, [300, 200]), z = LG.zoomAt(v, 300, 200, 2), after = LG.toWorld(z, [300, 200]);
  near(before[0], after[0]); near(before[1], after[1]); assert.ok(z.quer && z.mw === 500);
  var p = LG.pan(z, 5, 5); assert.ok(p.quer && p.mw === 500);
  // Treffer im Materialsystem trotz gedrehter Ansicht
  var h = LG.hitTest(model, v, LG.toWorld(v, LG.toScreen(v, [50, 2])), 8);
  assert.strictEqual(h.type, 'tab'); assert.strictEqual(h.key, 'A#1');
  // längs unverändert
  var vl = LG.makeView(1000, 500, 1024, 524, 12, 'laengs'); s = LG.toScreen(vl, [0, 0]); near(s[0], 12); near(s[1], 512);
});
t('pointInPoly / partContains / hitPart (interior, holes, innermost)', function () {
  assert.strictEqual(LG.pointInPoly(sq, [50, 25]), true);
  assert.strictEqual(LG.pointInPoly(sq, [50, -1]), false);
  var withHole = { key: 'H#1', outer: [[0, 0], [100, 0], [100, 100], [0, 100]],
    holes: [[[20, 20], [80, 20], [80, 80], [20, 80]]] };
  assert.strictEqual(LG.partContains(withHole, [10, 10]), true);
  assert.strictEqual(LG.partContains(withHole, [50, 50]), false);
  var inner = { key: 'IN#1', outer: [[30, 30], [70, 30], [70, 70], [30, 70]], holes: [] };
  var nest = { parts: [withHole, inner] };
  assert.strictEqual(LG.hitPart(nest, [50, 50]).key, 'IN#1');
  assert.strictEqual(LG.hitPart(nest, [10, 10]).key, 'H#1');
  assert.strictEqual(LG.hitPart(nest, [200, 200]).type, 'none');
  assert.strictEqual(LG.hitPart(model, [50, 25]).key, 'A#1');
});
t('orderPick: click order, ignore dups, done when all clicked, rest appended', function () {
  var st = LG.orderPickStart(['a', 'b', 'c']);
  assert.strictEqual(st.done, false);
  st = LG.orderPickClick(st, 'b');
  assert.deepStrictEqual(st.picked, ['b']);
  st = LG.orderPickClick(st, 'b');
  assert.deepStrictEqual(st.picked, ['b']);
  st = LG.orderPickClick(st, 'nope');
  assert.deepStrictEqual(st.picked, ['b']);
  assert.deepStrictEqual(LG.orderPickResult(st), ['b', 'a', 'c']);
  st = LG.orderPickClick(st, 'a');
  st = LG.orderPickClick(st, 'c');
  assert.strictEqual(st.done, true);
  assert.deepStrictEqual(st.picked, ['b', 'a', 'c']);
  assert.deepStrictEqual(LG.orderPickResult(st), ['b', 'a', 'c']);
  var c = LG.orderPickCancel(st);
  assert.strictEqual(c.cancelled, true);
  assert.strictEqual(c.done, false);
});
console.log('JS OK ' + n);
