/* Finalschnitt – Palette „Stege bearbeiten“: reine Logik (ohne DOM, mit node testbar).
   Koordinaten: Welt = Rohteil-mm (X rechts, Y oben), Bildschirm = SVG-Pixel (Y unten). */
(function (root) {
  'use strict';

  function dist(a, b) { return Math.hypot(a[0] - b[0], a[1] - b[1]); }

  function closestOnSeg(q, a, b) {
    var vx = b[0] - a[0], vy = b[1] - a[1], L2 = vx * vx + vy * vy;
    var t = L2 > 0 ? ((q[0] - a[0]) * vx + (q[1] - a[1]) * vy) / L2 : 0;
    t = Math.max(0, Math.min(1, t));
    var p = [a[0] + t * vx, a[1] + t * vy];
    return { pt: p, t: t, d: dist(p, q) };
  }

  /* nächster Punkt auf einem geschlossenen Polygon: {pt, d, i (Segment), s (Bogenlänge)} */
  function closestOnPoly(poly, q) {
    var best = null, s0 = 0;
    for (var i = 0; i < poly.length; i++) {
      var a = poly[i], b = poly[(i + 1) % poly.length];
      var h = closestOnSeg(q, a, b), L = dist(a, b);
      if (!best || h.d < best.d) best = { pt: h.pt, d: h.d, i: i, s: s0 + h.t * L };
      s0 += L;
    }
    return best;
  }

  function perimeter(poly) {
    var s = 0;
    for (var i = 0; i < poly.length; i++) s += dist(poly[i], poly[(i + 1) % poly.length]);
    return s;
  }

  /* 1.3.0: Rohteil quer (ContourNest „quer“): Bildschirm zeigt die Lage auf dem Maschinentisch.
     Welt bleibt das Materialsystem der Planung; Maschine (x, y) = (Breite − v, u). */
  function toMachine(v, p) { return v.quer ? [v.mw - p[1], p[0]] : [p[0], p[1]]; }
  function fromMachine(v, m) { return v.quer ? [m[1], v.mw - m[0]] : [m[0], m[1]]; }
  function dirToMachine(v, d) { return v.quer ? [-d[1], d[0]] : [d[0], d[1]]; }
  /* Ansicht: scale (px/mm), ox/oy = Bildschirm-Lage des Maschinen-Ursprungs. orient/mw: Ausrichtung + Materialbreite */
  function makeView(sheetL, sheetW, wPx, hPx, margin, orient) {
    margin = margin === undefined ? 12 : margin;
    var quer = orient === 'quer', X = quer ? sheetW : sheetL, Y = quer ? sheetL : sheetW;
    var sc = Math.min((wPx - 2 * margin) / X, (hPx - 2 * margin) / Y);
    return { scale: sc, ox: margin, oy: margin + Y * sc, quer: quer, mw: sheetW };
  }
  function machToScreen(v, m) { return [v.ox + m[0] * v.scale, v.oy - m[1] * v.scale]; }
  function screenToMach(v, s) { return [(s[0] - v.ox) / v.scale, (v.oy - s[1]) / v.scale]; }
  function toScreen(v, p) { return machToScreen(v, toMachine(v, p)); }
  function toWorld(v, s) { return fromMachine(v, screenToMach(v, s)); }
  function keep(v, o) { o.quer = !!v.quer; o.mw = v.mw; return o; }
  /* Zoom um einen Bildschirmpunkt (der Punkt darunter bleibt stehen) */
  function zoomAt(v, sx, sy, f) {
    var m = screenToMach(v, [sx, sy]);
    var sc = Math.max(0.02, Math.min(50, v.scale * f));
    return keep(v, { scale: sc, ox: sx - m[0] * sc, oy: sy + m[1] * sc });
  }
  function pan(v, dx, dy) { return keep(v, { scale: v.scale, ox: v.ox + dx, oy: v.oy + dy }); }

  /* Treffer unter dem Mauszeiger (q in Welt-mm, tolPx in Pixeln). Vorrang: Start, Steg/Brücke, Kontur. */
  function hitTest(model, v, q, tolPx) {
    var tol = (tolPx || 8) / v.scale, best = null, i, j, p;
    function take(h, d) { if (d <= tol && (!best || d < best.d - 1e-9)) { h.d = d; best = h; } }
    for (i = 0; i < model.parts.length; i++) {
      p = model.parts[i];
      take({ type: 'start', key: p.key, pt: p.start.pt }, dist(p.start.pt, q) * 0.8);
      (p.hole_starts || []).forEach(function (hs) {
        take({ type: 'start_hole', key: p.key, pt: hs.pt, hole: hs.hole }, dist(hs.pt, q) * 0.85);
      });
    }
    if (best) return best;
    for (i = 0; i < model.parts.length; i++) {
      p = model.parts[i];
      for (j = 0; j < p.tabs.length; j++) {
        var t = p.tabs[j];
        take({ type: t.bridge ? 'bridge' : 'tab', key: p.key, pt: t.pt, manual: t.manual }, dist(t.pt, q));
      }
    }
    if (best) return best;
    for (i = 0; i < model.parts.length; i++) {
      p = model.parts[i];
      var h = closestOnPoly(p.outer, q);
      take({ type: 'contour', key: p.key, pt: h.pt, s: h.s }, h.d);
      (p.holes || []).forEach(function (hole, hi) {
        var hh = closestOnPoly(hole, q);
        take({ type: 'contour_hole', key: p.key, pt: hh.pt, s: hh.s, hole: hi }, hh.d);
      });
    }
    return best || { type: 'none', pt: q };
  }

  /* Klick -> Bearbeitung für Python (oder null) */
  function clickOp(hit, mods, q) {
    mods = mods || {};
    if (mods.shift || mods.alt) return { op: 'bridge_add', pt: q };
    if (!hit) return null;
    if (hit.type === 'bridge') return { op: 'bridge_del', key: hit.key, pt: hit.pt };
    if (hit.type === 'tab') return { op: 'tab_del', key: hit.key, pt: hit.pt };
    if (hit.type === 'contour') return { op: 'tab_add', key: hit.key, pt: hit.pt };
    return null;
  }

  /* Ziehen: Punkt auf die Kontur des eigenen Teils einrasten */
  function snapToPart(model, key, q, hole) {
    var p = partByKey(model, key);
    if (!p) return q;
    if (hole !== undefined && hole !== null && p.holes && p.holes[hole])
      return closestOnPoly(p.holes[hole], q).pt;
    return closestOnPoly(p.outer, q).pt;
  }
  function dragOp(kind, key, from, to, hit) {
    if (kind === 'tab') return { op: 'tab_move', key: key, pt: from, to: to };
    if (kind === 'start') return { op: 'start_set', key: key, pt: from, to: to };
    if (kind === 'bridge') return { op: 'bridge_move', key: key, pt: from, to: to };
    return null;
  }
  function partByKey(model, key) {
    for (var i = 0; i < model.parts.length; i++) if (model.parts[i].key === key) return model.parts[i];
    return null;
  }

  function pointInPoly(poly, q) {
    if (!poly || poly.length < 3 || !q) return false;
    var inside = false, x = q[0], y = q[1], i, j, xi, yi, xj, yj, denom;
    for (i = 0, j = poly.length - 1; i < poly.length; j = i++) {
      xi = poly[i][0]; yi = poly[i][1]; xj = poly[j][0]; yj = poly[j][1];
      denom = yj - yi;
      if (((yi > y) !== (yj > y)) && (x < (xj - xi) * (y - yi) / (denom === 0 ? 1e-15 : denom) + xi))
        inside = !inside;
    }
    return inside;
  }
  function partContains(part, q) {
    if (!part || !pointInPoly(part.outer, q)) return false;
    var holes = part.holes || [], i;
    for (i = 0; i < holes.length; i++) if (pointInPoly(holes[i], q)) return false;
    return true;
  }
  function polyArea(poly) {
    var s = 0, i, j;
    if (!poly || poly.length < 3) return 0;
    for (i = 0, j = poly.length - 1; i < poly.length; j = i++)
      s += (poly[j][0] + poly[i][0]) * (poly[j][1] - poly[i][1]);
    return Math.abs(s / 2);
  }
  function hitPart(model, q) {
    var best = null, bestA = Infinity, i, p, a;
    if (!model || !model.parts) return { type: 'none', pt: q };
    for (i = 0; i < model.parts.length; i++) {
      p = model.parts[i];
      if (!partContains(p, q)) continue;
      a = polyArea(p.outer);
      if (a < bestA) { bestA = a; best = p; }
    }
    return best ? { type: 'part', key: best.key, pt: q } : { type: 'none', pt: q };
  }
  function orderPickStart(keys) {
    return { keys: (keys || []).slice(), picked: [], done: false, cancelled: false };
  }
  function orderPickClick(state, key) {
    if (!state || state.done || state.cancelled) return state;
    if (!key || state.keys.indexOf(key) < 0 || state.picked.indexOf(key) >= 0)
      return { keys: state.keys, picked: state.picked.slice(), done: !!state.done, cancelled: false };
    var picked = state.picked.concat([key]);
    return { keys: state.keys, picked: picked, done: picked.length >= state.keys.length, cancelled: false };
  }
  function orderPickCancel(state) {
    return { keys: (state && state.keys) || [], picked: ((state && state.picked) || []).slice(),
      done: false, cancelled: true };
  }
  function orderPickResult(state) {
    if (!state) return [];
    var seen = {}, out = [];
    (state.picked || []).forEach(function (k) { if (k && !seen[k]) { seen[k] = true; out.push(k); } });
    (state.keys || []).forEach(function (k) { if (k && !seen[k]) { seen[k] = true; out.push(k); } });
    return out;
  }

  var api = { dist: dist, closestOnSeg: closestOnSeg, closestOnPoly: closestOnPoly, perimeter: perimeter,
    makeView: makeView, toScreen: toScreen, toWorld: toWorld, toMachine: toMachine, fromMachine: fromMachine,
    dirToMachine: dirToMachine, machToScreen: machToScreen, screenToMach: screenToMach, zoomAt: zoomAt, pan: pan, hitTest: hitTest,
    clickOp: clickOp, snapToPart: snapToPart, dragOp: dragOp, partByKey: partByKey,
    pointInPoly: pointInPoly, partContains: partContains, hitPart: hitPart,
    orderPickStart: orderPickStart, orderPickClick: orderPickClick, orderPickCancel: orderPickCancel,
    orderPickResult: orderPickResult, DRAG_PX: 4 };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.FSLogic = api;
}(this));
