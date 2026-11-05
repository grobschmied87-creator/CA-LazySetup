/* CA LazySetup 2.0.0 – Vorschau/Stege bearbeiten (vormals Finalschnitt-Palette „Stege bearbeiten“). Logik in fs_logic.js,
   Planung/Speichern in Python. Eingebettet in das Hauptfenster (window.LS_EMBED, main.js); allein lauffähig wie 1.3.1. */
(function () {
  'use strict';
  var LG = window.FSLogic, model = null, view = null, drag = null, lastKey = null, busy = false;
  function $(id) { return document.getElementById(id); }
  function setStatus(t, err) { var s = $('status'); s.textContent = t; s.className = err ? 'err' : ''; }

  function send(action, obj, cb) {
    if (window.LS_EMBED) {                // Hauptfenster: Antwort = {plan: {...}}
      window.LS_EMBED.send(action, obj, function (r) {
        var j = null; try { j = typeof r === 'string' ? JSON.parse(r) : r; } catch (e) { j = null; }
        if (cb) cb(j && j.plan ? JSON.stringify(j.plan) : r);
      });
      return;
    }
    if (!window.adsk || !window.adsk.fusionSendData) { setStatus('Keine Verbindung zu Fusion.', true); return; }
    var res = window.adsk.fusionSendData(action, JSON.stringify(obj || {}));
    var done = function (r) { if (cb) cb(r); };
    if (res && typeof res.then === 'function') res.then(done); else done(res);
  }
  function handleReply(rep) {
    busy = false;
    if (!rep) return;
    try { var j = JSON.parse(rep); if (j && j.parts) load(j); else if (j && j.msgs) showMsgs(j.msgs, []); }
    catch (e) { setStatus(String(rep)); }
  }

  function load(j) {
    var first = !model || !model.sheet || model.sheet.name !== j.sheet.name;
    model = j;
    var sel = $('selSheet'), names = j.sheets || [j.sheet.name];
    if (sel.options.length !== names.length || [].some.call(sel.options, function (o, i) { return o.value !== names[i]; })) {
      sel.innerHTML = '';
      names.forEach(function (n) { var o = document.createElement('option'); o.value = n; o.textContent = n; sel.appendChild(o); });
    }
    sel.value = j.sheet.name;
    if (first || !view) fit();
    render();
    setStatus((j.sheet.label || j.sheet.name) + ' – ' + j.parts.length + ' Teile, ' + j.bridges.length + ' Brücken');
    var lb = $('sheetLabel'); if (lb) lb.textContent = j.sheet.label || '';
    showMsgs(j.msgs || [], j.warnings || []);
    if (window.LS_EMBED && window.LS_EMBED.onPlan) window.LS_EMBED.onPlan(j);
  }
  function showMsgs(msgs, warns) {
    var box = $('msgs'); box.innerHTML = '';
    msgs.concat(warns).forEach(function (m, i) {
      var d = document.createElement('div'); d.textContent = (i >= msgs.length ? '⚠ ' : '') + m;
      if (i >= msgs.length || /Ecke|neben|nahe|Kein|passt/.test(m)) d.className = 'w';
      box.appendChild(d);
    });
  }
  function size() { var r = $('svg').getBoundingClientRect(); return [r.width || 800, r.height || 500]; }
  function fit() { if (!model) return; var s = size(); view = LG.makeView(model.sheet.length, model.sheet.width, s[0], s[1], 12, model.sheet.orient); render(); }

  function pathOf(poly) {
    return poly.map(function (p, i) { var s = LG.toScreen(view, p); return (i ? 'L' : 'M') + s[0].toFixed(1) + ' ' + s[1].toFixed(1); }).join(' ') + ' Z';
  }
  function el(tag, attrs, parent) {
    var e = document.createElementNS('http://www.w3.org/2000/svg', tag);
    for (var k in attrs) e.setAttribute(k, attrs[k]);
    parent.appendChild(e); return e;
  }
  function render() {
    var svg = $('svg'); svg.innerHTML = '';
    if (!model || !view) return;
    var L = model.sheet.length, W = model.sheet.width;
    el('path', { d: pathOf([[0, 0], [L, 0], [L, W], [0, W]]), fill: '#ecdec4', stroke: '#786446', 'stroke-width': 2 }, svg);
    drawZero(svg);
    // 2.0.5: große Teile zuerst; outer+holes evenodd → Teile in Ausschnitten bleiben sichtbar
    var sorted = model.parts.slice().sort(function (a, b) {
      function area(poly) {
        var s = 0, i, j;
        for (i = 0, j = poly.length - 1; i < poly.length; j = i++) s += (poly[j][0] + poly[i][0]) * (poly[j][1] - poly[i][1]);
        return Math.abs(s / 2);
      }
      return area(b.outer) - area(a.outer);
    });
    var n = Math.max(1, sorted.length);
    sorted.forEach(function (p, k) {
      var g = 200 - Math.round(140 * k / n);
      var d = pathOf(p.outer);
      (p.holes || []).forEach(function (h) { d += pathOf(h); });
      el('path', { d: d, fill: p.edited ? '#fff2c2' : 'rgb(' + g + ',' + (225 - Math.round(60 * k / n)) + ',255)',
        'fill-rule': 'evenodd', 'class': 'part', stroke: '#1e3c78', 'stroke-width': 1.6 }, svg);
      (p.holes || []).forEach(function (h) {
        el('path', { d: pathOf(h), fill: 'none', stroke: '#c87800', 'stroke-width': 1.4 }, svg);
      });
      (p.pockets || []).forEach(function (h) { el('path', { d: pathOf(h), fill: 'none', stroke: '#5a78aa', 'stroke-width': 0.8 }, svg); });
    });
    model.bridges.forEach(function (b) {
      var a = LG.toScreen(view, b.pa), c = LG.toScreen(view, b.pb);
      el('line', { x1: a[0], y1: a[1], x2: c[0], y2: c[1], stroke: '#8c00aa', 'stroke-width': 3 }, svg);
    });
    model.parts.forEach(function (p) {
      function drawStart(st, col) {
        if (!st || !st.pt) return;
        var s = LG.toScreen(view, st.pt), d = LG.dirToMachine(view, st.dir || [0, 0]), l = Math.hypot(d[0], d[1]) || 1;
        var e = [s[0] + d[0] / l * 22, s[1] - d[1] / l * 22];
        el('line', { x1: s[0], y1: s[1], x2: e[0], y2: e[1], stroke: col, 'stroke-width': 2 }, svg);
        el('circle', { cx: s[0], cy: s[1], r: st.manual ? 6 : 4.5, fill: col, stroke: st.manual ? '#000' : 'none' }, svg);
      }
      drawStart(p.start, '#c80000');
      (p.hole_starts || []).forEach(function (hs) { drawStart(hs, '#e07000'); });
      p.tabs.forEach(function (t) {
        var q = LG.toScreen(view, t.pt);
        el('circle', { cx: q[0], cy: q[1], r: 5, fill: t.bridge ? '#8c00aa' : (t.manual ? '#00c8c8' : '#008c00'),
          stroke: '#fff', 'stroke-width': 1 }, svg);
      });
      var c = LG.toScreen(view, p.centroid);
      el('circle', { cx: c[0], cy: c[1], r: 11, fill: '#fff' }, svg);
      var tx = el('text', { x: c[0], y: c[1] + 4, 'text-anchor': 'middle', 'font-size': 12, 'font-weight': 'bold' }, svg);
      tx.textContent = String(p.nr);
    });
    if (drag && drag.moved && drag.kind !== 'pan') {
      var q = LG.toScreen(view, drag.to);
      el('circle', { cx: q[0], cy: q[1], r: 6, fill: 'none', stroke: '#000', 'stroke-width': 2 }, svg);
    }
  }

  /* 1.3.0: Nullpunkt des Rohteils (aus ContourNest): Achsenkreuz X rot / Y grün, Kreis gefüllt = Oberseite */
  function drawZero(svg) {
    var sh = model.sheet;
    if (sh.zero_x === undefined || sh.zero_x === null) return;
    var z = LG.machToScreen(view, [sh.zero_x, sh.zero_y]), a = 36;
    var g = el('g', { 'class': 'zero', 'data-zero': sh.zero || '' }, svg);
    var mk = function (x2, y2, c) {
      el('line', { x1: z[0], y1: z[1], x2: x2, y2: y2, stroke: c, 'stroke-width': 2.4 }, g);
      var dx = x2 - z[0], dy = y2 - z[1], l = Math.hypot(dx, dy) || 1, ux = dx / l, uy = dy / l;
      el('path', { d: 'M' + x2 + ' ' + y2 + ' L' + (x2 - ux * 8 - uy * 5) + ' ' + (y2 - uy * 8 + ux * 5) + ' L' + (x2 - ux * 8 + uy * 5) +
        ' ' + (y2 - uy * 8 - ux * 5) + ' Z', fill: c }, g);
    };
    mk(z[0] + a, z[1], '#d00000');
    mk(z[0], z[1] - a, '#008800');
    var tx = el('text', { x: z[0] + a + 4, y: z[1] + 4, 'font-size': 11, fill: '#d00000', 'font-weight': 'bold' }, g); tx.textContent = 'X';
    var ty = el('text', { x: z[0] - 4, y: z[1] - a - 4, 'font-size': 11, fill: '#008800', 'font-weight': 'bold' }, g); ty.textContent = 'Y';
    el('circle', { cx: z[0], cy: z[1], r: 6, fill: sh.zero_side === 'oben' ? '#fff' : 'none', stroke: '#000', 'stroke-width': 1.4,
      'stroke-dasharray': sh.zero_side === 'oben' ? 'none' : '3 2' }, g);
    el('path', { d: 'M' + (z[0] - 10) + ' ' + z[1] + ' L' + (z[0] + 10) + ' ' + z[1] + ' M' + z[0] + ' ' + (z[1] - 10) + ' L' + z[0] + ' ' + (z[1] + 10),
      stroke: '#000', 'stroke-width': 1.2 }, g);
    var t = el('title', {}, g); t.textContent = 'Nullpunkt: ' + (sh.zero_text || '');
  }
  function evPt(ev) { var r = $('svg').getBoundingClientRect(); return [ev.clientX - r.left, ev.clientY - r.top]; }
  function edit(op) {
    if (!op || busy) return;
    busy = true;
    if (op.key) lastKey = op.key;
    setStatus('… ' + op.op);
    op.sheet = model.sheet.name;
    send('edit', op, handleReply);
  }

  function onDown(ev) {
    if (!model) return;
    var sp = evPt(ev), q = LG.toWorld(view, sp), hit = LG.hitTest(model, view, q, 8);
    if (hit.key) lastKey = hit.key;
    var kind = (hit.type === 'tab' || hit.type === 'start' || hit.type === 'start_hole' || hit.type === 'bridge') && !(ev.shiftKey || ev.altKey)
      ? (hit.type === 'start_hole' ? 'start' : hit.type) : 'pan';
    drag = { kind: kind, hit: hit, sp: sp, last: sp, moved: false, from: hit.pt, to: hit.pt,
             mods: { shift: ev.shiftKey, alt: ev.altKey }, q: q };
    ev.preventDefault();
  }
  function onMove(ev) {
    if (!drag) return;
    var sp = evPt(ev);
    if (!drag.moved && Math.hypot(sp[0] - drag.sp[0], sp[1] - drag.sp[1]) > LG.DRAG_PX) drag.moved = true;
    if (!drag.moved) return;
    if (drag.kind === 'pan') {
      if (drag.hit.type === 'none' || drag.hit.type === 'contour') {
        view = LG.pan(view, sp[0] - drag.last[0], sp[1] - drag.last[1]); drag.last = sp; render();
      }
      return;
    }
    var wq = LG.toWorld(view, sp);
    if (drag.kind === 'bridge') drag.to = wq;
    else drag.to = LG.snapToPart(model, drag.hit.key, wq, drag.hit.hole);
    render();
  }
  function onUp() {
    if (!drag) return;
    var d = drag; drag = null;
    if (!d.moved) { edit(LG.clickOp(d.hit, d.mods, d.q)); return; }
    if (d.kind === 'tab' || d.kind === 'start' || d.kind === 'bridge') {
      var op = LG.dragOp(d.kind, d.hit.key, d.from, d.to, d.hit);
      if (op && d.hit.hole !== undefined && d.hit.hole !== null) op.hole = d.hit.hole;
      edit(op);
    }
    else render();
  }
  function onWheel(ev) {
    if (!view) return;
    var sp = evPt(ev);
    view = LG.zoomAt(view, sp[0], sp[1], ev.deltaY < 0 ? 1.2 : 1 / 1.2);
    render(); ev.preventDefault();
  }

  if (!window.LS_EMBED) window.fusionJavaScriptHandler = {
    handle: function (action, data) {
      try {
        if (action === 'plan') load(JSON.parse(data));
        else if (action === 'status') setStatus(data);
        else return 'Unbekannte Aktion: ' + action;
      } catch (e) { setStatus('Fehler: ' + e.message, true); }
      return 'OK';
    }
  };
  function announce(tries) {
    if (window.adsk && window.adsk.fusionSendData) send('ready', {}, handleReply);
    else if (tries < 100) setTimeout(function () { announce(tries + 1); }, 100);
    else setStatus('Keine Verbindung zu Fusion.', true);
  }
  document.addEventListener('DOMContentLoaded', function () {
    var svg = $('svg');
    svg.addEventListener('mousedown', onDown);
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
    svg.addEventListener('wheel', onWheel, { passive: false });
    svg.addEventListener('dblclick', function (ev) {
      var hit = model && LG.hitTest(model, view, LG.toWorld(view, evPt(ev)), 8);
      if (!hit || hit.type === 'none') fit();
    });
    window.addEventListener('resize', fit);
    $('btnFit').onclick = fit;
    $('selSheet').onchange = function () { send('sheet', { name: $('selSheet').value }, handleReply); };
    $('btnResetPart').onclick = function () {
      if (lastKey) edit({ op: 'reset_part', key: lastKey }); else setStatus('Erst ein Teil anklicken.', true);
    };
    $('btnResetAll').onclick = function () { edit({ op: 'reset_all' }); };
    if ($('btnClose')) $('btnClose').onclick = function () { send('close', {}); };
    if (!window.LS_EMBED) announce(0);
  });
  window.FinalschnittPalette = { model: function () { return model; }, view: function () { return view; }, load: load, fit: fit,
    clear: function () { model = null; view = null; render(); } };
}());
