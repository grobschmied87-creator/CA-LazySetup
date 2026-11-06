# -*- coding: utf-8 -*-
"""Finalschnitt – Ablauf (ohne Dialog, testbar): Rohteile lesen -> planen -> Vorschau -> Operationen."""
import json

import fs_cam as C
import fs_edit as E
import fs_fusion as F
import fs_geom as G
import fs_log as L
import fs_timing as TM

_safe = F._safe


def collect(design, cam=None, names=None, warn=None):
    """Rohteile mit Konturen; names = Liste der gewählten Rohteil-Namen (None = alle)."""
    out = []
    F.CACHE_SIG = tuple(core_sig(design)) if core_sig(design)[1] is not None else None   # 2.0.2
    if len(F.GEO_CACHE) > 2000:
        F.clear_cache()
    for occ, d in F.find_sheets(design):
        nm = _safe(lambda: occ.name, '')
        if names is not None and nm not in names:
            continue
        try:
            out.append(F.read_sheet(occ, d, cam, warn, design, L.info))
        except Exception as e:
            L.exc('Rohteil lesen %s' % nm)
            if warn is not None:
                warn.append('%s: nicht lesbar (%s)' % (nm, e))
    return out


def cfg_hash(cfg):
    """Kurzer Hash der Planungs-Einstellungen (Protokoll: Vorschau und Ausführen vergleichbar)."""
    import hashlib
    import json
    return hashlib.sha1(json.dumps(cfg, sort_keys=True, default=str).encode('utf-8')).hexdigest()[:10]


def plan_cfg(cfg, tool_entry=None):
    """EINZIGE Stelle, an der die Planungs-Einstellungen festgelegt werden – für Vorschau UND Operationen
    (1.0.5): Vorgaben + Dialogwerte, Werkzeug-Ø aus dem gewählten Werkzeug (sonst Planungs-Ø)."""
    raw = dict(cfg or {})
    cfg = dict(G.DEFAULTS, **raw)
    # 2.0.9: Legacy zustellung → az_vor/az_final wenn nur zustellung gesetzt
    if 'zustellung' in raw and 'az_vor' not in raw and 'az_final' not in raw:
        try:
            z = float(raw['zustellung'])
            cfg['az_vor'] = cfg['az_final'] = z
            cfg['zustellung'] = z
        except (TypeError, ValueError):
            pass
    cfg['stege_vor'] = False
    cfg['bruecken_vor'] = False
    if tool_entry and tool_entry.get('info', {}).get('d_mm'):
        cfg['tool_d'] = float(tool_entry['info']['d_mm'])
    return cfg


def sketch_inputs(sheet, cfg):
    """Eingaben neben den Einstellungen: Punkte der ANWENDER-Skizzen (nur wenn „aus Skizze“ an; die
    berechneten Skizzen „… (berechnet)“ werden nie gelesen) und die Bearbeitungen aus der Palette (1.2.0)."""
    st = tb = None
    ov = E.empty()
    try:
        ov = E.load(sheet)
    except Exception:
        L.exc('Bearbeitungen lesen %s' % sheet.get('name'))
    try:
        if cfg.get('skizze_start'):
            st = C.read_sketch_points(sheet, C.SK_START)
        if cfg.get('skizze_stege'):
            tb = C.read_sketch_points(sheet, C.SK_TABS)
    except Exception:
        L.exc('Skizzenpunkte lesen %s' % sheet.get('name'))
    return {'start': st, 'tabs': tb, 'ov': ov}


def plan_hash(sheet, cfg, sk=None):
    """Planungs-Hash eines Rohteils: Einstellungen + (falls „aus Skizze“) die Skizzenpunkte."""
    import hashlib
    if sk is None:
        sk = sketch_inputs(sheet, cfg)
    pts = {k: [[round(x, 2), round(y, 2)] for x, y in v] if v is not None else None
           for k, v in sk.items() if k in ('start', 'tabs')}
    pts['ov'] = E.canonical(sk.get('ov')) if not E.is_empty(sk.get('ov')) else None
    raw = cfg_hash(cfg) + json.dumps(pts, sort_keys=True)
    return hashlib.sha1(raw.encode('utf-8')).hexdigest()[:10]


def make_plan(sheet, cfg, manual=True, sk=None):
    """Plan eines Rohteils (Reihenfolge, Start, Stege, Brücken, Skizzenpunkte) – dieselbe Funktion für
    Dialog-Vorschau und Operationen. cfg muss aus plan_cfg() kommen."""
    if sk is None:
        sk = sketch_inputs(sheet, cfg)
    plan = G.plan_sheet(sheet, cfg, sk.get('ov'))
    _log_order(sheet, plan)
    ovi = plan.get('overrides') or {}
    if ovi.get('parts') or ovi.get('bridges_add') or ovi.get('bridges_del') or ovi.get('stale'):
        L.info('%s: Bearbeitungen (Palette) – Teile %s, Brücken +%d/−%d, veraltet %s', sheet['name'],
               ovi.get('parts'), ovi.get('bridges_add', 0), ovi.get('bridges_del', 0), ovi.get('stale'))
    if manual and (cfg.get('skizze_start') or cfg.get('skizze_stege')):
        st, tb = sk.get('start'), sk.get('tabs')
        r = G.apply_manual(plan, st, tb)
        L.info('%s: Skizzenpunkte übernommen start=%d stege=%d (Brücken %d) ignoriert=%d %s', sheet['name'],
               r['start'], r['tabs'], r['bridges'], r['ignored'],
               ('ignorierte Punkte %s' % [[round(v, 1) for v in q] for q in r['ignored_pts']]) if r['ignored'] else '')
        if cfg.get('skizze_stege'):
            plan['warnings'].insert(0, '%s: Stege kommen aus Skizze „%s“ – Steg-Einstellungen wirkungslos'
                                    % (sheet['name'], C.SK_TABS))
        if cfg.get('skizze_start') and not r['start']:
            plan['warnings'].append('%s: keine Startpunkte in Skizze „%s“ – berechnete verwendet'
                                    % (sheet['name'], C.SK_START))
        if cfg.get('skizze_stege') and not r['tabs']:
            plan['warnings'].append('%s: keine Stegpunkte in Skizze „%s“ – berechnete verwendet'
                                    % (sheet['name'], C.SK_TABS))
        elif cfg.get('skizze_stege') and r['parts_without']:
            plan['warnings'].append('%s: %d Teil(e) ohne Skizzen-Stegpunkte – dort berechnete Stege (%s)'
                                    % (sheet['name'], len(r['parts_without']), ', '.join(r['parts_without'][:6])))
        if r['ignored']:
            plan['warnings'].append('%s: %d Skizzenpunkt(e) passen zu keinem Teil des aktuellen Nestings '
                                    '(> 15 mm von jeder Außenkontur) – ignoriert' % (sheet['name'], r['ignored']))
    return plan


def _log_order(sheet, plan):
    tm = plan.get('timing') or {}
    if plan.get('order_info'):
        ps = plan['parts']
        L.info('%s: Reihenfolge „Restfläche“ (%.3f s, Raster %.1f mm, %d Auswertungen): %s', sheet.get('name'),
               tm.get('sekunden', 0.0), tm.get('raster_mm', 0.0), tm.get('auswertungen', 0),
               '; '.join('%d. %s Rest %.1f %% (%d Bereich%s) Eilgang %.0f mm' % (
                   k + 1, ps[e['idx']].get('name'), e['rest_pct'], e['bereiche'], '' if e['bereiche'] == 1 else 'e',
                   e['eilgang_mm']) for k, e in enumerate(plan['order_info'])))
    elif plan.get('order'):
        L.info('%s: Reihenfolge „Gewichtung“ (alt): %s', sheet.get('name'),
               ', '.join(str(plan['parts'][i].get('name')) for i in plan['order']))


def preview_png(plan, sheet, tag=''):
    safe = ''.join(c if c.isalnum() else '_' for c in sheet['name'])
    path = L.path('preview_%s_%s%s.png' % (safe, L.stamp(), tag))
    try:
        G.render_preview(plan, path)
        L._prune('preview_')
        return path
    except Exception:
        L.exc('Vorschau')
        return ''


def preview_contact(plans, tag=''):
    """Übersicht aller Rohteile (Kacheln) als PNG; '' bei Fehler."""
    path = L.path('preview_alle_%s%s.png' % (L.stamp(), tag))
    try:
        G.render_contact(plans, path)
        L._prune('preview_')
        return path
    except Exception:
        L.exc('Vorschau Übersicht')
        return ''


REFS = None            # ca_core.ca_refs (von LazySetup.py gesetzt); None = Prüfung nicht verfügbar
LAST_COMPUTE = {}      # Stand nach der letzten erfolgreichen Neuberechnung (doppeltes computeAll vermeiden)


def design_sig(design):
    """Kennung des Konstruktionsstands: Dokument, Zeitachse (Anzahl/Marker), Typ, Änderungsflag.
    Gleiche Kennung wie nach der letzten Neuberechnung -> computeAll nicht nötig."""
    tl = _safe(lambda: design.timeline)
    return (_safe(lambda: design.parentDocument.name, ''), _safe(lambda: design.parentDocument.dataFile.versionNumber),
            _safe(lambda: tl.count) if tl is not None else None,
            _safe(lambda: tl.markerPosition) if tl is not None else None,
            _safe(lambda: int(design.designType)), _safe(lambda: bool(design.parentDocument.isModified)))


def models_safe(setup):
    """(ok, grund): Modelle des Setups gefahrlos lesbar? Nach gelöschten/ersetzten Teilen (LazyNest „Nesting
    bearbeiten“) können Verweise ungültig sein – dann das Setup NICHT anfassen (Fusion-Absturz 12.10.2026)."""
    try:
        ms = setup.models
        items = list(ms) if isinstance(ms, (list, tuple)) else None     # Testattrappe
        n = len(items) if items is not None else ms.count
        for i in range(n):
            m = items[i] if items is not None else ms.item(i)
            if m is None or not _safe(lambda: m.isValid, True):
                return False, 'Modell %d von %d ungültig' % (i + 1, n)
        return True, ''
    except Exception as e:
        return False, str(e)


STATE_GROUP, STATE_NAME = 'CA_Tools', 'compute_state'   # 2.0.2: gemeinsam mit LazyNest 2.0.2


def core_sig(design):
    """2.0.2: Kennung für „Zeitachse unverändert seit der letzten Neuberechnung“: Dokument, Zeitachse
    (Anzahl/Marker), Typ – OHNE Version/Änderungsflag (Speichern, Attribute und CAM ändern die Geometrie nicht)."""
    tl = _safe(lambda: design.timeline)
    return [_safe(lambda: design.parentDocument.name, ''),
            _safe(lambda: tl.count) if tl is not None else None,
            _safe(lambda: tl.markerPosition) if tl is not None else None,
            _safe(lambda: int(design.designType))]


def read_state(design):
    a = _safe(lambda: design.attributes.itemByName(STATE_GROUP, STATE_NAME))
    try:
        return json.loads(a.value) if a is not None else None
    except Exception:
        return None


CC = None              # 2.0.3: ca_core.ca_compute (von LazySetup.py gesetzt); None = kein gemeinsamer Stand


def write_state(design, by):
    """Stand „neu berechnet/unverändert“ im Design ablegen (Attribut, keine Zeitachsen-Änderung).
    2.0.3: Fingerabdruck CA_Tools/computed_state (ca_core.ca_compute); das alte 2.0.2-Attribut bleibt nur zur
    Diagnose erhalten."""
    sig = core_sig(design)
    if sig[1] is not None:
        LAST_COMPUTE['core'] = sig
    if CC is None:
        return
    import time
    t0 = time.time()
    ok, fp = CC.write(design, by)
    if ok:
        LAST_COMPUTE['fp'] = fp
        L.info('Neuberechnungs-Stand gespeichert (%s, %.0f ms): %s', by, (time.time() - t0) * 1000.0, fp)
    else:
        L.warn('Neuberechnungs-Stand nicht gespeichert: %s', fp)


def _skip_reason(design):
    """2.0.3: (überspringen?, Text). Überspringen NUR, wenn der aktuelle Fingerabdruck vollständig bestimmbar
    ist und exakt dem gespeicherten Stand nach dem letzten erfolgreichen computeAll (LazyNest oder LazySetup)
    entspricht. Sonst (nicht bestimmbar, kein Stand, Abweichung) -> computeAll wie bisher."""
    if CC is None:
        return False, 'Kern ohne ca_compute'
    import time
    t0 = time.time()
    cur = CC.fingerprint(design)
    ms = (time.time() - t0) * 1000.0
    st = CC.read(design)
    same, why = CC.compare(st, cur)
    # Diagnose: alter 2.0.2-Stand (warum hat 2.0.2 neu berechnet?)
    old = read_state(design)
    if old is not None:
        L.info('Neuberechnung: alter Stand 2.0.2 %s von %s, aktuell %s', old.get('sig'), old.get('by'), core_sig(design))
    L.info('Neuberechnung: Fingerabdruck %s (%.0f ms), gespeichert %s -> %s', cur, ms,
           (st or {}).get('fp'), why)
    if same and LAST_COMPUTE.get('fp') not in (None, cur) and (st or {}).get('by') == 'LazySetup':
        return False, 'Sitzungsstand widerspricht dem Attribut'
    return same, why


def compute_ok(design, res, mode='auto'):
    """design.computeAll() vor jeder CAM-Änderung (Lehre aus ContourNest 1.8.1). False = abbrechen.
    2.0.0 (Hänger KMD-PC-03 12:50, fs_run.py:153 mit 4 veralteten Verknüpfungen): zuerst veraltete Verknüpfungen
    prüfen und mit Meldung abbrechen; nur neu berechnen, wenn nötig (parametrisch und Stand geändert);
    Checkpoint NACH dem Rücksprung.
    2.0.3: „auto“ vergleicht den Fingerabdruck der Zeitachse mit dem Stand nach der letzten erfolgreichen
    Neuberechnung (Design-Attribut CA_Tools/computed_state, geschrieben von LazyNest UND LazySetup)."""
    od, checked = REFS.outdated(design) if REFS is not None else ([], False)
    if od:
        L.warn('Abbruch vor computeAll – veraltete Verknüpfungen: %s', json.dumps(od, ensure_ascii=False, default=str))
        res['errors'] += 1
        res['aborted'] = True
        res['outdated'] = od
        res['lines'].append(REFS.message(od, 'Erstellung der Operationen (Neuberechnung)'))
        return False
    L.info('Verknüpfungen: %s', 'aktuell' if checked else 'nicht prüfbar (API fehlt)')
    if _safe(lambda: int(design.designType)) == 0:          # DirectDesignType: keine Zeitachse
        L.info('Direkte Modellierung – computeAll nicht nötig')
        return True
    if mode == 'nie':
        L.info('computeAll übersprungen – Einstellung „Neuberechnen: nie“')
        res.setdefault('compute', 'nie')
        return True
    sig = design_sig(design)
    if mode != 'immer' and sig[2] is not None and sig[3] is not None and LAST_COMPUTE.get('sig') == sig:
        L.info('computeAll übersprungen – Konstruktion seit der letzten Neuberechnung unverändert %s', sig)
        res['compute'] = 'übersprungen'
        return True
    if mode != 'immer':
        skip, why = _skip_reason(design)
        if skip:
            st = (CC.read(design) if CC is not None else None) or {}
            L.info('computeAll übersprungen: Modell seit %s-Berechnung unverändert (%s)', st.get('by', '?'), why)
            res['compute'] = 'übersprungen'
            res['compute_by'] = st.get('by')
            return True
        L.info('computeAll nötig: %s', why)
    try:
        import time
        t0 = time.time()
        L.checkpoint('design.computeAll() vor CAM-Änderungen')
        F.clear_cache()                          # 2.0.2: Neuberechnung -> gelesene B-Rep-Objekte ungültig
        design.computeAll()
        L.checkpoint('design.computeAll() fertig (%.1f s)' % (time.time() - t0))
        LAST_COMPUTE['sig'] = design_sig(design)
        res['compute'] = 'ausgeführt'
        write_state(design, 'LazySetup')
        return True
    except Exception as e:
        L.exc('computeAll')
        if CC is not None:
            CC.clear(design)
        res['errors'] += 1
        res['lines'].append('Abbruch vor jeder CAM-Änderung: Neuberechnung der Konstruktion fehlgeschlagen (%s). '
                            'Bitte Zeitachse/Fehler prüfen und erneut ausführen.' % e)
        return False


def run(app, ui, design, cfg, names=None, tool_entry=None, version='', ask_setup=None):
    """Hauptablauf. Wirft nie. Rückgabe dict: lines (deutsch), warnings, ops, previews, plans."""
    res = {'lines': [], 'warnings': [], 'ops': 0, 'previews': [], 'plans': [], 'errors': 0}
    cfg = plan_cfg(cfg, tool_entry)
    TM.reset()
    F.CACHE_STATS.update(hit=0, miss=0)
    import time as _time
    t_run = _time.perf_counter()
    try:
        if C.adsk.cam is None:
            res['lines'].append('CAM-API nicht verfügbar.')
            return res
        tool = tool_entry['tool'] if tool_entry else None
        pass_tools = {
            'default': tool,
            'vor': ((tool_entry or {}).get('vor') or {}).get('tool') or tool,
            'final': ((tool_entry or {}).get('final') or {}).get('tool') or tool,
        }
        L.info('Planung: Werkzeug-Ø %g mm, cfg-Hash %s', cfg['tool_d'], cfg_hash(cfg))
        if tool is None:
            res['warnings'].append('Kein Werkzeug gewählt – Operationen ohne Werkzeug (in Fusion nachtragen).')
        cam = C.get_cam(app, ui)
        if cam is None:
            res['lines'].append('Kein CAM-Produkt – Arbeitsbereich FERTIGUNG einmal öffnen.')
            return res
        # 1.3.1: Konstruktion ZUERST neu berechnen (Lehre aus ContourNest 1.8.1), erst DANACH B-Rep lesen –
        # computeAll baut parametrische Körper neu auf und macht vorher gelesene Kanten ungültig
        # (ADALAP 10.10.: „InternalValidationError : edge“, keine Konturen in den Operationen)
        with TM.phase('Prüfen + Neuberechnen'):
            ok_c = compute_ok(design, res, cfg.get('neuberechnen') or 'auto')
        if not ok_c:
            return res
        with TM.phase('Einlesen'):
            sheets = collect(design, cam, names, res['warnings'])
        if not sheets:
            res['lines'].append('Keine ContourNest-Rohteile gefunden (Attribut ContourNest/sheet).')
            return res
        state = {'dumped': {}, 'warnings': res['warnings'], 'param_issues': set(), 'context': set(),
                 'pass_tools': pass_tools}
        all_ops = []
        # Phase 1 – nur lesen/planen (keine CAM-Änderung)
        jobs = []
        for sh in sheets:
            try:
                if not sh['parts']:
                    res['warnings'].append('%s: keine Teile mit lesbarer Unterseite' % sh['name'])
                    continue
                sk = sketch_inputs(sh, cfg)
                L.info('Planung %s: Planungs-Hash %s (Werkzeug-Ø %g mm)', sh['name'], plan_hash(sh, cfg, sk),
                       cfg['tool_d'])
                with TM.phase('Planen'):
                    plan = make_plan(sh, cfg, sk=sk)
                res['warnings'] += plan['warnings']
                with TM.phase('Vorschau'):
                    png = preview_png(plan, sh)
                res['previews'].append(png)
                summ = G.plan_summary(plan)
                setup, how = C.find_setup(cam, sh)
                if setup is not None:
                    ok, why = models_safe(setup)
                    L.info('%s: Setup %s – Modelle %s', sh['name'], _safe(lambda: setup.name),
                           'lesbar' if ok else 'NICHT sicher lesbar (%s)' % why)
                    if not ok:
                        res['errors'] += 1
                        res['warnings'].append('%s: Modelle des Setups „%s“ nicht sicher lesbar (%s) – Rohteil '
                                               'übersprungen. Bitte in FERTIGUNG: Setup bearbeiten → Modell neu '
                                               'wählen, dann erneut ausführen.' % (sh['name'],
                                                                                   _safe(lambda: setup.name), why))
                        setup = 'skip'
                jobs.append([sh, plan, summ, setup, how])
            except Exception as e:
                res['errors'] += 1
                L.exc('Rohteil %s' % sh.get('name'))
                res['warnings'].append('%s: Fehler %s' % (sh.get('name'), e))
        # Phase 2 (1.0.2) – Neuberechnung: ab 1.3.1 vor dem Einlesen (siehe oben)
        # Phase 3 – alte FS-Operationen ALLER Rohteile löschen, BEVOR Skizzen/Auswahlen angefasst werden
        for j in jobs:
            sh, setup = j[0], j[3]
            j.append(0)
            if setup not in (None, 'skip') and cfg['ersetzen']:
                try:
                    with TM.phase('Alte Operationen löschen'):
                        j[5] = C.delete_old(setup, cam, sh['name'])
                except Exception as e:
                    res['errors'] += 1
                    L.exc('Alte FS-Operationen %s' % sh['name'])
                    res['warnings'].append('%s: alte FS-Operationen nicht löschbar (%s) – Rohteil übersprungen'
                                           % (sh['name'], e))
                    j[3] = 'skip'
        # Phase 4 – neue Operationen
        for sh, plan, summ, setup, how, removed in jobs:
            try:
                if setup == 'skip':
                    res['plans'].append(summ)
                    continue
                if setup is None:
                    if ask_setup is not None and ask_setup(sh):
                        setup = C.create_simple_setup(cam, sh, version)
                        how = 'neu (LazySetup)'
                    else:
                        res['warnings'].append('%s: kein CAM-Setup – übersprungen (ContourNest „Nesting bearbeiten“ → '
                                               'Fertigung: CAM-Setup je Rohteil, oder hier anlegen lassen)' % sh['name'])
                        res['plans'].append(summ)
                        continue
                else:
                    try:                        # 1.3.0: Nullpunkt/Rohteilmaß aus dem ContourNest-Projekt
                        wchg, wrec = C.ensure_wcs(setup, sh)
                        summ['wcs'] = {'box_point': sh.get('box_point'), 'changed': wchg, 'params': wrec}
                        if wchg:
                            L.info('%s: Setup angepasst – %s', sh['name'], ', '.join(wchg))
                    except Exception as e:
                        L.exc('WCS %s' % sh.get('name'))
                        res['warnings'].append('%s: Nullpunkt/Rohteil im Setup nicht geprüft (%s)' % (sh['name'], e))
                with TM.phase('Operationen anlegen'):
                    ops, recs = C.build_sheet_ops(cam, setup, sh, plan, tool, cfg, version, state)
                all_ops += ops
                res['ops'] += len(ops)
                summ.update({'setup': _safe(lambda: setup.name), 'setup_found_by': how, 'removed_ops': removed,
                             'operations': recs})
                res['plans'].append(summ)
                bad = C.failed_contours(recs)
                line = C.summary_line(sh, plan, ops, recs)
                if bad:                        # 1.3.1: keine irreführende Erfolgszeile
                    res['errors'] += 1
                    nm = sh['name'].split(':')[0]
                    line = '%s: Konturauswahl fehlgeschlagen – %d von %d Operation(en) ohne Geometrie (%s)' % (
                        nm, len(bad), len(ops), ', '.join(bad))
                    res['warnings'].insert(0, line + ' – bitte erneut ausführen, Details logs/finalschnitt.log')
                    L.warn('%s', line)
                if removed:
                    line += ' (%d alte FS-Operationen ersetzt)' % removed
                if (summ.get('wcs') or {}).get('changed'):
                    line += '; Setup angepasst: ' + ', '.join(summ['wcs']['changed'])
                res['lines'].append(line)
                res['errors'] += sum(1 for r in recs if r.get('error'))
            except Exception as e:
                res['errors'] += 1
                L.exc('Rohteil %s' % sh.get('name'))
                res['warnings'].append('%s: Fehler %s' % (sh.get('name'), e))
        # Werkzeugwege NUR, wenn ausdrücklich angehakt (cfg['berechnen'] is True) – nie automatisch
        if cfg.get('berechnen') is True and all_ops:
            with TM.phase('Werkzeugwege starten'):
                res['generate'] = C.generate(cam, all_ops) is not None
            res['lines'].append('Werkzeugwege: Berechnung %s.' % ('gestartet' if res['generate'] else 'NICHT gestartet'))
        elif all_ops:
            res['lines'].append('Werkzeugwege: nicht berechnet (Option „Werkzeugwege berechnen“ aus) – in FERTIGUNG '
                                'mit „Generieren“ berechnen.')
        if state['param_issues']:
            res['warnings'].append('Parameter nicht gesetzt/bestätigt (Details logs/plan_*.json): '
                                   + ', '.join(sorted(state['param_issues'])))
        res['param_dumps'] = state['dumped']
        res['point_context'] = sorted(state['context'])
        return res
    except Exception as e:
        res['errors'] += 1
        L.exc('run')
        res['lines'].append('Abbruch: %s (Details logs/finalschnitt.log)' % e)
        return res
    finally:
        try:
            if res.get('compute') in ('ausgeführt', 'übersprungen') and not res.get('aborted'):
                write_state(design, 'LazySetup')     # eigene Skizzen sind berechnet -> nächster Lauf ohne computeAll
        except Exception:
            pass
        TM.add('Gesamt', (_time.perf_counter() - t_run) * 1000.0)
        res['timing'] = TM.data()
        TM.count('Geometrie-Cache Treffer', F.CACHE_STATS['hit'])
        L.info('Zeiten (ms): %s', TM.report())
        try:
            res['plan_file'] = L.dump_json('plan', {'cfg': {k: v for k, v in cfg.items()},
                                                    'result': {k: v for k, v in res.items() if k != 'plans'},
                                                    'plans': res['plans']})
            L.info('Ergebnis: %s', json.dumps({'lines': res['lines'], 'warnings': res['warnings']}, ensure_ascii=False))
        except Exception:
            pass
