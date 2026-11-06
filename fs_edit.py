# -*- coding: utf-8 -*-
"""Finalschnitt – Bearbeitungen aus der Palette „Stege bearbeiten“ (ab 1.2.0), ohne Fusion testbar.

Datenmodell je Rohteil (JSON im Attribut Finalschnitt/overrides der Rohteil-Occurrence):
    {'version': 1,
     'parts': {<Teil-Schlüssel ContourNest-ID#Kopie>: {'name', 'sig', 'tabs': [u, …] | None, 'start': u | None,
               'starts_holes': {Loch-Index: u}}},
     'bridges_add': [{'a', 'ua', 'b', 'ub'}], 'bridges_del': [{'a', 'b', 'ua'}],
     'order': [Teil-Schlüssel, …] | None}  # 2.0.5 manuelle Reihenfolge
u = Konturparameter 0…1 ab Bezugs-Eckpunkt (fs_geom.to_u/from_u), sig = Lage/Form beim Bearbeiten.
'tabs' legt ALLE Einzelstege des Teils fest (beim ersten Eingriff werden die berechneten übernommen);
Brücken stehen getrennt (hinzugefügt / gelöscht). Bleibt bei jeder Neuplanung erhalten bis „Zurücksetzen“.
"""
import copy
import json
import math

import fs_geom as G

GROUP = 'Finalschnitt'
ATTR = 'overrides'
HIT_MM = 15.0          # Steg/Brücke „getroffen“, wenn so nah (mm)


def empty():
    return {'version': 1, 'parts': {}, 'bridges_add': [], 'bridges_del': [], 'order': None}


def normalize(ov):
    out = empty()
    if isinstance(ov, dict):
        out['parts'] = {k: dict(v) for k, v in (ov.get('parts') or {}).items() if isinstance(v, dict)}
        out['bridges_add'] = [dict(b) for b in ov.get('bridges_add') or [] if isinstance(b, dict)]
        out['bridges_del'] = [dict(b) for b in ov.get('bridges_del') or [] if isinstance(b, dict)]
        od = ov.get('order')
        if isinstance(od, list) and od:
            out['order'] = [str(k) for k in od]
    return out


def is_empty(ov):
    ov = normalize(ov)
    return not (any(e.get('tabs') is not None or e.get('start') is not None
                    or e.get('starts_holes') for e in ov['parts'].values())
                or ov['bridges_add'] or ov['bridges_del'] or ov.get('order'))


def canonical(ov):
    """Für den Planungs-Hash: gerundet, sortiert, leere Einträge weg."""
    ov = normalize(ov)
    parts = {}
    for k, e in sorted(ov['parts'].items()):
        if e.get('tabs') is None and e.get('start') is None and not e.get('starts_holes'):
            continue
        sh = e.get('starts_holes')
        if isinstance(sh, dict):
            sh = {str(i): round(float(u), 5) for i, u in sh.items() if u is not None}
        parts[k] = {'sig': e.get('sig'), 'tabs': None if e.get('tabs') is None else [round(float(u), 5) for u in e['tabs']],
                    'start': None if e.get('start') is None else round(float(e['start']), 5),
                    'starts_holes': sh or None}
    return {'parts': parts,
            'add': sorted([[b['a'], round(float(b['ua']), 5), b['b'], round(float(b['ub']), 5)] for b in ov['bridges_add']]),
            'del': sorted([[b['a'], b['b'], round(float(b['ua']), 5)] for b in ov['bridges_del']]),
            'order': list(ov['order'] or [])}


# ---------------------------------------------------------------- Speicher (Attribut der Rohteil-Occurrence)
# Zwischenspeicher je Rohteil-Name: Bearbeitungen aus der Palette, während der Dialog offen ist. Fusion kann
# Attribut-Änderungen, die während eines aktiven Befehls außerhalb seiner Ereignisse entstehen, beim Abbrechen
# verwerfen – daher schreibt Finalschnitt sie nach dem Dialog noch einmal (persist_all).
_mem = {}


def _ent(sheet):
    return sheet.get('occ')


def _ent_valid(ent):
    """Occurrence noch gültig? Nach Dokument-Schluss ist der Proxy tot – Native-Zugriff würde Fusion crashen."""
    if ent is None:
        return False
    try:
        return getattr(ent, 'isValid', True) is not False
    except Exception:
        return False


def _key(sheet):
    """2.0.4: Zwischenspeicher je Rohteil-Name UND Occurrence – ein neues Rohteil gleichen Namens (Nesting
    gelöscht und neu angelegt) erbt keine Bearbeitungen des alten."""
    ent = _ent(sheet)
    tok = ''
    if _ent_valid(ent):
        try:
            tok = ent.entityToken or ''
        except Exception:
            tok = ''
    return '%s|%s' % (sheet.get('name'), tok if isinstance(tok, str) else '')


def load(sheet):
    if _key(sheet) in _mem:
        return normalize(copy.deepcopy(_mem[_key(sheet)]))
    ent = _ent(sheet)
    if ent is None:
        return empty()
    try:
        a = ent.attributes.itemByName(GROUP, ATTR)
        return normalize(json.loads(a.value)) if a and a.value else empty()
    except Exception:
        return empty()


def save(sheet, ov):
    """True, wenn geschrieben. Leere Bearbeitung löscht das Attribut."""
    ov = normalize(ov)
    _mem[_key(sheet)] = copy.deepcopy(ov)
    ent = _ent(sheet)
    if not _ent_valid(ent):
        return False
    try:
        a = ent.attributes.itemByName(GROUP, ATTR)
        if is_empty(ov):
            if a is not None:
                try:
                    a.deleteMe()
                except Exception:
                    ent.attributes.add(GROUP, ATTR, '')
            return True
        ent.attributes.add(GROUP, ATTR, json.dumps(ov, sort_keys=True))
        return True
    except Exception:
        return False


def persist_all(sheets):
    """Zwischenspeicher in die Attribute schreiben (nach Ende des Dialogs). Anzahl geschriebener Rohteile."""
    n = 0
    for sh in sheets or []:
        try:
            if _key(sh) in _mem:
                if save(sh, _mem[_key(sh)]):
                    n += 1
        except Exception:
            pass
    return n


def clear_mem():
    _mem.clear()


# ---------------------------------------------------------------- Bearbeiten (auf einem fertigen Plan)
def _part(plan, key):
    return next((p for p in plan['parts'] if p.get('key') == key), None)


def _entry(ov, p):
    e = ov['parts'].setdefault(p['key'], {})
    e['name'] = p.get('name')
    e['sig'] = G.part_sig(p)
    return e


def _freeze(ov, p):
    """Beim ersten Eingriff: berechnete Einzelstege übernehmen."""
    e = _entry(ov, p)
    if e.get('tabs') is None:
        e['tabs'] = [round(G.to_u(p, t['s']), 6) for t in p['tabs'] if not t.get('bridge')]
    return e


def _checks(plan, p, s, ignore_s=None):
    """Warnungen für einen Steg an s: Ecke, zu nah an anderem Steg, am Startpunkt."""
    cfg = plan['cfg']
    msgs = []
    tot = p['per']
    if any(G.cyc_dist(s, sc, tot) < G.corner_gap(cfg) for _i, sc, _t in G.corners(p['outer'], 45.0, p['_c'])):
        msgs.append('Steg liegt in/nahe einer Ecke (< %.0f mm)' % G.corner_gap(cfg))
    near = min([G.cyc_dist(s, t['s'], tot) for t in p['tabs'] if ignore_s is None or abs(t['s'] - ignore_s) > 1e-6]
               or [tot])
    lim = max(3 * float(cfg['steg_breite']), 2 * float(cfg['tool_d']))
    if near < lim:
        msgs.append('Steg nur %.0f mm neben einem anderen (< %.0f mm)' % (near, lim))
    td, tw = float(cfg['tool_d']), float(cfg['steg_breite'])
    if G.cyc_dist(s, p['start']['s'], tot) < max(float(cfg['start_abstand_min']), 3 * td) + tw / 2:
        msgs.append('Steg nahe am Startpunkt')
    return msgs


def _nearest_tab(p, q, bridge=None):
    best = None
    for t in p['tabs']:
        if bridge is not None and bool(t.get('bridge')) != bridge:
            continue
        d = math.dist(t['pt'], q)
        if best is None or d < best[0]:
            best = (d, t)
    return best


def _nearest_part(plan, q, exclude=()):
    best = None
    for p in plan['parts']:
        if p['idx'] in exclude:
            continue
        h = G.closest_on_poly(p['outer'], q, p['_c'])
        if best is None or h['d'] < best[1]['d']:
            best = (p, h)
    return best


def apply_edit(plan, ov, op):
    """Eine Bearbeitung auf ov anwenden (ov wird kopiert). op = {'op': …, 'key', 'pt', 'to', …}.
    Rückgabe (neues ov, Meldungen, ok)."""
    ov = normalize(copy.deepcopy(ov))
    kind = op.get('op')
    q = tuple(op['pt']) if op.get('pt') is not None else None
    msgs = []
    p = _part(plan, op.get('key')) if op.get('key') else None
    if kind in ('tab_add', 'tab_del', 'tab_move', 'start_set', 'bridge_del', 'bridge_move') and p is None:
        if q is not None and kind not in ('bridge_del', 'bridge_move'):
            hit = _nearest_part(plan, q)
            p = hit[0] if hit and hit[1]['d'] <= 3 * HIT_MM else None
        if p is None and kind not in ('bridge_del', 'bridge_move'):
            return ov, ['Kein Teil an dieser Stelle'], False
    if kind == 'tab_add':
        h = G.closest_on_poly(p['outer'], q, p['_c'])
        msgs += _checks(plan, p, h['s'])
        e = _freeze(ov, p)
        e['tabs'].append(round(G.to_u(p, h['s']), 6))
        return ov, ['%s: Steg hinzugefügt' % p.get('name')] + msgs, True
    if kind == 'tab_del':
        nt = _nearest_tab(p, q)
        if nt is None or nt[0] > HIT_MM:
            return ov, ['Kein Steg an dieser Stelle'], False
        if nt[1].get('bridge'):
            return apply_edit(plan, ov, {'op': 'bridge_del', 'key': p['key'], 'pt': nt[1]['pt']})
        e = _freeze(ov, p)
        u = G.to_u(p, nt[1]['s'])
        k = min(range(len(e['tabs'])), key=lambda i: G.cyc_dist(e['tabs'][i], u, 1.0)) if e['tabs'] else None
        if k is not None:
            e['tabs'].pop(k)
        return ov, ['%s: Steg gelöscht' % p.get('name')], True
    if kind == 'tab_move':
        nt = _nearest_tab(p, q, bridge=False)
        if nt is None or nt[0] > HIT_MM:
            return ov, ['Kein Einzelsteg zum Verschieben'], False
        h = G.closest_on_poly(p['outer'], tuple(op['to']), p['_c'])
        msgs += _checks(plan, p, h['s'], ignore_s=nt[1]['s'])
        e = _freeze(ov, p)
        u0 = G.to_u(p, nt[1]['s'])
        if e['tabs']:
            k = min(range(len(e['tabs'])), key=lambda i: G.cyc_dist(e['tabs'][i], u0, 1.0))
            e['tabs'][k] = round(G.to_u(p, h['s']), 6)
        return ov, ['%s: Steg verschoben' % p.get('name')] + msgs, True
    if kind == 'start_set':
        hole_i = op.get('hole')
        q = tuple(op.get('to') or op['pt'])
        if hole_i is not None and 0 <= int(hole_i) < len(p['holes']):
            hi = int(hole_i)
            hpoly = p['holes'][hi]
            hc = G.cum(hpoly)
            h = G.closest_on_poly(hpoly, q, hc)
            e = _entry(ov, p)
            sh = dict(e.get('starts_holes') or {})
            sh[str(hi)] = round((h['s'] / (hc[1] or 1.0)), 6)
            e['starts_holes'] = sh
            return ov, ['%s: Start Innenkante %d verschoben' % (p.get('name'), hi + 1)] + msgs, True
        h = G.closest_on_poly(p['outer'], q, p['_c'])
        _entry(ov, p)['start'] = round(G.to_u(p, h['s']), 6)
        if any(G.cyc_dist(h['s'], sc, p['per']) < float(plan['cfg']['start_ecke_min'])
               for _i, sc, _t in G.corners(p['outer'], 45.0, p['_c'])):
            msgs.append('Startpunkt liegt an einer Ecke')
        return ov, ['%s: Startpunkt verschoben' % p.get('name')] + msgs, True
    if kind == 'order_set':
        keys = [str(k) for k in (op.get('order') or [])]
        known = {q.get('key') for q in plan['parts']}
        keys = [k for k in keys if k in known]
        ov['order'] = keys or None
        return ov, (['Reihenfolge von Hand: %d Teil(e)' % len(keys)] if keys else
                    ['Reihenfolge zurück auf Automatik']), True
    if kind == 'order_clear':
        ov['order'] = None
        return ov, ['Reihenfolge zurück auf Automatik'], True
    if kind == 'bridge_del':
        best = None
        for b in plan['bridges']:
            for end in ('pa', 'pb'):
                d = math.dist(b[end], q)
                if (p is None or p['idx'] in (b['a'], b['b'])) and (best is None or d < best[0]):
                    best = (d, b)
        if best is None or best[0] > HIT_MM:
            return ov, ['Keine Brücke an dieser Stelle'], False
        b = best[1]
        A, B = plan['parts'][b['a']], plan['parts'][b['b']]
        if b.get('manual'):
            ua = G.to_u(A, b['sa'])
            ov['bridges_add'] = [e for e in ov['bridges_add']
                                 if not ({e['a'], e['b']} == {A['key'], B['key']}
                                         and G.cyc_dist(float(e['ua'] if e['a'] == A['key'] else e['ub']), ua, 1.0)
                                         * A['per'] <= HIT_MM)]
        else:
            _entry(ov, A)
            _entry(ov, B)
            ov['bridges_del'].append({'a': A['key'], 'b': B['key'], 'ua': round(G.to_u(A, b['sa']), 6)})
        return ov, ['Brücke %s–%s gelöscht' % (A.get('name'), B.get('name'))], True
    if kind == 'bridge_move':
        q = tuple(op['pt']) if op.get('pt') is not None else None
        to = tuple(op['to']) if op.get('to') is not None else None
        if q is None or to is None:
            return ov, ['Brücke: von/nach fehlt'], False
        best = None
        for b in plan['bridges']:
            for end in ('pa', 'pb'):
                d = math.dist(b[end], q)
                if (p is None or p['idx'] in (b['a'], b['b'])) and (best is None or d < best[0]):
                    best = (d, b)
        if best is None or best[0] > HIT_MM * 2:
            # Fallback: Nähe zum Mittelpunkt
            for b in plan['bridges']:
                mid = (0.5 * (b['pa'][0] + b['pb'][0]), 0.5 * (b['pa'][1] + b['pb'][1]))
                d = math.dist(mid, q)
                if best is None or d < best[0]:
                    best = (d, b)
        if best is None or best[0] > HIT_MM * 3:
            return ov, ['Keine Brücke zum Verschieben'], False
        b = best[1]
        A, B = plan['parts'][b['a']], plan['parts'][b['b']]
        # Alte Brücke entfernen (wie bridge_del)
        if b.get('manual'):
            ua = G.to_u(A, b['sa'])
            ov['bridges_add'] = [e for e in ov['bridges_add']
                                 if not ({e['a'], e['b']} == {A['key'], B['key']}
                                         and G.cyc_dist(float(e['ua'] if e['a'] == A['key'] else e['ub']), ua, 1.0)
                                         * A['per'] <= HIT_MM)]
        else:
            _entry(ov, A)
            _entry(ov, B)
            ov['bridges_del'].append({'a': A['key'], 'b': B['key'], 'ua': round(G.to_u(A, b['sa']), 6)})
        # Versatz Mittelpunkt -> neue Endpunkte auf beiden Konturen
        mid = (0.5 * (b['pa'][0] + b['pb'][0]), 0.5 * (b['pa'][1] + b['pb'][1]))
        dx, dy = to[0] - mid[0], to[1] - mid[1]
        ha = G.closest_on_poly(A['outer'], (b['pa'][0] + dx, b['pa'][1] + dy), A['_c'])
        hb = G.closest_on_poly(B['outer'], (b['pb'][0] + dx, b['pb'][1] + dy), B['_c'])
        _entry(ov, A)
        _entry(ov, B)
        ov['bridges_add'].append({'a': A['key'], 'ua': round(G.to_u(A, ha['s']), 6),
                                  'b': B['key'], 'ub': round(G.to_u(B, hb['s']), 6)})
        msgs += _checks(plan, A, ha['s']) + _checks(plan, B, hb['s'])
        return ov, ['Brücke %s–%s verschoben' % (A.get('name'), B.get('name'))] + msgs, True
    if kind == 'bridge_add':
        hit = _nearest_part(plan, q)
        if hit is None:
            return ov, ['Kein Teil'], False
        A, ha = hit
        hb = _nearest_part(plan, q, exclude=(A['idx'],))
        if hb is None:
            return ov, ['Kein zweites Teil in der Nähe'], False
        B, _h = hb
        pb = G.closest_on_poly(B['outer'], ha['pt'], B['_c'])
        cfg = plan['cfg']
        lim = float(cfg['tool_d']) + float(cfg['bruecke_extra']) + 2.0
        if pb['d'] > lim:
            return ov, ['Keine zwei eng benachbarten Teile hier (Abstand %.1f mm > %.1f mm)' % (pb['d'], lim)], False
        _entry(ov, A)
        _entry(ov, B)
        ov['bridges_add'].append({'a': A['key'], 'ua': round(G.to_u(A, ha['s']), 6),
                                  'b': B['key'], 'ub': round(G.to_u(B, pb['s']), 6)})
        msgs += _checks(plan, A, ha['s']) + _checks(plan, B, pb['s'])
        return ov, ['Brücke %s–%s hinzugefügt' % (A.get('name'), B.get('name'))] + msgs, True
    if kind == 'reset_part':
        key = op.get('key')
        ov['parts'].pop(key, None)
        ov['bridges_add'] = [e for e in ov['bridges_add'] if key not in (e['a'], e['b'])]
        ov['bridges_del'] = [e for e in ov['bridges_del'] if key not in (e['a'], e['b'])]
        return ov, ['%s: zurückgesetzt' % (p.get('name') if p else key)], True
    if kind == 'reset_all':
        return empty(), ['Alle Bearbeitungen dieses Rohteils zurückgesetzt'], True
    return ov, ['Unbekannte Bearbeitung %s' % kind], False


# ---------------------------------------------------------------- Plan als JSON für die Palette
def plan_json(plan, sheet_names=None, msgs=None):
    ps = plan['parts']
    r1 = lambda q: [round(q[0], 2), round(q[1], 2)]      # noqa: E731
    ovi = plan.get('overrides') or {}
    parts = []
    for k, i in enumerate(plan['order']):
        p = ps[i]
        parts.append({
            'key': p.get('key'), 'name': p.get('name'), 'nr': k + 1, 'small': p['small'], 'large': p.get('large', False),
            'outer': [r1(q) for q in p['outer']], 'holes': [[r1(q) for q in h] for h in p['holes']],
            'pockets': [[r1(q) for q in h] for h in p.get('pockets') or []],
            'centroid': r1(p['centroid']), 'edited': p.get('key') in (ovi.get('parts') or []),
            'start': {'pt': r1(p['start']['pt']), 'dir': r1(p['start'].get('to_centre') or (0, 0)),
                      'manual': bool(p['start'].get('manual'))},
            'hole_starts': [{'pt': r1(hs['pt']), 'dir': r1(hs.get('to_centre') or (0, 0)),
                             'manual': bool(hs.get('manual')), 'hole': hi}
                            for hi, hs in enumerate(p.get('hole_starts') or [])],
            'tabs': [{'pt': r1(t['pt']), 'bridge': bool(t.get('bridge')), 'manual': bool(t.get('manual'))}
                     for t in p['tabs']]})
    return {'sheet': plan['sheet'], 'sheets': sheet_names or [], 'parts': parts,
            'bridges': [{'a': ps[b['a']].get('key'), 'b': ps[b['b']].get('key'), 'pa': r1(b['pa']), 'pb': r1(b['pb']),
                         'manual': bool(b.get('manual'))} for b in plan['bridges']],
            'warnings': plan['warnings'], 'msgs': msgs or [],
            'tool_d': plan['cfg']['tool_d'], 'snap_mm': HIT_MM,
            'order_keys': [ps[i].get('key') for i in plan['order']],
            'order_manual': bool((plan.get('overrides') or {}).get('order_manual'))}
