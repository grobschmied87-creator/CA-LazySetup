# -*- coding: utf-8 -*-
"""Finalschnitt – Anlegen der 2D-Kontur-Operationen über die Fusion-CAM-API (Basis-CAM, ohne Extension).

Reihenfolge je Rohteil (Operationen werden in Erstellungsreihenfolge angehängt):
  FS 01 Taschen              (optional, pocket2d – verschiebt die folgenden Nummern)
  FS 01 Innen                (alle Durchbrüche, contour2d, ohne Stege)
  FS 02 Außen – <Teil>       (je Teil eine Operation in Schnittreihenfolge -> Reihenfolge garantiert)
  FS 03 Schlicht – <Teil>    (optional, gleicher Umriss ohne Aufmaß)
Jeder Parameter wird über getChoices() geprüft, gesetzt, zurückgelesen und protokolliert; fehlende oder
abweichende Namen erscheinen als Warnung. Die vollständige Parameterliste der ersten Operation je
Strategie wird nach logs/params_<strategie>_<zeit>.json geschrieben.
"""
import json
import math

import adsk.core

try:
    import adsk.cam
except Exception:
    adsk.cam = None

import fs_fusion as FF
import fs_geom as G
import fs_log as L
import fs_timing as TM

GROUP = 'Finalschnitt'
OP_ATTR = 'op'
PREFIX = 'FS '
CN = 'ContourNest'
SETUP_FMT = 'ContourNest Rohteil %02d'
SK_START = 'Finalschnitt Startpunkte'
SK_TABS = 'Finalschnitt Stege'
# ab 1.1.0: berechnete Punkte (Bezug der Operationen) NUR in diese Skizzen – sie werden nie als Eingabe gelesen
SK_START_OUT = SK_START + ' (berechnet)'
SK_TABS_OUT = SK_TABS + ' (berechnet)'
SK_LEGACY = (SK_START + ' (intern)', SK_TABS + ' (intern)')
SK_SIL = 'LazySetup Silhouette'           # 2.0.1: je Teil eine Skizze, wenn die Silhouette keine B-Rep-Schleife ist
CAM_WS = 'CAMEnvironment'
MILL_TYPES = ('flat end mill', 'bull nose end mill', 'ball end mill', 'tapered mill', 'lollipop mill')

_safe = FF._safe
items = FF.items


# ---------------------------------------------------------------- CAM-Produkt / Setup
def get_cam(app, ui, create=True):
    doc = _safe(lambda: app.activeDocument)
    if doc is None:
        return None

    def lookup():
        p = _safe(lambda: doc.products.itemByProductType('CAMProductType'))
        if p is None:
            return None
        return (_safe(lambda: adsk.cam.CAM.cast(p)) if adsk.cam else None) or p
    cam = lookup()
    if cam is None and create:
        ws = _safe(lambda: ui.workspaces.itemById(CAM_WS))
        if ws is not None:
            _safe(lambda: ws.activate())
            cam = lookup()
            L.info('CAM-Produkt fehlte – Arbeitsbereich FERTIGUNG aktiviert -> %s', 'ok' if cam else 'weiterhin None')
    return cam


def setup_link(setup):
    return FF.attr(setup, 'cam_link', as_json=True)


def find_setup(cam, sheet):
    """Setup des Rohteils: zuerst über ContourNest/cam_link (Projekt + Rohteil), sonst über den Namen."""
    setups = items(_safe(lambda: cam.setups))
    for s in setups:
        ln = setup_link(s)
        if isinstance(ln, dict) and ln.get('project_id', '') == sheet['project_id'] and \
                int(ln.get('project_sheet', -1)) == sheet['project_sheet']:
            return s, 'cam_link'
    for s in setups:
        if FF.attr(s, 'sheet', group=GROUP) == sheet['name']:
            return s, 'Finalschnitt'
    nm = SETUP_FMT % sheet['no']
    for s in setups:
        if _safe(lambda: s.name) == nm:
            return s, 'Name'
    return None, ''


def _coll(objs):
    c = adsk.core.ObjectCollection.create()
    for o in objs:
        c.add(o)
    return c


def create_simple_setup(cam, sheet, version):
    """Einfaches Fräs-Setup: Modelle = Teile, Rohteil = Körper „Rohteil“ (sonst feste Box im Maschinenmaß),
    WCS = Modell-Ausrichtung, Nullpunkt des Rohteils aus ContourNest (1.3.0; ältere Daten: 'bottom 1')."""
    rec = {}
    L.checkpoint('%s: Setup anlegen (setups.add)', sheet['name'])
    inp = cam.setups.createInput(adsk.cam.OperationTypes.MillingOperation)
    inp.models = [p['cam_occ'] for p in sheet['parts']] or [sheet['cam_occ']]
    setup = cam.setups.add(inp)
    _safe(lambda: setattr(setup, 'name', SETUP_FMT % sheet['no']))
    params = setup.parameters
    body = next((b for b in items(_safe(lambda: sheet['cam_occ'].bRepBodies)) if _safe(lambda: b.name) == 'Rohteil'), None)
    try:
        if body is None:
            raise RuntimeError('kein Körper „Rohteil“')
        L.checkpoint('%s: stockSolids zuweisen', sheet['name'])
        setup.stockMode = adsk.cam.SetupStockModes.SolidStock
        setup.stockSolids = _coll([body])
        rec['stock'] = 'solid'
    except Exception as e:
        rec['stock_solid_error'] = str(e)
        _safe(lambda: setattr(setup, 'stockMode', adsk.cam.SetupStockModes.FixedBoxStock))
        X, Y, Z = machine_dims(sheet)
        set_length(params, 'job_stockFixedX', X, rec)
        set_length(params, 'job_stockFixedY', Y, rec)
        set_length(params, 'job_stockFixedZ', Z, rec)
        rec['stock'] = 'box'
    set_choice(params, 'wcs_orientation_mode', 'modelOrientation', ('model',), rec)
    set_choice(params, 'wcs_origin_mode', 'stockPoint', ('stock',), rec)
    set_choice(params, 'wcs_origin_boxPoint', sheet.get('box_point') or 'bottom 1', (), rec)
    link = {'project_id': sheet['project_id'], 'project_sheet': sheet['project_sheet'], 'sheet_no': sheet['no'],
            'sheet_name': sheet['name'], 'version': 'LazySetup ' + version}
    _safe(lambda: setup.attributes.add(CN, 'cam_link', json.dumps(link)))
    _safe(lambda: setup.attributes.add(GROUP, 'sheet', sheet['name']))
    L.info('Eigenes Setup angelegt für %s: %s', sheet['name'], json.dumps(rec, default=str))
    return setup


# ---------------------------------------------------------------- Werkzeuge
def machine_dims(sheet):
    """Rohteilmaß im Maschinensystem (X, Y, Z mm): quer liegende Rohteile mit getauschter Länge/Breite."""
    if sheet.get('W') is not None and sheet.get('H') is not None:
        return float(sheet['W']), float(sheet['H']), float(sheet.get('thickness') or 0)
    if sheet.get('orient') == 'quer':
        return float(sheet['width']), float(sheet['length']), float(sheet.get('thickness') or 0)
    return float(sheet['length']), float(sheet['width']), float(sheet.get('thickness') or 0)


def ensure_wcs(setup, sheet):
    """1.3.0: vorhandenes Setup auf Nullpunkt (WCS) und – bei fester Box – Rohteilmaß des Rohteils bringen.
    Ändert nur, was abweicht (set_choice liest vorher). Rückgabe (geändert: Liste, rec)."""
    rec, changed = {}, []
    params = _safe(lambda: setup.parameters)
    if params is None:
        return changed, rec
    bp = sheet.get('box_point') if sheet.get('zero_explicit') else None     # ältere Daten: Setup nie ändern
    if bp:
        mode = _safe(lambda: _read(params.itemByName('wcs_origin_mode')))
        if mode not in (None, 'stockPoint'):
            set_choice(params, 'wcs_origin_mode', 'stockPoint', ('stock',), rec)
            changed.append('WCS-Ursprung = Rohteil-Punkt')
        before = _safe(lambda: _read(params.itemByName('wcs_origin_boxPoint')))
        if before != bp:
            if set_choice(params, 'wcs_origin_boxPoint', bp, (), rec):
                changed.append('Nullpunkt %s → %s' % (before, bp))
    is_box = False
    try:
        is_box = setup.stockMode == adsk.cam.SetupStockModes.FixedBoxStock
    except Exception:
        is_box = False
    if is_box:
        X, Y, Z = machine_dims(sheet)
        for ax, v in (('X', X), ('Y', Y), ('Z', Z)):
            p = _safe(lambda: params.itemByName('job_stockFixed%s' % ax))
            cur = _safe(lambda: float(str(_read(p)).replace('mm', '').strip())) if p is not None else None
            if cur is None or abs(cur - v) > 1e-6:
                if set_length(params, 'job_stockFixed%s' % ax, v, rec):
                    changed.append('Rohteil %s = %g mm' % (ax, v))
    return changed, rec


def tool_info(tool):
    def p(name):
        q = _safe(lambda: tool.parameters.itemByName(name))
        v = _safe(lambda: q.value.value) if q is not None else None
        return v
    d = p('tool_diameter')
    return {'type': p('tool_type') or '', 'd_mm': round(float(d) * 10.0, 4) if isinstance(d, (int, float)) else None,
            'number': p('tool_number'), 'desc': p('tool_description') or '', 'flutes': p('tool_numberOfFlutes'),
            'feed': p('tool_feedCutting'), 'rpm': p('tool_spindleSpeed')}


def _lib_urls(tl, url, depth=0):
    """Alle Bibliotheks-URLs unter url (rekursiv, wie Autodesk-Beispiel getLibrariesURLs)."""
    out = [u.toString() for u in items(_safe(lambda: tl.childAssetURLs(url)))]
    if depth < 4:
        for f in items(_safe(lambda: tl.childFolderURLs(url))):
            out += _lib_urls(tl, f, depth + 1)
    return [u for u in dict.fromkeys(out) if u]


def list_libraries(cam, include_fusion=False):
    """2.0.5: Werkzeugbibliotheken als [{id, label, location}] – Dokument zuerst, dann Lokal/Cloud/Hub(/Fusion)."""
    out = [{'id': 'Dokument', 'label': 'Dokument (aktuelles Setup)', 'location': 'Dokument'}]
    try:
        tl = adsk.cam.CAMManager.get().libraryManager.toolLibraries
        locs = [('Lokal', adsk.cam.LibraryLocations.LocalLibraryLocation),
                ('Cloud', adsk.cam.LibraryLocations.CloudLibraryLocation),
                ('Hub', getattr(adsk.cam.LibraryLocations, 'HubLibraryLocation', None))]
        if include_fusion:
            locs.append(('Fusion', adsk.cam.LibraryLocations.Fusion360LibraryLocation))
        for nm, loc in locs:
            if loc is None:
                continue
            base = _safe(lambda: tl.urlByLocation(loc))
            if base is None:
                continue
            for u in _lib_urls(tl, base):
                short = u.rstrip('/').split('/')[-1] or u
                lid = '%s: %s' % (nm, short)
                out.append({'id': lid, 'label': lid, 'location': nm, 'url': u})
    except Exception:
        L.exc('Werkzeugbibliotheken auflisten')
    return out


def list_tools(cam, include_fusion=False, library_id=None):
    """Fräswerkzeuge aus Dokument- und Bibliotheks-Werkzeugen.
    2.0.5: library_id filtert – None/'Alle' = Dokument + alle Libs; 'Dokument' nur Doku;
    sonst nur diese eine Bibliothek (id wie in list_libraries). Liste dicts {label, tool, source, info}."""
    res, seen = [], set()
    want = library_id or 'Alle'
    if want in ('', None):
        want = 'Alle'

    def add(tool, src):
        if want != 'Alle':
            if want == 'Dokument' and src != 'Dokument':
                return
            if want != 'Dokument' and src != want:
                return
        inf = tool_info(tool)
        if inf['type'] and str(inf['type']).lower() not in MILL_TYPES:
            return
        key = (inf['number'], inf['d_mm'], inf['desc'], src.split(':')[0])
        if key in seen:
            return
        seen.add(key)
        num = 'T%s ' % inf['number'] if inf['number'] not in (None, '') else ''
        label = '%sØ %s mm %s – %s' % (num, ('%g' % inf['d_mm']) if inf['d_mm'] else '?', inf['desc'] or inf['type'], src)
        res.append({'label': label[:90], 'tool': tool, 'source': src, 'info': inf, 'library': src})
    try:
        if want in ('Alle', 'Dokument'):
            for t_ in items(_safe(lambda: cam.documentToolLibrary)):
                add(t_, 'Dokument')
    except Exception:
        L.exc('Dokument-Werkzeuge')
    try:
        if want != 'Dokument':
            tl = adsk.cam.CAMManager.get().libraryManager.toolLibraries
            locs = [('Lokal', adsk.cam.LibraryLocations.LocalLibraryLocation),
                    ('Cloud', adsk.cam.LibraryLocations.CloudLibraryLocation),
                    ('Hub', getattr(adsk.cam.LibraryLocations, 'HubLibraryLocation', None))]
            if include_fusion:
                locs.append(('Fusion', adsk.cam.LibraryLocations.Fusion360LibraryLocation))
            for nm, loc in locs:
                if loc is None:
                    continue
                base = _safe(lambda: tl.urlByLocation(loc))
                if base is None:
                    continue
                for u in _lib_urls(tl, base):
                    lib = _safe(lambda: tl.toolLibraryAtURL(adsk.core.URL.create(u)))
                    if lib is None:
                        continue
                    short = u.rstrip('/').split('/')[-1]
                    src = '%s: %s' % (nm, short)
                    if want != 'Alle' and src != want:
                        continue
                    for t_ in items(lib):
                        add(t_, src)
    except Exception:
        L.exc('Werkzeugbibliotheken')
    res.sort(key=lambda r: (r['source'] != 'Dokument', r['info']['d_mm'] or 999, str(r['info']['number'])))
    unique_labels(res)
    L.info('Werkzeuge gefunden: %d (Bibliothek=%s, Schaftfräser: %d)', len(res), want,
           sum(1 for r in res if str(r['info'].get('type', '')).lower() == 'flat end mill'))
    return res


def default_tool(tools, last_label=None, want_d=8.0):
    """Vorauswahl: zuletzt benutztes Werkzeug (Bezeichnung), sonst Schaftfräser (flat end mill) mit Ø am
    nächsten an want_d – Dokument-Werkzeuge vor Bibliotheken. Rückgabe Index in tools oder None."""
    if not tools:
        return None
    if last_label:
        for k, t in enumerate(tools):
            if t['label'] == last_label:
                return k
    flat = [(k, t) for k, t in enumerate(tools) if str(t['info'].get('type', '')).lower() == 'flat end mill'
            and t['info'].get('d_mm')]
    if not flat:
        flat = [(k, t) for k, t in enumerate(tools) if t['info'].get('d_mm')]
    if not flat:
        return 0
    return min(flat, key=lambda e: (abs(e[1]['info']['d_mm'] - want_d), e[1]['source'] != 'Dokument', e[0]))[0]


def unique_labels(tools):
    """Bezeichnungen eindeutig machen (Dropdown wird über den Namen zurückgelesen)."""
    seen = {}
    for t in tools:
        lb = t['label']
        if lb in seen:
            seen[lb] += 1
            t['label'] = '%s (%d)' % (lb[:84], seen[lb])
        else:
            seen[lb] = 1
    return tools


def tool_by_number(tools, number):
    for r in tools:
        try:
            if int(r['info']['number']) == int(number):
                return r
        except (TypeError, ValueError):
            continue
    return None


# ---------------------------------------------------------------- Parameter
def unq(v):
    """Auswahlwert ohne umschließende Hochkommas. Fusion 2705 liefert getChoices()-Werte MIT Hochkommas
    ("'modelOrientation'", ContourNest-Log cam_*.json 12:50) – überall (Vergleich, Setzen, Rücklesen) gleich
    behandeln, sonst entstehen Ausdrücke wie "''wert''" („Invalid enumeration value“)."""
    if isinstance(v, str):
        v = v.strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in "'\"":
            v = v[1:-1]
    return v


def _choices(p):
    r = _safe(lambda: p.value.getChoices())
    if isinstance(r, (list, tuple)) and len(r) == 3 and r[0]:
        return [unq(n) for n in (r[1] or [])], [unq(v) for v in (r[2] or [])]
    return [], []


def _read(p):
    v = _safe(lambda: p.value.value)
    if v is None or not isinstance(v, (str, int, float, bool)):
        v = _safe(lambda: p.expression)
    return unq(v)


def set_choice(params, name, want, keys=(), rec=None):
    rec = rec if rec is not None else {}
    p = _safe(lambda: params.itemByName(name))
    if p is None:
        rec[name] = {'ok': False, 'error': 'Parameter fehlt', 'want': want}
        return None
    names, values = _choices(p)
    want = unq(want)
    val = want
    if values and want not in values:
        cand = [v for v, n in zip(values, names + [''] * len(values))
                if any(k.lower() in (str(v) + ' ' + str(n)).lower() for k in keys)]
        val = cand[0] if cand else want
    r = {'want': want, 'value': val, 'choices': values[:40]}
    if _read(p) == val:                      # schon gesetzt -> nichts anfassen
        r['read_back'] = val
        r['ok'] = True
        r['unchanged'] = True
        rec[name] = r
        return val
    try:
        p.expression = "'%s'" % val
    except Exception as e:
        r['expr_error'] = str(e)
    if _read(p) != val:
        try:
            p.value.value = val
        except Exception as e:
            r['value_error'] = str(e)
    r['read_back'] = _read(p)
    r['ok'] = r['read_back'] == val
    rec[name] = r
    return val if r['ok'] else None


def set_bool(params, name, val, rec):
    p = _safe(lambda: params.itemByName(name))
    if p is None:
        rec[name] = {'ok': False, 'error': 'Parameter fehlt', 'want': val}
        return False
    try:
        p.expression = 'true' if val else 'false'
    except Exception as e:
        try:
            p.value.value = bool(val)
        except Exception:
            rec[name] = {'ok': False, 'error': str(e)}
            return False
    rb = _read(p)
    ok = rb in (val, 'true' if val else 'false', 1 if val else 0)
    rec[name] = {'ok': ok, 'value': val, 'read_back': rb}
    return ok


def set_length(params, name, mm, rec):
    p = _safe(lambda: params.itemByName(name))
    if p is None:
        rec[name] = {'ok': False, 'error': 'Parameter fehlt', 'want': mm}
        return False
    try:
        p.expression = '%g mm' % mm
        rec[name] = {'ok': True, 'value': '%g mm' % mm, 'read_back': _safe(lambda: p.expression)}
        return True
    except Exception as e:
        rec[name] = {'ok': False, 'error': str(e)}
        return False


def set_number(params, name, v, rec):
    p = _safe(lambda: params.itemByName(name))
    if p is None:
        rec[name] = {'ok': False, 'error': 'Parameter fehlt', 'want': v}
        return False
    try:
        p.expression = '%g' % v
        rec[name] = {'ok': True, 'value': v, 'read_back': _safe(lambda: p.expression)}
        return True
    except Exception as e:
        rec[name] = {'ok': False, 'error': str(e)}
        return False


def set_objects(params, name, objs, rec):
    """CadObjectParameterValue (z. B. entryPositions, tabPositions): value.value = [Objekte]."""
    p = _safe(lambda: params.itemByName(name))
    if p is None:
        rec[name] = {'ok': False, 'error': 'Parameter fehlt'}
        return False
    try:
        flush_points()
        L.checkpoint('Parameter %s: %d Objekt(e) zuweisen', name, len(objs))
        p.value.value = list(objs)
        n = len(_safe(lambda: list(p.value.value), []) or [])
        rec[name] = {'ok': n == len(objs), 'count': len(objs), 'read_back_count': n}
        return rec[name]['ok']
    except Exception as e:
        rec[name] = {'ok': False, 'error': str(e)}
        return False


def dump_params(op, kind):
    """Alle Parameter einer Operation (Name, Titel, Ausdruck, Wert, Auswahlwerte) -> logs/params_<kind>_*.json."""
    out = []
    for p in items(_safe(lambda: op.parameters)):
        e = {'name': _safe(lambda: p.name), 'title': _safe(lambda: p.title), 'expression': _safe(lambda: p.expression)}
        v = _safe(lambda: p.value.value)
        e['value'] = v if isinstance(v, (str, int, float, bool)) else type(v).__name__ if v is not None else None
        e['value_type'] = type(_safe(lambda: p.value)).__name__
        n, vals = _choices(p)
        if vals:
            e['choices'] = vals
            e['choice_names'] = n
        out.append(e)
    path = L.dump_json('params_' + kind, {'operation': _safe(lambda: op.name), 'strategy': _safe(lambda: op.strategy),
                                          'count': len(out), 'parameters': out})
    L.info('Parameterliste %s: %d Parameter -> %s', kind, len(out), path)
    return path


# ---------------------------------------------------------------- Geometrie-Auswahl
def set_chains(op, chains, rec, param='contours', refetch=None):
    with TM.phase('Konturauswahl'):
        return _set_chains(op, chains, rec, param, refetch)


def _set_chains(op, chains, rec, param='contours', refetch=None):
    """chains = [(kanten, isReverted)] -> CadContours2dParameterValue (getCurveSelections/applyCurveSelections).
    1.3.1: vorher edge.isValid prüfen; ungültig oder von Fusion abgelehnt -> refetch() (Kanten frisch aus der
    B-Rep) und EINMAL erneut versuchen."""
    name = _safe(lambda: op.name, '?')
    tries, last = 0, None
    while tries < 2:
        if refetch is not None and (tries > 0 or not all(FF.edges_valid(e) for e, _r in chains)):
            L.info('%s: Kanten %s – frisch aus der B-Rep lesen', name,
                   'abgelehnt' if tries else 'ungültig (Konstruktion neu berechnet)')
            chains = refetch() or []
            rec['%s_reread' % param] = rec.get('%s_reread' % param, 0) + 1
        tries += 1
        try:
            L.checkpoint('%s: Konturauswahl %s (%d Kette(n))', name, param, len(chains))
            val = op.parameters.itemByName(param).value
            sel = val.getCurveSelections()
            _safe(lambda: sel.clear())
            for edges, rev in chains:
                ch = sel.createNewChainSelection()
                ch.inputGeometry = list(edges)
                _safe(lambda: setattr(ch, 'isReverted', bool(rev)))
                _safe(lambda: setattr(ch, 'isOpen', False))
            val.applyCurveSelections(sel)
            rec[param] = {'ok': True, 'chains': len(chains), 'reverted': [bool(r) for _e, r in chains],
                          'attempts': tries, 'curves': [len(list(e)) for e, _r in chains]}
            rb = readback_chains(op, param)
            rec[param]['readback'] = rb
            if rb.get('n') is not None and rb['n'] != len(chains):
                rec[param]['readback_mismatch'] = True
                L.warn('%s: Konturauswahl zurückgelesen: %s Kette(n) statt %d', name, rb['n'], len(chains))
            else:
                L.info('%s: Konturauswahl übernommen – %s Kette(n), Kurven je Kette %s', name,
                       rb.get('n', '?'), rb.get('curves'))
            return True
        except Exception as e:
            last = e
            L.exc('Kettenauswahl %s (Versuch %d)' % (name, tries))
            if refetch is None:
                break
    rec[param] = {'ok': False, 'error': str(last), 'attempts': tries}
    return False


def readback_chains(op, param='contours'):
    """2.0.2: Auswahl nach applyCurveSelections zurücklesen: Anzahl Ketten, Kurven je Kette, isReverted."""
    out = {}
    try:
        sel = op.parameters.itemByName(param).value.getCurveSelections()
        n = _safe(lambda: sel.count)
        lst = [_safe(lambda i=i: sel.item(i)) for i in range(n or 0)]
        out['n'] = n
        out['curves'] = [len(list(_safe(lambda c=c: c.inputGeometry, []) or [])) for c in lst]
        out['reverted'] = [_safe(lambda c=c: bool(c.isReverted)) for c in lst]
    except Exception as e:
        out['error'] = str(e)[:160]
    return out


def set_pockets(op, faces, rec):
    try:
        L.checkpoint('%s: Taschenauswahl (%d Fläche(n))', _safe(lambda: op.name, '?'), len(faces))
        val = op.parameters.itemByName('pockets').value
        sel = val.getCurveSelections()
        ps = sel.createNewPocketSelection()
        ps.inputGeometry = list(faces)
        val.applyCurveSelections(sel)
        rec['pockets'] = {'ok': True, 'faces': len(faces)}
        return True
    except Exception as e:
        rec['pockets'] = {'ok': False, 'error': str(e)}
        L.exc('Taschenauswahl')
        return False


# ---------------------------------------------------------------- Skizzenpunkte
def _sketch(comp, name, create=True, recreate=False):
    sk = next((s for s in items(_safe(lambda: comp.sketches)) if _safe(lambda: s.name) == name), None)
    if sk is not None and recreate:
        L.checkpoint('Skizze %s löschen (neu anlegen)', name)
        if _safe(lambda: sk.deleteMe(), False) is not False:
            sk = None
    if sk is None and create:
        L.checkpoint('Skizze %s anlegen', name)
        sk = comp.sketches.add(comp.xYConstructionPlane)
        sk.name = name
        _safe(lambda: setattr(sk, 'isVisible', False))
    return sk


def read_sketch_points(sheet, name):
    """Punkte einer vorhandenen Skizze im Rohteil (mm, Rohteil-Koordinaten; Ursprung ausgenommen)."""
    comp = _safe(lambda: sheet['occ'].component)
    sk = _sketch(comp, name, create=False) if comp is not None else None
    out = []
    if sk is None:
        return out
    for sp in items(_safe(lambda: sk.sketchPoints)):
        g = _safe(lambda: sp.geometry)
        if g is None or (abs(g.x) < 1e-9 and abs(g.y) < 1e-9 and abs(_safe(lambda: g.z, 0.0)) < 1e-9):
            continue                                    # Skizzenursprung
        w = _safe(lambda: sk.sketchToModelSpace(g)) or g  # Komponenten-Koordinaten (cm)
        out.append((w.x / FF.MM, w.y / FF.MM))
    return out


def sketch_z_mm(sheet):
    """2.0.5: Z der Steg-/Startpunkt-Skizze = Bearbeitungsseite.
    Oberseite (zero_side=oben) -> max z_top; sonst min z_bottom. Vermeidet Punkte auf der
    Gegenfläche, die Fusion bei tabPositions/entryPositions verwirft."""
    side = sheet.get('zero_side') or 'unten'
    tops, bots = [], []
    for part in sheet.get('parts') or []:
        g = part.get('geo') or {}
        bots.append(float(g.get('z_bottom', 0.0)))
        tops.append(float(g.get('z_top', g.get('z_bottom', 0.0))))
    if not bots:
        return 0.0
    return max(tops) if side == 'oben' else min(bots)


class PointFactory:
    """Legt Skizzenpunkte im Rohteil an und liefert sie im Kontext des Rohteils (createForAssemblyContext)."""

    def __init__(self, sheet, name, recreate, z_mm=0.0):
        self.sheet, self.name, self.z = sheet, name, z_mm
        self.comp = sheet['occ'].component
        self.sk = _sketch(self.comp, name, True, recreate)
        self.count = 0
        self.ctx = []
        self.occ = None              # 2.0.2: funktionierender Kontext (einmal bestimmt)
        self.deferred = False

    def add(self, x_mm, y_mm):
        if not self.deferred:        # 2.0.2: viele Punkte -> Skizze erst beim Zuweisen berechnen
            self.deferred = _safe(lambda: setattr(self.sk, 'isComputeDeferred', True) or True, False)
            if self.deferred:
                _OPEN_PF.append(self)
        mp = adsk.core.Point3D.create(x_mm * FF.MM, y_mm * FF.MM, self.z * FF.MM)
        sp_ = _safe(lambda: self.sk.modelToSketchSpace(mp)) or mp
        pt = self.sk.sketchPoints.add(sp_)
        self.count += 1
        if self.occ is not None:
            px = _safe(lambda: pt.createForAssemblyContext(self.occ[0]))
            if px is not None:
                self.ctx.append(self.occ[1])
                return px
        for occ, how in ((self.sheet.get('cam_occ'), 'cam'), (self.sheet['occ'], 'design')):
            if occ is None:
                continue
            px = _safe(lambda: pt.createForAssemblyContext(occ))
            if px is not None:
                self.ctx.append(how)
                self.occ = (occ, how)
                return px
        self.ctx.append('lokal')
        return pt

    def flush(self):
        if self.deferred:
            _safe(lambda: setattr(self.sk, 'isComputeDeferred', False))
            self.deferred = False


_OPEN_PF = []


def flush_points():
    """Zurückgestellte Punkt-Skizzen berechnen (vor dem Zuweisen an CAM-Parameter)."""
    while _OPEN_PF:
        _OPEN_PF.pop().flush()


def _sil_sketches(comp):
    return [s for s in items(_safe(lambda: comp.sketches)) if str(_safe(lambda: s.name, '')).startswith(SK_SIL)]


def remove_silhouette_sketches(comp, keep=()):
    """Silhouetten-Skizzen löschen (veraltet: Teil nicht mehr im Lauf / Operationen ersetzt)."""
    n = 0
    for sk in _sil_sketches(comp):
        if _safe(lambda: sk.name) in keep:
            continue
        L.checkpoint('Skizze %s löschen (veraltet)', _safe(lambda: sk.name))
        if _safe(lambda: sk.deleteMe(), False) is not False:
            n += 1
    return n


def arc_sweep(pts, c):
    """Überstrichener Winkel (rad, + = gegen den Uhrzeigersinn) entlang der Abtastpunkte um den Mittelpunkt c."""
    tot = 0.0
    for a, b in zip(pts, pts[1:]):
        a0 = math.atan2(a[1] - c[1], a[0] - c[0])
        a1 = math.atan2(b[1] - c[1], b[0] - c[0])
        d = a1 - a0
        while d > math.pi:
            d -= 2 * math.pi
        while d < -math.pi:
            d += 2 * math.pi
        tot += d
    return tot


ARC_TOL = 0.02      # mm: Bogenprüfung (Länge, Mitte, Ende) gegen die Quellkante


def _arc_ok(arc, exp_len_mm, exp_mid, exp_end, P):
    """Angelegten Skizzenbogen gegen die Erwartung prüfen (Länge, Endpunkte, Mitte – soweit lesbar)."""
    ln = _safe(lambda: arc.length)
    if ln is not None and abs(ln / FF.MM - exp_len_mm) > max(ARC_TOL, 0.002 * exp_len_mm):
        return False, 'Länge %.3f statt %.3f mm' % (ln / FF.MM, exp_len_mm)
    ends = [_safe(lambda: arc.startSketchPoint.geometry), _safe(lambda: arc.endSketchPoint.geometry)]
    pe = P(exp_end)
    if all(e is not None for e in ends) and min(math.dist((e.x, e.y), (pe.x, pe.y)) for e in ends) > ARC_TOL * FF.MM:
        return False, 'Endpunkt weicht ab'
    ev = _safe(lambda: arc.geometry.evaluator)
    if ev is not None:
        r = _safe(lambda: ev.getParameterExtents())
        if r and r[0]:
            m = _safe(lambda: ev.getPointAtParameter((r[1] + r[2]) / 2.0))
            pm = P(exp_mid)
            if m and m[0] and math.dist((m[1].x, m[1].y), (pm.x, pm.y)) > ARC_TOL * FF.MM:
                return False, 'Bogenmitte weicht ab'
    return True, ''


def _sketch_matrix(sk, z_mm, P_api):
    """2.0.3: Matrix Modell -> Skizze (Zeilen, 12 Werte) aus sk.transform (invertiert), geprüft gegen
    modelToSketchSpace an zwei Punkten. None = nicht sicher -> Aufrufer rechnet je Punkt über die API."""
    try:
        m = sk.transform.copy()
        if not m.invert():
            return None
        a = list(m.asArray())
        if len(a) != 16:
            return None
        for p in ((12.5, 34.25), (-250.0, 1210.0)):
            q = P_api(p)
            x, y, z = p[0] * FF.MM, p[1] * FF.MM, z_mm * FF.MM
            r = (a[0] * x + a[1] * y + a[2] * z + a[3], a[4] * x + a[5] * y + a[6] * z + a[7],
                 a[8] * x + a[9] * y + a[10] * z + a[11])
            if max(abs(r[0] - q.x), abs(r[1] - q.y), abs(r[2] - q.z)) > 1e-7:
                return None
        return a[:12]
    except Exception:
        return None


def _draw_loop(sk, lp, z_mm):
    """Silhouetten-Läufe als Skizzenkurven. 2.0.2: Bögen über Mittelpunkt/Start/Winkel aus der Original-Kante
    (Arc3D/Circle3D: Mittelpunkt, Radius), geprüft gegen Länge/Mitte/Ende – bei Abweichung Strecken + Warnung
    in lp['warn'] (nie mehr Dreipunktbögen, die bei fast geraden Läufen riesig werden). Rückgabe Kurvenliste;
    setzt lp['first_opposed'] nach der tatsächlichen Richtung der ersten Kurve."""
    curves_ = sk.sketchCurves
    lines, arcs = curves_.sketchLines, curves_.sketchArcs

    def P_api(p):
        mp = adsk.core.Point3D.create(p[0] * FF.MM, p[1] * FF.MM, z_mm * FF.MM)
        return _safe(lambda: sk.modelToSketchSpace(mp)) or mp

    # 2.0.3 Tempo: Umrechnung Modell -> Skizze einmal als Matrix bestimmen (statt 2 API-Aufrufe je Punkt); nur
    # wenn sie an zwei Probepunkten exakt mit modelToSketchSpace übereinstimmt, sonst wie bisher je Punkt.
    mat = _sketch_matrix(sk, z_mm, P_api)

    def P(p):
        if mat is None:
            return P_api(p)
        x, y, z = p[0] * FF.MM, p[1] * FF.MM, z_mm * FF.MM
        return adsk.core.Point3D.create(mat[0] * x + mat[1] * y + mat[2] * z + mat[3],
                                        mat[4] * x + mat[5] * y + mat[6] * z + mat[7],
                                        mat[8] * x + mat[9] * y + mat[10] * z + mat[11])

    def poly(pts):
        prev = None                     # 2.0.3: Strecken verketten (gemeinsamer Skizzenpunkt statt neuer Punkte)
        for a, b in zip(pts, pts[1:]):
            if math.dist(a, b) > 1e-4:
                st = _safe(lambda: prev.endSketchPoint) if prev is not None else None
                ln = lines.addByTwoPoints(st if st is not None else P(a), P(b))
                out.append(ln)
                prev = ln
            else:
                prev = None

    out = []
    for run in lp['runs']:
        pts = run['pts']
        ai = run.get('arc')
        if run['kind'] == 'arc' and len(pts) >= 2 and ai:
            c, r = ai['c'], ai['r']
            sw = arc_sweep(pts, c)
            full = abs(abs(sw) - 2 * math.pi) < 1e-3 or (math.dist(pts[0], pts[-1]) < 1e-3 and abs(sw) > math.pi)
            if full:
                sw = math.copysign(2 * math.pi, sw)
            pieces = [sw / 2.0, sw / 2.0] if full else [sw]
            a0 = math.atan2(pts[0][1] - c[1], pts[0][0] - c[0])
            for sw_i in pieces:
                st = (c[0] + r * math.cos(a0), c[1] + r * math.sin(a0))
                en = (c[0] + r * math.cos(a0 + sw_i), c[1] + r * math.sin(a0 + sw_i))
                md = (c[0] + r * math.cos(a0 + sw_i / 2), c[1] + r * math.sin(a0 + sw_i / 2))
                # Vorzeichen im SKIZZEN-Raum (Skizzennormale kann −Z sein): Drehsinn von Start -> Mitte dort
                pc, ps, pm = P(c), P(st), P(md)
                cr = (ps.x - pc.x) * (pm.y - pc.y) - (ps.y - pc.y) * (pm.x - pc.x)
                sgn = 1.0 if cr > 0 else -1.0
                arc = None
                try:
                    arc = arcs.addByCenterStartSweep(pc, ps, sgn * abs(sw_i))
                except Exception as e:
                    lp.setdefault('warn', []).append('Bogen nicht anlegbar (%s) – Strecken' % e)
                ok, why = (False, 'kein Bogen') if arc is None else _arc_ok(arc, r * abs(sw_i), md, en, P)
                if ok:
                    out.append(arc)
                else:
                    if arc is not None:
                        _safe(lambda: arc.deleteMe())
                        lp.setdefault('warn', []).append('Bogen R %.2f mm verworfen (%s) – Strecken' % (r, why))
                    n = max(4, int(abs(sw_i) * r / 0.5) + 1)
                    poly([(c[0] + r * math.cos(a0 + sw_i * t / n), c[1] + r * math.sin(a0 + sw_i * t / n))
                          for t in range(n + 1)])
                a0 += sw_i
        else:
            poly(pts)
    if out:
        s0 = _safe(lambda: out[0].startSketchPoint.geometry)
        p0 = P(lp['runs'][0]['pts'][0])
        lp['first_opposed'] = bool(s0 is not None and math.dist((s0.x, s0.y), (p0.x, p0.y)) > 1e-5)
    return out


def silhouette_sketches(sheet, parts, order, recreate, z_mm=0.0, warns=None):
    """2.0.1: je Teil mit zusammengesetzter Silhouette (Fase/Falz/Überstand über mehrere Flächen) eine
    ausgeblendete Skizze „LazySetup Silhouette – <Teil>“ im Rohteil; Kurven im Rohteil-Kontext an die
    Schleifen (lp['curves']). recreate (Ersetzen): alle alten Silhouetten-Skizzen vorher löschen.
    Rückgabe (angelegt, gelöscht, Fehler-Liste)."""
    comp = sheet['occ'].component
    removed = remove_silhouette_sketches(comp) if recreate else 0
    names = set(_safe(lambda: s.name) for s in _sil_sketches(comp))
    made, errs = 0, []
    warns = errs if warns is None else warns
    for i in order:
        g = parts[i]['geo']
        loops = [lp for lp in [g['outer']] + list(g['holes']) if lp.get('method') == 'skizze' and lp.get('runs')]
        if not loops:
            continue
        base = '%s – %s' % (SK_SIL, parts[i].get('name'))
        nm, k = base, 2
        while nm in names:
            nm, k = '%s (%d)' % (base, k), k + 1
        names.add(nm)
        try:
            sk = _sketch(comp, nm, True, False)
            _safe(lambda: setattr(sk, 'isComputeDeferred', True))
            n = 0
            ctx = []                           # 2.0.2: Kontext einmal je Skizze bestimmen, nicht je Kurve probieren
            for lp in loops:
                cs = _draw_loop(sk, lp, z_mm)
                for w in lp.pop('warn', []):
                    warns.append('%s / %s: %s' % (sheet['name'], parts[i].get('name'), w))
                n += len(cs)
                px = []
                for c in cs:
                    q = None
                    if ctx:
                        q = _safe(lambda: c.createForAssemblyContext(ctx[0]))
                    else:
                        for occ in (sheet.get('cam_occ'), sheet['occ']):
                            if occ is not None:
                                q = _safe(lambda: c.createForAssemblyContext(occ))
                                if q is not None:
                                    ctx.append(occ)
                                    break
                    px.append(q or c)
                lp['curves'] = px
            _safe(lambda: setattr(sk, 'isComputeDeferred', False))
            _safe(lambda: setattr(sk, 'isVisible', False))
            made += 1
            L.info('%s / %s: Silhouette als Skizze „%s“ (%d Kontur(en), %d Kurven)', sheet['name'],
                   parts[i].get('name'), nm, len(loops), n)
        except Exception as e:
            L.exc('Silhouetten-Skizze %s' % nm)
            errs.append('%s / %s: Silhouetten-Skizze nicht anlegbar (%s) – Teil wird NICHT geschnitten'
                        % (sheet['name'], parts[i].get('name'), e))
            for lp in loops:
                lp['curves'] = []
                lp['sketch_failed'] = True
    return made, removed, errs


# ---------------------------------------------------------------- Operationen
def is_fs_op(op):
    return bool(FF.attr(op, OP_ATTR, group=GROUP)) or str(_safe(lambda: op.name, '')).startswith(PREFIX)


def _op_sheet(op):
    m = FF.attr(op, OP_ATTR, group=GROUP)
    try:
        return (json.loads(m) if isinstance(m, str) else (m or {})).get('sheet')
    except Exception:
        return None


def delete_old(setup, cam=None, sheet_name=None):
    """Alte FS-Operationen löschen – IMMER bevor Skizzen/Auswahlen/Geometrie angefasst werden (1.0.2,
    Lehre aus dem ContourNest-Absturz 12:48/12:53). Gelöscht wird im Setup des Rohteils und zusätzlich jede
    FS-Operation in anderen Setups, die laut Attribut zu diesem Rohteil gehört (sie verweist auf dieselben
    Skizzenpunkte)."""
    n = 0
    targets = [setup]
    if cam is not None and sheet_name:
        targets += [s for s in items(_safe(lambda: cam.setups)) if s is not setup]
    for s in targets:
        ops = items(_safe(lambda: s.allOperations)) or items(_safe(lambda: s.operations))
        for op in list(ops):
            if not is_fs_op(op):
                continue
            if s is not setup and _op_sheet(op) != sheet_name:
                continue
            try:
                L.checkpoint('FS-Operation löschen: %s / %s', _safe(lambda: s.name, '?'), _safe(lambda: op.name, '?'))
                op.deleteMe()
                n += 1
            except Exception:
                L.exc('Alte Operation löschen')
    return n


def new_op(setup, strategy, name, tool, meta, rec):
    inp = setup.operations.createInput(strategy)
    if tool is not None:
        inp.tool = tool
        pres = _safe(lambda: tool.presets)
        if pres is not None and _safe(lambda: pres.count, 0):
            _safe(lambda: setattr(inp, 'toolPreset', pres.item(0)))
            rec['toolPreset'] = _safe(lambda: pres.item(0).name)
    _safe(lambda: setattr(inp, 'displayName', name))
    L.checkpoint('Operation anlegen: %s (%s)', name, strategy)
    op = setup.operations.add(inp)
    if _safe(lambda: op.name) != name:
        _safe(lambda: setattr(op, 'name', name))
    _safe(lambda: op.attributes.add(GROUP, OP_ATTR, json.dumps(meta)))
    rec['name'] = _safe(lambda: op.name)
    rec['strategy'] = strategy
    return op


DIRECTION = {'gleich': ('climb', 'left', ('climb', 'gleich', 'left')),
             'gegen': ('conventional', 'right', ('conv', 'gegen', 'right'))}


def _richtung_key(cfg, premill=False):
    """2.0.7: richtung_vor/final; Legacy `richtung` wenn neue Keys noch gemeinsam Default sind."""
    key = 'richtung_vor' if premill else 'richtung_final'
    specific = cfg.get(key)
    other = cfg.get('richtung_final' if premill else 'richtung_vor')
    legacy = cfg.get('richtung')
    if specific in (None, ''):
        return legacy or 'gleich'
    if other is not None and specific != other:
        return specific
    if legacy and legacy != specific and specific == 'gleich' and legacy != 'gleich':
        return legacy
    return specific


def _legacy_pair(cfg, base, suf, default):
    """Wert aus base_suf, sonst base; Legacy-Override wenn beide Suffixe noch Default."""
    specific = cfg.get(base + suf)
    legacy = cfg.get(base)
    if specific is None:
        return legacy if legacy is not None else default
    other = cfg.get(base + ('_final' if suf == '_vor' else '_vor'))
    if other is not None and specific != other:
        return specific
    if legacy is not None and specific == default and legacy != default and (other is None or other == default):
        return legacy
    return specific


def _op_tab_cfg(cfg, premill=False):
    """Form/Breite/Höhe + ob Tabs an. 2.0.9: Vorfräs nie Stege/Brücken."""
    if premill:
        c = dict(cfg)
        c['stege'] = False
        return c, False
    suf = '_final'
    on = cfg.get('stege_final')
    if on is None:
        on = cfg.get('stege', True)
    form = _legacy_pair(cfg, 'steg_form', suf, 'rechteckig')
    br = _legacy_pair(cfg, 'steg_breite', suf, 8.0)
    ho = _legacy_pair(cfg, 'steg_hoehe', suf, 3.0)
    c = dict(cfg)
    c['stege'] = bool(on)
    c['steg_form'] = form
    c['steg_breite'] = float(br)
    c['steg_hoehe'] = float(ho)
    return c, bool(on)


def _suf(premill):
    return '_vor' if premill else '_final'


def _cfg_f(cfg, key, default=0.0):
    try:
        return float(cfg.get(key, default) or default)
    except (TypeError, ValueError):
        return float(default)


def lead_in_params(op, cfg, premill, rec):
    """Anfahrart Rampe / Eintauchen / Bogen – nur setzen wenn Parameter existieren."""
    ps = op.parameters
    suf = _suf(premill)
    art = (cfg.get('anfahr_art' + suf) or ('rampe' if premill else 'bogen')).lower()
    set_bool(ps, 'doLeadIn', True, rec)
    # Art
    if art == 'eintauchen':
        set_choice(ps, 'leadInType', 'plunge', ('plunge', 'vertical', 'eintauch'), rec)
        set_choice(ps, 'entry_horizontal', 'plunge', ('plunge', 'vertical'), rec)
        set_bool(ps, 'useRamp', False, rec)
    elif art == 'bogen':
        set_choice(ps, 'leadInType', 'smooth', ('smooth', 'arc', 'circular', 'horizontal', 'bogen'), rec)
        set_choice(ps, 'entry_horizontal', 'horizontal', ('horizontal', 'arc', 'smooth'), rec)
        set_bool(ps, 'useRamp', False, rec)
    else:  # rampe
        set_choice(ps, 'leadInType', 'ramp', ('ramp', 'rampe'), rec)
        set_choice(ps, 'entry_horizontal', 'ramp', ('ramp',), rec)
        set_bool(ps, 'useRamp', True, rec)
        set_choice(ps, 'rampType', 'plunge zig zag', ('zig', 'zag', 'ramp'), rec)
    ang = _cfg_f(cfg, 'rampenwinkel' + suf, 3.0)
    leng = _cfg_f(cfg, 'rampenlaenge' + suf, 10.0)
    rad = _cfg_f(cfg, 'bogenradius' + suf, 5.0)
    pct = _cfg_f(cfg, 'einfahrt_pct' + suf, 50.0)
    set_number(ps, 'rampAngle', ang, rec)
    set_number(ps, 'leadInAngle', ang, rec)
    set_length(ps, 'rampLength', leng, rec)
    set_length(ps, 'horizontalLeadInDistance', leng, rec)
    set_length(ps, 'leadInSweepDistance', leng, rec)
    set_length(ps, 'leadInRadius', rad, rec)
    set_length(ps, 'horizontalLeadInRadius', rad, rec)
    # Einfahrvorschub % – Fusion oft 0..1 oder %
    set_number(ps, 'leadInFeedrate', pct, rec)
    set_number(ps, 'entry_feedrate', pct / 100.0 if pct > 1 else pct, rec)
    set_number(ps, 'rampFeedrate', pct, rec)
    rec['anfahr'] = {'art': art, 'winkel': ang, 'laenge': leng, 'radius': rad, 'pct': pct}


def feed_speed_params(op, cfg, premill, rec):
    """Schnittwerte vf/spindle (vc/fz informativ in rec)."""
    ps = op.parameters
    suf = _suf(premill)
    vf = _cfg_f(cfg, 'vf' + suf, 0.0)
    rpm = _cfg_f(cfg, 'spindle' + suf, 0.0)
    vc = _cfg_f(cfg, 'vc' + suf, 0.0)
    fz = _cfg_f(cfg, 'fz' + suf, 0.0)
    if vf > 0:
        set_number(ps, 'tool_feedCutting', vf, rec)
        set_number(ps, 'feedrate', vf, rec)
        set_number(ps, 'cuttingFeedrate', vf, rec)
    if rpm > 0:
        set_number(ps, 'tool_spindleSpeed', rpm, rec)
        set_number(ps, 'spindleSpeed', rpm, rec)
    rec['feeds'] = {'vf': vf, 'spindle': rpm, 'vc': vc, 'fz': fz}


def common_params(op, cfg, depth_mm, rec, finish=False, leave_mm=0.0, stock=None, premill=False):
    """Tiefe, Zustellung, Aufmaß, Richtung, Anfahren – für Innen- und Außenkonturen.
    leave_mm: Resttiefe über Endtiefe (Vorfräs); stock: radiales Aufmaß (None = schlicht_zugabe / 0 bei finish)."""
    ps = op.parameters
    climb, comp, keys = DIRECTION.get(_richtung_key(cfg, premill=premill), DIRECTION['gleich'])
    if _safe(lambda: ps.itemByName('compensation')) is not None:
        set_choice(ps, 'compensation', comp, keys, rec)
    elif _safe(lambda: ps.itemByName('direction')) is not None:
        set_choice(ps, 'direction', climb, keys, rec)
    else:
        rec['richtung'] = {'ok': False, 'error': 'weder compensation noch direction vorhanden'}
    set_choice(ps, 'bottomHeight_mode', 'from stock bottom', ('stock bottom', 'stockbottom'), rec)
    # Endtiefe = -durchstich; Vorfräs belässt leave_mm Material
    leave = max(0.0, float(leave_mm or 0.0))
    set_length(ps, 'bottomHeight_offset', -float(cfg['durchstich']) + leave, rec)
    cut_depth = max(0.1, float(depth_mm) - leave)
    suf = _suf(premill)
    zst = _cfg_f(cfg, 'az' + suf, _cfg_f(cfg, 'zustellung', 6.0))
    if not finish and 0 < zst < cut_depth - 1e-6:
        set_bool(ps, 'doMultipleDepths', True, rec)
        set_length(ps, 'maximumStepdown', zst, rec)
    else:
        set_bool(ps, 'doMultipleDepths', False, rec)
    if stock is None:
        zug = 0.0 if finish else float(cfg['schlicht_zugabe'])
    else:
        zug = float(stock)
    if zug > 0:
        set_bool(ps, 'useStockToLeave', True, rec)
        set_length(ps, 'stockToLeave', zug, rec)
        set_length(ps, 'verticalStockToLeave', 0.0, rec)
    else:
        set_bool(ps, 'useStockToLeave', False, rec)
    lead_in_params(op, cfg, premill, rec)
    feed_speed_params(op, cfg, premill, rec)


def tab_params(op, cfg, tabs, perimeter, pf, rec):
    """Haltestege: Form/Breite/Höhe; Lage über Skizzenpunkte (tabPositions), sonst Abstand (tabDistance)."""
    ps = op.parameters
    if not tabs:
        set_bool(ps, 'group_tabs', False, rec)
        return 'keine'
    set_bool(ps, 'group_tabs', True, rec)
    if cfg['steg_form'] == 'dreieckig':
        set_choice(ps, 'tabShape', 'triangular', ('triang', 'ramp', 'dreieck'), rec)
    else:
        set_choice(ps, 'tabShape', 'rectangular', ('rect', 'recht'), rec)
    set_length(ps, 'tabWidth', float(cfg['steg_breite']), rec)
    set_length(ps, 'tabHeight', float(cfg['steg_hoehe']), rec)
    pts = []
    if pf is not None:
        try:
            pts = [pf.add(t['pt'][0], t['pt'][1]) for t in tabs]
        except Exception as e:
            rec['tab_points_error'] = str(e)
            pts = []
    manualish = any(t.get('manual') or t.get('kind') == 'manuell' for t in tabs)
    if pts:
        mode = set_choice(ps, 'tabPositioning', 'tabCount', ('point', 'manual', 'tabcount', 'points'), rec)
        ok = set_objects(ps, 'tabPositions', pts, rec)
        if ok:
            set_number(ps, 'tabsPerContour', 0, rec)
            rec['tabs_mode'] = 'punkte (%s)' % mode
            return 'punkte'
        rec['tabs_points_rejected'] = True
    # Rückfall: gleichmäßiger Abstand
    set_choice(ps, 'tabPositioning', 'distance', ('dist', 'abstand'), rec)
    set_length(ps, 'tabDistance', max(float(cfg['steg_breite']) * 3, perimeter / max(1, len(tabs))), rec)
    rec['tabs_mode'] = 'abstand'
    msg = ('%s: Stege über Skizzenpunkte nicht möglich (Z/Kontext?) – Rückfall auf Stegabstand %.0f mm'
           % (_safe(lambda: op.name), perimeter / max(1, len(tabs))))
    if manualish:
        msg += ' – manuelle Stege ggf. nicht übernommen'
    L.warn('%s', msg)
    rec['tabs_fallback_warn'] = msg
    return 'abstand'


def entry_param(op, pf, pt, rec):
    if pf is None or pt is None:
        return False
    try:
        sp = pf.add(pt[0], pt[1])
    except Exception as e:
        rec['entryPositions'] = {'ok': False, 'error': str(e)}
        return False
    return set_objects(op.parameters, 'entryPositions', [sp], rec)


def _failed(rec):
    return sorted(k for k, v in rec.items() if isinstance(v, dict) and v.get('ok') is False)


def build_sheet_ops(cam, setup, sheet, plan, tool, cfg, version, state):
    """Alle FS-Operationen eines Rohteils. state: dict für Rohteil-übergreifendes (Parameter-Dump, Zähler).
    Gibt Liste der erzeugten Operationen und Protokoll-Einträge zurück. Fehler je Operation werden
    protokolliert und übersprungen."""
    ops, recs = [], []
    depth = float(sheet['thickness']) + float(cfg['durchstich'])
    parts = plan['parts']
    num = [0]

    def nr():
        num[0] += 1
        return num[0]

    def meta(kind, part=None):
        return {'kind': kind, 'sheet': sheet['name'], 'part': part, 'version': version}

    pf_start = pf_tabs = None
    try:
        recreate = bool(cfg['ersetzen'])
        z0 = sketch_z_mm(sheet)
        # 1.1.0: Bezugspunkte der Operationen IMMER in die Skizzen „… (berechnet)“ (werden nie gelesen);
        # die Anwender-Skizzen „Finalschnitt Stege/Startpunkte“ werden nie geschrieben
        # (ohne „Ersetzen“ bleiben alte Operationen und damit ihre Skizzen erhalten -> anhängen statt neu)
        if recreate:
            for nm in SK_LEGACY:                   # alte interne Skizzen (≤ 1.0.6) aufräumen – Ops sind gelöscht
                _sketch(sheet['occ'].component, nm, create=False, recreate=True)
        pf_start = PointFactory(sheet, SK_START_OUT, recreate, z0)
        pf_tabs = PointFactory(sheet, SK_TABS_OUT, recreate, z0)
    except Exception:
        L.exc('Skizzen für Start-/Stegpunkte')
        state['warnings'].append('%s: Skizzen für Start-/Stegpunkte nicht anlegbar – Stege über Abstand, '
                                 'Einstieg automatisch' % sheet['name'])

    try:                                       # 2.0.1: Silhouetten-Skizzen (vor dem ersten Kanten-Lesen)
        with TM.phase('Silhouetten-Skizzen'):
            made, removed, errs = silhouette_sketches(sheet, parts, plan['order'], bool(cfg['ersetzen']),
                                                      sketch_z_mm(sheet), state['warnings'])
        state['warnings'].extend(errs)
        if made or removed:
            L.info('%s: Silhouetten-Skizzen %d angelegt, %d veraltete gelöscht', sheet['name'], made, removed)
    except Exception as e:
        L.exc('Silhouetten-Skizzen')
        state['warnings'].append('%s: Silhouetten-Skizzen nicht anlegbar (%s)' % (sheet['name'], e))
        for i in plan['order']:
            g = parts[i]['geo']
            for lp in [g['outer']] + list(g['holes']):
                if lp.get('method') == 'skizze' and not lp.get('curves'):
                    lp['sketch_failed'] = True

    fresh = set()                              # 1.3.1: Teile, deren Kanten in DIESEM Lauf frisch gelesen wurden

    def refresh(idx_list, force=False):
        """Kanten frisch aus der B-Rep (nach Neuberechnung/Löschen/Skizzen sind alte Objekte ungültig)."""
        for i in idx_list:
            if (i in fresh and not force) or parts[i]['geo'].get('no_edges'):
                continue
            g0 = parts[i]['geo']
            if not force and all(FF.edges_valid(lp.get('edges')) for lp in [g0['outer']] + list(g0['holes'])
                                 + list(g0.get('pockets') or [])) and \
                    FF.edges_valid([q.get('face') for q in g0.get('pockets') or []]):
                fresh.add(i)               # 2.0.2: Kanten noch gültig -> nicht neu lesen (Silhouette ist teuer)
                TM.count('Kanten gültig, nicht neu gelesen')
                continue
            why = []
            ok = False
            try:
                with TM.phase("Kanten neu lesen"):
                    ok = FF.reread_geometry(sheet, parts[i], why)
            except Exception as e:
                why.append(str(e))
            fresh.add(i)
            TM.count('Kanten neu gelesen')
            if not ok or why:
                L.warn('%s / %s: Kanten neu lesen %s%s', sheet['name'], parts[i].get('name'),
                       'ok' if ok else 'FEHLGESCHLAGEN', (' – ' + '; '.join(why)) if why else '')

    def guarded(label, fn):
        rec = {'op': label}
        try:
            op = fn(rec)
            if op is not None:
                ops.append(op)
                k = rec.get('strategy')
                if k and k not in state['dumped']:
                    state['dumped'][k] = dump_params(op, k)
        except Exception as e:
            rec['error'] = str(e)
            L.exc('Operation %s' % label)
            state['warnings'].append('%s / %s: Fehler %s' % (sheet['name'], label, e))
        bad = _failed(rec)
        if bad:
            rec['not_ok'] = bad
            state['param_issues'].update(bad)
        recs.append(rec)

    # ---- Taschen
    if cfg['taschen']:
        refresh(plan['order'])
        faces = [q['face'] for i in plan['order'] for q in parts[i]['geo']['pockets'] if q.get('face') is not None]
        if faces:
            def mk_pockets(rec):
                op = new_op(setup, 'pocket2d', '%s%02d Taschen' % (PREFIX, nr()), tool, meta('taschen'), rec)
                set_pockets(op, faces, rec)
                set_choice(op.parameters, 'compensation', DIRECTION[_richtung_key(cfg, False)][1], DIRECTION[_richtung_key(cfg, False)][2], rec)
                zst = float(cfg['zustellung'])
                set_bool(op.parameters, 'doMultipleDepths', zst > 0, rec)
                if zst > 0:
                    set_length(op.parameters, 'maximumStepdown', zst, rec)
                return op
            guarded('Taschen', mk_pockets)

    def hole_chains(i, with_pt=False):
        g = parts[i]['geo']
        hs = [h for h in g['holes'] if FF.chain_geom(h)]
        out = [(FF.chain_geom(h), FF.chain_reverted(h['pts'], h['first_opposed'], want_cw=False) != bool(cfg['seite_umkehren']))
               for h in hs]
        if with_pt:
            return [(G.centroid(h['pts']) if len(h['pts']) >= 3 else (0.0, 0.0), c) for h, c in zip(hs, out)]
        return out

    no_edges = [parts[i].get('name') for i in plan['order'] if parts[i]['geo'].get('no_edges')]
    if no_edges:
        state['warnings'].append('%s: keine B-Rep-Kanten für %s – Kontur nur aus Projekt-Daten, keine Operation'
                                 % (sheet['name'], ', '.join(no_edges)))
    def sil_failed(i):
        g = parts[i]['geo']
        return any(lp.get('sketch_failed') for lp in [g['outer']] + list(g['holes']))
    bad = [parts[i].get('name') for i in plan['order'] if sil_failed(i)]
    if bad:
        state['warnings'].append('%s: Silhouette ohne Skizze für %s – Teil(e) NICHT geschnitten'
                                 % (sheet['name'], ', '.join(bad)))
    order = [i for i in plan['order'] if not parts[i]['geo'].get('no_edges') and not sil_failed(i)]

    def mk_inner(idx_list, label):
        def build(force=False):
            refresh(idx_list, force)
            pc = [e for i in idx_list for e in hole_chains(i, True)]
            # 1.1.0: Durchbrüche in der Kette „nächster Nachbar“ ab Nullpunkt (wie die Vorschau)
            return [pc[k][1] for k in G.nn_order([e[0] for e in pc])]

        def f(rec):
            chains = build()
            if not chains:
                return None
            op = new_op(setup, 'contour2d', label, tool, meta('innen'), rec)
            set_chains(op, chains, rec, refetch=lambda: build(True))
            common_params(op, cfg, depth, rec)
            set_bool(op.parameters, 'group_tabs', False, rec)
            if len(chains) > 1:
                set_bool(op.parameters, 'preserveOrder', True, rec)
            # 2.0.5: Startpunkte Innenkanten (gleiche nn_order wie chains)
            if pf_start is not None:
                refresh(idx_list)
                pc = [e for i in idx_list for e in hole_chains(i, True)]
                order_h = G.nn_order([e[0] for e in pc])
                # hole_starts parallel zu geo.holes mit chain_geom
                entries = []
                flat = []
                for i in idx_list:
                    hs_geo = [h for h in parts[i]['geo']['holes'] if FF.chain_geom(h)]
                    starts = parts[i].get('hole_starts') or []
                    for hi, h in enumerate(parts[i]['geo']['holes']):
                        if not FF.chain_geom(h):
                            continue
                        # index in hole_starts = index in all holes
                        st = starts[hi] if hi < len(starts) else None
                        pt = (st.get('entry') or st['pt']) if st else G.centroid(h['pts'])
                        flat.append(pt)
                # reorder flat like nn_order of centroids in pc
                # pc order before nn: flat should match pc order
                if len(flat) == len(pc):
                    entries = [flat[k] for k in order_h]
                else:
                    entries = flat
                if entries:
                    sps = [pf_start.add(pt[0], pt[1]) for pt in entries]
                    set_objects(op.parameters, 'entryPositions', sps, rec)
                    rec['inner_starts'] = len(sps)
            return op
        return f

    # Hinweis: Vorfräs-Innen bei innen_zuerst erst nach mk_inner_pass-Definition – siehe unten nach _vf().
    _innen_zuerst_done = False
    if cfg['innen_zuerst'] and not bool(cfg.get('vorfraesen')):
        if any(parts[i]['geo']['holes'] for i in order):
            guarded('Innen', mk_inner(order, '%s%02d Innen' % (PREFIX, nr())))
            _innen_zuerst_done = True

    def outer_chain(i):
        g = parts[i]['geo']['outer']
        return (FF.chain_geom(g), FF.chain_reverted(g['pts'], g['first_opposed'], want_cw=True) != bool(cfg['seite_umkehren']))

    def _vf():
        return bool(cfg.get('vorfraesen')) and float(cfg.get('vorfraes_rest_mm') or 0) > 1e-9

    def _vf_leave():
        return float(cfg.get('vorfraes_rest_mm') or 1.0)

    def _vf_stock():
        return float(cfg.get('vorfraes_aufmass') or 0.0)

    def mk_outer(i, finish, premill=False):
        p = parts[i]
        if premill:
            kind, mkey = 'Vorfräs', 'vorfraes'
        elif finish:
            kind, mkey = 'Schlicht', 'schlicht'
        else:
            kind, mkey = 'Außen', 'aussen'

        def f(rec):
            op = new_op(setup, 'contour2d', '%s%02d %s – %s' % (PREFIX, nr(), kind, p.get('name')), tool,
                        meta(mkey, p.get('key')), rec)
            refresh([i])
            set_chains(op, [outer_chain(i)], rec, refetch=lambda: (refresh([i], True), [outer_chain(i)])[1])
            if premill:
                common_params(op, cfg, depth, rec, finish=False, leave_mm=_vf_leave(), stock=_vf_stock(), premill=True)
                tcfg, tabs_on = _op_tab_cfg(cfg, premill=True)
                if tabs_on:
                    mode = tab_params(op, tcfg, p['tabs'], p['per'], pf_tabs, rec)
                else:
                    set_bool(op.parameters, 'group_tabs', False, rec)
                    mode = 'keine'
            else:
                common_params(op, cfg, depth, rec, finish=finish, premill=False)
                tcfg, tabs_on = _op_tab_cfg(cfg, premill=False)
                if tabs_on:
                    mode = tab_params(op, tcfg, p['tabs'], p['per'], pf_tabs, rec)
                else:
                    set_bool(op.parameters, 'group_tabs', False, rec)
                    mode = 'keine'
            entry_param(op, pf_start, p['start'].get('entry') or p['start']['pt'], rec)
            rec['part'] = p.get('name')
            rec['tabs'] = 0 if premill else len(p['tabs'])
            rec['premill'] = bool(premill)
            if rec.get('tabs_fallback_warn'):
                state['warnings'].append(rec['tabs_fallback_warn'])
            return op
        return f

    # Innen: optional Vorfräs (ohne Tabs), dann Final
    def mk_inner_pass(idx_list, label, premill=False):
        base = mk_inner(idx_list, label)
        if not premill:
            return base

        def f(rec):
            op = base(rec)
            if op is None:
                return None
            common_params(op, cfg, depth, rec, finish=False, leave_mm=_vf_leave(), stock=_vf_stock(), premill=True)
            tcfg, tabs_on = _op_tab_cfg(cfg, premill=True)
            if not tabs_on:
                set_bool(op.parameters, 'group_tabs', False, rec)
            rec['premill'] = True
            return op
        return f

    if cfg['innen_zuerst'] and _vf() and any(parts[i]['geo']['holes'] for i in order):
        guarded('Innen-Vorfräs', mk_inner_pass(order, '%s%02d Innen-Vorfräs' % (PREFIX, nr()), True))
        guarded('Innen', mk_inner(order, '%s%02d Innen' % (PREFIX, nr())))

    if cfg['gruppierung'] == 'eine':
        def mk_all(rec, premill=False, finish=False):
            kind = 'Vorfräs' if premill else ('Schlicht' if finish else 'Außen')
            mkey = 'vorfraes' if premill else ('schlicht' if finish else 'aussen')
            op = new_op(setup, 'contour2d', '%s%02d %s – alle Teile' % (PREFIX, nr(), kind), tool, meta(mkey), rec)
            refresh(order)
            set_chains(op, [outer_chain(i) for i in order], rec,
                       refetch=lambda: (refresh(order, True), [outer_chain(i) for i in order])[1])
            if premill:
                common_params(op, cfg, depth, rec, finish=False, leave_mm=_vf_leave(), stock=_vf_stock(), premill=True)
                tcfg, tabs_on = _op_tab_cfg(cfg, premill=True)
                if tabs_on:
                    tabs = [x for i in order for x in parts[i]['tabs']]
                    tab_params(op, tcfg, tabs, sum(parts[i]['per'] for i in order), pf_tabs, rec)
                else:
                    set_bool(op.parameters, 'group_tabs', False, rec)
            else:
                common_params(op, cfg, depth, rec, finish=finish, premill=False)
                tcfg, tabs_on = _op_tab_cfg(cfg, premill=False)
                if tabs_on:
                    tabs = [x for i in order for x in parts[i]['tabs']]
                    tab_params(op, tcfg, tabs, sum(parts[i]['per'] for i in order), pf_tabs, rec)
                else:
                    set_bool(op.parameters, 'group_tabs', False, rec)
            set_bool(op.parameters, 'preserveOrder', True, rec)
            if pf_start is not None:
                sps = [pf_start.add(*(parts[i]['start'].get('entry') or parts[i]['start']['pt'])) for i in order]
                set_objects(op.parameters, 'entryPositions', sps, rec)
            rec['premill'] = bool(premill)
            return op
        # Innen
        if cfg['innen_zuerst'] is False:
            if any(parts[i]['geo']['holes'] for i in order):
                if _vf():
                    guarded('Innen-Vorfräs', mk_inner_pass(order, '%s%02d Innen-Vorfräs' % (PREFIX, nr()), True))
                guarded('Innen', mk_inner(order, '%s%02d Innen' % (PREFIX, nr())))
        if _vf():
            guarded('Außen-Vorfräs (alle)', lambda rec: mk_all(rec, premill=True))
            guarded('Außen-Final (alle)', lambda rec: mk_all(rec, finish=True))
        else:
            guarded('Außen (alle)', lambda rec: mk_all(rec, premill=False, finish=False))
            if cfg.get('schlichtgang'):
                guarded('Schlicht (alle)', lambda rec: mk_all(rec, finish=True))
    else:
        for i in order:
            if not cfg['innen_zuerst'] and parts[i]['geo']['holes']:
                if _vf():
                    guarded('Innen-Vorfräs %s' % parts[i].get('name'),
                            mk_inner_pass([i], '%s%02d Innen-Vorfräs – %s' % (PREFIX, nr(), parts[i].get('name')), True))
                guarded('Innen %s' % parts[i].get('name'),
                        mk_inner([i], '%s%02d Innen – %s' % (PREFIX, nr(), parts[i].get('name'))))
            if _vf():
                guarded('Vorfräs %s' % parts[i].get('name'), mk_outer(i, False, premill=True))
                guarded('Final %s' % parts[i].get('name'), mk_outer(i, True, premill=False))
            else:
                guarded('Außen %s' % parts[i].get('name'), mk_outer(i, False))
                if cfg['schlichtgang']:
                    guarded('Schlicht %s' % parts[i].get('name'), mk_outer(i, True))
    if pf_start is not None:
        state['context'].update(pf_start.ctx)
    if pf_tabs is not None:
        state['context'].update(pf_tabs.ctx)
    flush_points()
    return ops, recs


def generate(cam, ops):
    """Werkzeugwege berechnen (cam.generateToolpath mit ObjectCollection). Wartet nicht.
    Nur aufrufen, wenn der Anwender „Werkzeugwege berechnen“ angehakt hat (fs_run prüft das)."""
    if not ops:
        return None
    try:
        L.checkpoint('cam.generateToolpath(%d Operation(en))', len(ops))
        fut = cam.generateToolpath(_coll(ops))
        L.info('Werkzeugwege: Berechnung für %d Operation(en) gestartet', len(ops))
        return fut
    except Exception:
        L.exc('generateToolpath')
        return None


def tabs_hint(plan):
    n = sum(len(p['tabs']) for p in plan['parts'])
    b = len(plan['bridges'])
    return '%d Stege (%d Brückenpaare)' % (n, b)


def failed_contours(recs):
    """Namen der Operationen, deren Konturauswahl fehlgeschlagen ist (1.3.1)."""
    return [r.get('name') or r.get('op') for r in recs if (r.get('contours') or {}).get('ok') is False]


def summary_line(sheet, plan, ops, recs):
    n_err = sum(1 for r in recs if r.get('error'))
    return ('%s: %d Operation(en), %d Teile, %d Durchbrüche, %s%s' % (
        sheet['name'], len(ops), len(plan['order']), sum(len(p['holes']) for p in plan['parts']), tabs_hint(plan),
        (', %d Fehler' % n_err) if n_err else ''))


def depth_text(cfg, thickness):
    d = float(thickness) + float(cfg['durchstich'])
    n = int(math.ceil(d / float(cfg['zustellung']))) if float(cfg['zustellung']) > 0 else 1
    return '%.1f mm in %d Zustellung(en)' % (d, max(1, n))


__all__ = ['G']
