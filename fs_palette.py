# -*- coding: utf-8 -*-
"""Finalschnitt – Python-Seite der Palette „Stege bearbeiten“ (ab 1.2.0), ohne Fusion testbar.
Finalschnitt.py verbindet sie mit der Fusion-Palette (incomingFromHTML / sendInfoToHTML)."""
import json

import fs_edit as E
import fs_log as L
import fs_run as R


class Editor:
    """Zustand: gewählte Rohteile (wie im Dialog), Planungs-Einstellungen (R.plan_cfg) und gezeigtes Rohteil.
    on_change(sheet_name) wird nach jeder gespeicherten Bearbeitung aufgerufen (Dialog-Vorschau auffrischen)."""

    def __init__(self, on_change=None, on_close=None):
        self.sheets, self.cfg, self.current = [], None, None
        self.on_change, self.on_close = on_change, on_close

    def setup(self, sheets, cfg, current=None):
        self.sheets = [s for s in sheets if s.get('parts')]
        self.cfg = cfg
        names = [s['name'] for s in self.sheets]
        if current in names:
            self.current = current
        elif self.current not in names:
            self.current = names[0] if names else None

    def sheet(self):
        return next((s for s in self.sheets if s['name'] == self.current), None)

    def plan(self, sh=None):
        """2.0.2: Ergebnis je (Rohteil, Einstellungen, Skizzen-/Bearbeitungseingaben) merken – die Palette fragt
        pro Aktion zweimal (Plan + Textzeilen); die Planung lief bisher doppelt."""
        sh = sh or self.sheet()
        if sh is None:
            return None
        sk = R.sketch_inputs(sh, self.cfg)
        try:
            key = (id(sh), sh.get('name'), json.dumps(self.cfg, sort_keys=True, default=str),
                   json.dumps(sk, sort_keys=True, default=str))
        except Exception:
            key = None
        memo = getattr(self, '_memo', None)
        if key is not None and memo is not None and memo[0] == key:
            return memo[1]
        p = R.make_plan(sh, self.cfg, sk=sk)
        self._memo = (key, p) if key is not None else None
        return p

    def payload(self, msgs=None):
        sh = self.sheet()
        if sh is None or self.cfg is None:
            return json.dumps({'msgs': ['Kein Rohteil mit Teilen gewählt.']})
        return json.dumps(E.plan_json(self.plan(sh), [s['name'] for s in self.sheets], msgs), ensure_ascii=False)

    def handle(self, action, data):
        """Antwort (String) auf eine Nachricht der Palette."""
        try:
            d = json.loads(data or '{}') if isinstance(data, str) else (data or {})
        except ValueError:
            d = {}
        if action == 'ready':
            return self.payload()
        if action == 'sheet':
            if any(s['name'] == d.get('name') for s in self.sheets):
                self.current = d['name']
            return self.payload()
        if action == 'edit':
            return self.edit(d)
        if action == 'close':
            if self.on_close:
                self.on_close()
            return 'OK'
        return json.dumps({'msgs': ['Unbekannte Aktion %s' % action]})

    def edit(self, op):
        sh = self.sheet()
        if sh is None:
            return json.dumps({'msgs': ['Kein Rohteil gewählt.']})
        if op.get('sheet') and op['sheet'] != sh['name']:
            self.current = op['sheet']
            sh = self.sheet() or sh
        plan = self.plan(sh)
        ov, msgs, ok = E.apply_edit(plan, E.load(sh), op)
        L.info('Palette %s: %s %s -> %s', sh['name'], op.get('op'), {k: v for k, v in op.items() if k != 'op'},
               '; '.join(msgs))
        if ok:
            try:
                E.save(sh, ov)
            except Exception:
                L.exc('Bearbeitungen speichern')
                msgs.append('Speichern im Design fehlgeschlagen – nur bis zum Schließen gültig')
            if self.on_change:
                try:
                    self.on_change(sh['name'])
                except Exception:
                    L.exc('Dialog-Vorschau nach Bearbeitung')
        return self.payload(msgs)
