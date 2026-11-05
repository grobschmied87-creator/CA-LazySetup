/* CA LazySetup 2.0.0 – Hauptfenster (Register, Einstellungen, Rohteile, Werkzeug, Ergebnis).
   Vorschau/Stege bearbeiten: editor.js (eingebettet über window.LS_EMBED). Infobox/Theme: ca_core/web/ca_shell.js. */
(function () {
  'use strict';
  var TABS = ['Rohteile', 'Werkzeug', 'Bearbeitung', 'Stege', 'Vorschau', 'Ergebnis'];
  var S = { session: null, fields: [], cfg: {}, sheets: [], tools: null, tab: 'Rohteile', timer: null, plan: null };
  function $(id) { return document.getElementById(id); }
  function el(tag, attrs, parent, text) {
    var e = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) { if (k === 'className') e.className = attrs[k]; else e.setAttribute(k, attrs[k]); });
    if (text !== undefined && text !== null) e.textContent = text;
    if (parent) parent.appendChild(e);
    return e;
  }
  function parse(r) { if (r === null || r === undefined) return null; if (typeof r !== 'string') return r; try { return JSON.parse(r); } catch (e) { return r; } }
  function send(action, obj, cb) {
    if (!window.adsk || !window.adsk.fusionSendData) { status((window.CA_I18n && CA_I18n.t('status.no_fusion')) || 'Keine Verbindung zu Fusion.', true); return; }
    var res = window.adsk.fusionSendData(action, JSON.stringify(obj || {}));
    var done = function (r) { if (cb) cb(r); };
    if (res && typeof res.then === 'function') res.then(done); else done(res);
  }
  function status(t, err) { var s = $('status'); s.textContent = t || ''; s.className = err ? 'err' : ''; }
  function notice(level, text, list) {
    var n = $('notice');
    if (!text) { n.hidden = true; return; }
    n.className = 'notice ' + (level || 'info'); n.innerHTML = '';
    el('span', {}, n, text);
    if (list && list.length) { var ul = el('ul', {}, n); list.slice(0, 8).forEach(function (s) { el('li', {}, ul, s); }); }
    var x = el('button', { className: 'icon close', title: 'Ausblenden' }, n, '✕'); x.onclick = function () { n.hidden = true; };
    n.hidden = false;
  }


  function ensureLangSelect() {
    if ($('langSel')) return $('langSel');
    var hdr = $('hdr'); if (!hdr) return null;
    var sel = document.createElement('select');
    sel.id = 'langSel'; sel.className = 'lang';
    sel.style.cssText = 'margin-left:auto;max-width:7.5rem;font-size:12px;';
    hdr.insertBefore(sel, $('btnInfo') || null);
    sel.addEventListener('change', function () {
      send('language', { language: sel.value }, function (r) {
        var d = parse(r) || {};
        if (d.i18n) applyI18n(d.i18n);
        if (d.fields && d.groups) { buildFields(d.fields, d.groups); fillCfg(S.cfg); }
      });
    });
    return sel;
  }
  function applyI18n(payload) {
    if (!payload || !window.CA_I18n) return;
    CA_I18n.set(payload);
    CA_I18n.apply(document);
    var sel = ensureLangSelect();
    if (sel) CA_I18n.fillSelect(sel, payload.language);
    var map = { 'Rohteile': 'tab_parts', 'Werkzeug': 'tab_tool', 'Bearbeitung': 'tab_machining',
      'Stege': 'tab_tabs', 'Vorschau': 'tab_preview', 'Ergebnis': 'tab_result' };
    document.querySelectorAll('#tabs .tab').forEach(function (btn) {
      var k = map[btn.getAttribute('data-tab')]; if (!k) return;
      var sp = btn.querySelector('span'); if (sp) sp.textContent = CA_I18n.t(k);
    });
    if ($('btnRun')) $('btnRun').textContent = CA_I18n.t('run_ops');
    if ($('btnInfo')) $('btnInfo').title = CA_I18n.t('info');
    document.querySelectorAll('.btnPreviewUpdate').forEach(function (b) {
      b.textContent = CA_I18n.t('btn.refresh_preview');
    });
    if ($('btnRefresh')) $('btnRefresh').textContent = CA_I18n.t('btn.refresh');
  }

  // ---------------------------------------------------------------- Register
  function showTab(name, persist) {
    if (TABS.indexOf(name) < 0) name = 'Rohteile';
    S.tab = name;
    Array.prototype.forEach.call(document.querySelectorAll('#tabs .tab'), function (b) { b.classList.toggle('on', b.getAttribute('data-tab') === name); });
    Array.prototype.forEach.call(document.querySelectorAll('.pane'), function (p) { p.hidden = p.getAttribute('data-pane') !== name; });
    if (name === 'Vorschau' && window.FinalschnittPalette) setTimeout(function () { window.FinalschnittPalette.fit(); }, 0);
    if (persist) send('tab', { tab: name });
  }

  // ---------------------------------------------------------------- Felder
  function buildFields(fields, groups) {
    S.fields = fields;
    groups.forEach(function (g) {
      var host = $('grp_' + g[0]); if (!host) return;
      host.innerHTML = '';
      var fs = el('fieldset', {}, host); el('legend', {}, fs, g[1]);
      var grid = el('div', { className: 'fgrid' }, fs);
      fields.filter(function (f) { return f.group === g[0]; }).forEach(function (f) {
        if (f.kind === 'h') {
          el('div', { className: 'fsub' }, grid, f.label);
          return;
        }
        var id = 'f_' + f.key, inp;
        if (f.kind === 'b') {
          var lb = el('label', { className: 'check' }, grid);
          inp = el('input', { id: id, type: 'checkbox' }, lb); lb.appendChild(document.createTextNode(' ' + f.label));
        } else {
          var l2 = el('label', {}, grid, f.label);
          if (f.kind === 'd') {
            inp = el('select', { id: id }, l2);
            f.options.forEach(function (o) { el('option', { value: o[0] }, inp, o[1]); });
          } else {
            inp = el('input', { id: id, type: 'number', min: f.min, max: f.max, step: f.step }, l2);
          }
        }
        // Zahlen nur über „Aktualisieren“; Checkbox/Select sofort
        if (f.kind === 'b' || f.kind === 'd') {
          inp.addEventListener('change', changed);
        } else {
          inp.addEventListener('change', markDirty);
          inp.addEventListener('input', markDirty);
        }
      });
    });
  }
  function fillCfg(cfg) {
    S.cfg = cfg || {};
    S.fields.forEach(function (f) {
      if (f.kind === 'h') return;
      var i = $('f_' + f.key); if (!i || !(f.key in S.cfg)) return;
      if (f.kind === 'b') i.checked = !!S.cfg[f.key]; else i.value = S.cfg[f.key];
    });
    if (S.cfg.tool_d !== undefined) $('tD').value = S.cfg.tool_d;
  }
  function collectCfg() {
    var c = {};
    S.fields.forEach(function (f) {
      if (f.kind === 'h') return;
      var i = $('f_' + f.key); if (!i) return;
      if (f.kind === 'b') c[f.key] = i.checked;
      else if (f.kind === 'd') c[f.key] = i.value;
      else { var v = parseFloat(String(i.value).replace(',', '.')); if (!isNaN(v)) c[f.key] = v; }
    });
    var d = parseFloat($('tD').value); if (!isNaN(d)) c.tool_d = d;
    return c;
  }
  function selected() { return S.sheets.filter(function (s) { return s.checked; }).map(function (s) { return s.name; }); }
  function markDirty() {
    S._dirty = true;
    status((window.CA_I18n && CA_I18n.t('btn.refresh_preview')) || '⟳ Vorschau aktualisieren');
  }
  function changed(ev) {
    if (S.timer) clearTimeout(S.timer);
    var src = ev && ev.target;
    if (src && src.id && src.id.indexOf('f_') === 0) {
      var key = src.id.slice(2);
      var f = S.fields.filter(function (x) { return x.key === key; })[0];
      S._liveStege = !!(f && f.group === 'stege');
    }
    status((window.CA_I18n && CA_I18n.t('preview_planning')) || 'Vorschau wird neu geplant …');
    S.timer = setTimeout(push, 180);
  }
  function push() {
    S.timer = null;
    var cur = $('selSheet').value || null;
    var fromStege = !!S._liveStege; S._liveStege = false;
    send('cfg', { cfg: collectCfg(), tool: { label: $('tTool').value, tnr: parseInt($('tTnr').value, 10) || 0 }, sel: selected(), cur: cur }, function (r) {
      var d = parse(r) || {};
      if (d.error) { status(d.error, true); return; }
      if (d.tools) renderTools(d.tools);
      if (d.sheets) renderSheets(d.sheets);
      loadPlan(d.plan);
      if (fromStege && d.plan && d.plan.parts && (S.tab === 'Stege' || S.tab === 'Bearbeitung')) showTab('Vorschau', false);
    });
  }

  // ---------------------------------------------------------------- Rohteile / Werkzeug
  function renderSheets(list) {
    S.sheets = list || [];
    var tb = $('sheetBody'); tb.innerHTML = '';
    $('sheetsEmpty').hidden = S.sheets.length > 0; $('sheetTable').hidden = !S.sheets.length;
    S.sheets.forEach(function (s) {
      var tr = el('tr', {}, tb);
      var td = el('td', {}, tr), cb = el('input', { type: 'checkbox' }, td); cb.checked = !!s.checked;
      cb.onchange = function () { s.checked = cb.checked; selInfo(); changed(); };
      var tn = el('td', {}, tr, s.name); if (s.edited) el('span', { className: 'ed', title: 'Stege/Start von Hand bearbeitet' }, tn, '✎');
      el('td', {}, tr, String(s.parts));
      el('td', { className: 'meta' }, tr, (s.label || '').split(': ').slice(1).join(': ') || s.source || '');
    });
    selInfo();
  }
  function selInfo() {
    var n = selected().length;
    $('selInfo').textContent = n + ' von ' + S.sheets.length + ' Rohteil(en) gewählt';
    $('btnRun').disabled = !n;
  }
  function renderTools(t) {
    S.tools = t;
    var lib = $('tLib');
    if (lib) {
      var cur = t.library || 'Dokument', libs = t.libraries || [{ id: 'Dokument', label: 'Dokument' }];
      lib.innerHTML = '';
      libs.forEach(function (x) { el('option', { value: x.id }, lib, x.label || x.id); });
      lib.value = cur;
      if (lib.value !== cur) lib.value = libs[0] ? libs[0].id : 'Dokument';
    }
    var sel = $('tTool'), want = t.label || t.selected || '';
    sel.innerHTML = '';
    el('option', { value: '' }, sel, '– automatisch / Werkzeugnummer –');
    (t.list || []).forEach(function (lbl) { el('option', { value: lbl }, sel, lbl); });
    sel.value = t.label || '';
    if (sel.value !== (t.label || '')) sel.value = '';
    $('tTnr').value = t.tnr || 0;
    $('tBib').checked = !!t.fusionBib;
    $('tInfo').textContent = (t.selected && !t.label ? 'Automatisch: ' + t.selected + ' – ' : (t.selected ? t.selected + ' – ' : '')) + t.text;
    $('tNoCam').hidden = !!t.available;
    void want;
  }

  // ---------------------------------------------------------------- Vorschau
  function loadPlan(p) {
    if (!p) { if (window.FinalschnittPalette) window.FinalschnittPalette.clear(); $('rows').innerHTML = ''; status(S.sheets.length ? 'Kein Rohteil gewählt.' : 'Keine Rohteile.'); return; }
    if (!p.parts) { $('msgs').textContent = (p.msgs || []).join(' · '); status((p.msgs || [''])[0]); return; }
    window.FinalschnittPalette.load(p);
  }
  function onPlan(p) {
    S.plan = p;
    var box = $('rows'); box.innerHTML = '';
    (p.rows || []).forEach(function (r) { el('div', { className: /^⚠/.test(r) ? 'w' : (/^ℹ/.test(r) ? 'i' : '') }, box, r); });
    (p.hints || []).forEach(function (r) { el('div', { className: 'i' }, box, 'ℹ ' + r); });
    renderOrderUi(p);
  }
  function renderOrderUi(p) {
    var host = $('orderUi');
    if (!host) {
      host = el('div', { id: 'orderUi', className: 'order-ui' }, $('rowsBox') || $('rows').parentNode);
    }
    host.innerHTML = '';
    var items = p.order_ui || [];
    if (!items.length) return;
    var head = el('div', { className: 'order-head' }, host);
    head.appendChild(document.createTextNode('Bearbeitungsreihenfolge' + (p.order_manual ? ' (von Hand)' : '')));
    if (p.order_manual) {
      var bAuto = el('button', { type: 'button', className: 'small', title: 'Automatische Reihenfolge' }, head, 'Auto');
      bAuto.onclick = function () { send('edit', { op: 'order_clear', sheet: (p.sheet || {}).name }, function (r) { var d = parse(r) || {}; if (d.plan) { loadPlan(d.plan); onPlan(d.plan); } }); };
    }
    items.forEach(function (it, idx) {
      var row = el('div', { className: 'order-row' }, host);
      el('span', { className: 'nr' }, row, String(it.nr));
      el('span', { className: 'nm' }, row, it.name || it.key || '?');
      var up = el('button', { type: 'button', className: 'small', title: 'früher' }, row, '▲');
      var dn = el('button', { type: 'button', className: 'small', title: 'später' }, row, '▼');
      up.disabled = idx === 0; dn.disabled = idx === items.length - 1;
      up.onclick = function () { moveOrder(items, idx, -1, p); };
      dn.onclick = function () { moveOrder(items, idx, +1, p); };
    });
  }
  function moveOrder(items, idx, dir, p) {
    var j = idx + dir;
    if (j < 0 || j >= items.length) return;
    var a = items.slice();
    var tmp = a[idx]; a[idx] = a[j]; a[j] = tmp;
    var keys = a.map(function (x) { return x.key; }).filter(Boolean);
    send('edit', { op: 'order_set', order: keys, sheet: (p.sheet || {}).name }, function (r) {
      var d = parse(r) || {};
      if (d.plan) { loadPlan(d.plan); onPlan(d.plan); }
    });
  }
  function step(d) {
    var s = $('selSheet'); if (!s.options.length) return;
    s.selectedIndex = (s.selectedIndex + d + s.options.length) % s.options.length;
    if (s.onchange) s.onchange();
  }

  // ---------------------------------------------------------------- Ergebnis
  function renderResult(r) {
    $('resEmpty').hidden = !!r; $('resBox').hidden = !r;
    if (!r) return;
    $('resHead').textContent = r.aborted ? '✖ Abgebrochen – nichts geändert' :
      (r.ops + ' Operation(en) erstellt' + (r.errors ? ', ' + r.errors + ' Fehler' : '') + ' · Rohteile: ' + (r.names || []).join(', '));
    $('resHead').className = r.aborted || r.errors ? 'warn' : 'ok';
    var ul = $('resLines'); ul.innerHTML = '';
    (r.lines || []).forEach(function (l) { l.split('\n\n').forEach(function (x) { if (x) el('li', { className: /Abbruch|fehlgeschlagen|veraltet/.test(x) ? 'err' : '' }, ul, x); }); });
    var w = $('resWarn'); w.innerHTML = '';
    (r.warnings || []).forEach(function (x) { el('li', {}, w, x); });
    $('resWarnBox').hidden = !(r.warnings || []).length;
    $('resLog').textContent = r.plan_file || (S.session && S.session.logFile) || '';
  }

  // ---------------------------------------------------------------- Fusion -> Palette
  function onSession(s) {
    S.session = s;
    if (s.i18n) applyI18n(s.i18n);
    if (s.info) window.CACore.setInfo(s.info);
    window.CACore.setTheme(s.theme);
    $('ver').textContent = 'v' + s.version;
    if (!S.fields.length || S.fields.length !== s.fields.length) buildFields(s.fields, s.groups);
    fillCfg(s.cfg);
    var ps = $('pSel'); ps.innerHTML = ''; (s.presets || []).forEach(function (n) { el('option', { value: n }, ps, n); });
    renderSheets(s.sheets);
    if (s.tools) renderTools(s.tools);
    renderResult(s.result);
    $('logPath').textContent = s.logFile || '';
    var hb = $('hints'); hb.innerHTML = '';
    (s.plan && s.plan.hints || []).forEach(function (h) { el('div', { className: 'warnbox' }, hb, 'ℹ ' + h); });
    if (!s.design) notice('warn', 'Keine Konstruktion aktiv – bitte ein Design öffnen.');
    else if (s.outdated && s.outdated.length) notice('warn', s.outdated.length + ' verknüpfte Komponente(n) veraltet – „Operationen erstellen“ bricht ab, bis die Verknüpfungen aktualisiert sind (Fusion: „Alle aktualisieren“, dann in CA LazyNest „Kopien aktualisieren“):', s.outdated.map(function (o) { return o.name + (o.version && o.latest ? ' (v' + o.version + ' → v' + o.latest + ')' : ''); }));
    else if (s.silhouette && s.silhouette.length) notice('warn', 'Silhouette prüfen bei ' + s.silhouette.length + ' Teil(en) (Abweichung zu LazyNest, offene Enden oder Ersatzkontur) – geschnitten wird immer die Silhouette (Draufsicht). Details: „🔍 Diagnose-Silhouette“ (Register Ergebnis):', s.silhouette);
    else if (s.migration && s.migration.copied) notice('ok', 'Einstellungen/Vorlagen aus Finalschnitt übernommen (' + s.migration.copied + ' Datei(en)).');
    else notice();
    loadPlan(s.plan);
    showTab(S.shown ? S.tab : (s.lastTab || 'Rohteile'), false);
    S.shown = true;
    status(S.sheets.length ? S.sheets.length + ' Rohteil(e) gefunden.' : 'Keine Rohteile gefunden.');
  }
  window.LS_EMBED = { send: send, onPlan: onPlan };
  window.fusionJavaScriptHandler = {
    handle: function (action, data) {
      try {
        var d = parse(data);
        if (action === 'session') onSession(d);
        else if (action === 'result') { renderResult(d); showTab('Ergebnis', false); status(d.aborted ? 'Abgebrochen.' : 'Fertig.', d.aborted || d.errors); $('btnRun').disabled = false; }
        else if (action === 'status') status(d);
        else if (action === 'theme') window.CACore.setTheme(d);
        else if (action === 'license') window.CACore.renderLicense(d);
        else if (action === 'plan') loadPlan(d);
        else return 'Unbekannte Aktion: ' + action;
      } catch (e) { status('Fehler: ' + e.message, true); }
      return 'OK';
    }
  };
  window.LazySetupMain = { state: function () { return S; }, showTab: showTab, onSession: onSession, renderResult: renderResult, collectCfg: collectCfg };

  function announce(tries) {
    if (window.adsk && window.adsk.fusionSendData) send('ready', {}, function (r) { var s = parse(r); if (s && s.version) onSession(s); });
    else if (tries < 100) setTimeout(function () { announce(tries + 1); }, 100);
    else status((window.CA_I18n && CA_I18n.t('status.no_fusion')) || 'Keine Verbindung zu Fusion.', true);
  }
  document.addEventListener('DOMContentLoaded', function () {
    window.CACore.init({ send: send, logo: 'img/logo_' });
    $('btnInfo').onclick = function () { window.CACore.openInfo(); };
    Array.prototype.forEach.call(document.querySelectorAll('#tabs .tab'), function (b) { b.onclick = function () { showTab(b.getAttribute('data-tab'), true); }; });
    $('btnRefresh').onclick = function () { status('Rohteile werden neu gelesen …'); send('refresh', {}, function (r) { var s = parse(r); if (s && s.version) onSession(s); }); };
    $('btnAll').onclick = function () { S.sheets.forEach(function (s) { s.checked = true; }); renderSheets(S.sheets); changed(); };
    $('btnNone').onclick = function () { S.sheets.forEach(function (s) { s.checked = false; }); renderSheets(S.sheets); changed(); };
    $('tTool').addEventListener('change', changed);
    ['tTnr', 'tD'].forEach(function (id) { $(id).addEventListener('input', markDirty); $(id).addEventListener('change', markDirty); });
    document.querySelectorAll('.btnPreviewUpdate').forEach(function (b) {
      b.onclick = function () { S._liveStege = (S.tab === 'Stege'); push(); };
    });
    $('tBib').onchange = function () { send('fusionBib', { on: $('tBib').checked }, function (r) { var d = parse(r) || {}; if (d.tools) renderTools(d.tools); loadPlan(d.plan); }); };
    if ($('tLib')) $('tLib').onchange = function () { send('toolLib', { id: $('tLib').value }, function (r) { var d = parse(r) || {}; if (d.tools) renderTools(d.tools); loadPlan(d.plan); }); };
    $('pLoad').onclick = function () {
      send('presetLoad', { name: $('pSel').value }, function (r) { var d = parse(r) || {}; if (d.error) { status(d.error, true); return; } fillCfg(d.cfg); loadPlan(d.plan); status('Vorlage „' + $('pSel').value + '“ geladen.'); });
    };
    $('pSave').onclick = function () {
      var n = $('pName').value.trim(); if (!n) { status('Bitte einen Namen für die Vorlage eingeben.', true); return; }
      send('presetSave', { name: n }, function (r) { var d = parse(r) || {}; if (d.presets) { var ps = $('pSel'); ps.innerHTML = ''; d.presets.forEach(function (x) { el('option', { value: x }, ps, x); }); ps.value = n; } status(d.ok ? 'Vorlage „' + n + '“ gespeichert.' : 'Vorlage nicht gespeichert.', !d.ok); });
    };
    $('btnPrev').onclick = function () { step(-1); }; $('btnNext').onclick = function () { step(1); };
    $('btnRun').onclick = function () {
      if (S.timer) { clearTimeout(S.timer); S.timer = null; }
      $('btnRun').disabled = true; status('Operationen werden vorbereitet …');
      send('cfg', { cfg: collectCfg(), tool: { label: $('tTool').value, tnr: parseInt($('tTnr').value, 10) || 0 }, sel: selected() }, function () {
        send('run', {}, function (r) { var d = parse(r) || {}; if (d.error) { status(d.error, true); notice('error', d.error); $('btnRun').disabled = false; } else status('Läuft – Fusion arbeitet …'); });
      });
    };
    $('btnClose').onclick = function () { send('close', {}); };
    $('btnSilDiag').onclick = function () { status('Diagnose-Silhouette läuft …'); send('silDiag', {}, function (r) { var d = parse(r) || {}; if (d.error) { status(d.error); return; } $('silDiagPath').textContent = d.file || ''; status('Diagnose-Silhouette: ' + d.parts + ' Teil(e) – ' + (d.file || '')); }); };
    $('btnLog').onclick = function () { send('openLogs', {}, function (r) { var d = parse(r) || {}; if (d.path) status((d.ok ? 'Geöffnet: ' : 'Ordner: ') + d.path); }); };
    window.addEventListener('resize', function () { if (S.tab === 'Vorschau' && window.FinalschnittPalette) window.FinalschnittPalette.fit(); });
    showTab('Rohteile', false);
    announce(0);
  });
}());
