# -*- coding: utf-8 -*-
"""Finalschnitt – Lesen der ContourNest-Ergebnisse aus dem Fusion-Design.

Rohteil  = Occurrence unter der Wurzel mit Attribut ContourNest/sheet (JSON: index, length_mm, width_mm,
           thickness_mm, project_id, project_sheet …), Körper „Rohteil“.
Teil     = Kind-Occurrence des Rohteils mit Attributen ContourNest/part_name, small_part, critical_vacuum …
Kontur   = 2.0.1: SILHOUETTE (fs_silhouette, Draufsicht aller Flächen): äußerster Umriss -> Außenkontur, nur
           durchgehende Öffnungen -> Durchbrüche. Entspricht eine Silhouetten-Schleife genau einer B-Rep-Schleife,
           werden deren Kanten verwendet (Bögen bleiben Bögen), sonst Skizzenkurven (fs_cam.silhouette_sketches).
           Taschen = nach oben zeigende ebene Flächen zwischen Unter- und Oberseite (äußere Schleife).
Alle Koordinaten werden ins Rohteil-System (mm, Ursprung = Rohteil-Ursprung) umgerechnet.
Die Kanten (BRepEdge) werden für die Kettenauswahl der CAM-Operation mitgegeben – bevorzugt aus dem
CAM-Modellkontext (cam.designRootOccurrence), damit Fusion sie dem Setup-Modell zuordnen kann.
"""
import json
import math

import fs_geom as G
import fs_sheet as S
import fs_silhouette as SIL

CN = 'ContourNest'
MM = 0.1            # 1 mm in cm
STROKE_TOL = 0.005  # cm (0,05 mm) Sehnenfehler beim Abtasten der Kanten


def _safe(fn, default=None):
    try:
        return fn()
    except Exception:
        return default


def items(coll):
    if coll is None:
        return []
    if isinstance(coll, (list, tuple)):
        return list(coll)
    n = _safe(lambda: coll.count)
    if isinstance(n, int):
        return [coll.item(i) for i in range(n)]
    try:
        return list(coll)
    except Exception:
        return []


def attr(ent, name, group=CN, as_json=False, default=None):
    a = _safe(lambda: ent.attributes.itemByName(group, name))
    if not a:
        return default
    v = _safe(lambda: a.value)
    if as_json:
        return _safe(lambda: json.loads(v), default)
    return v if v is not None else default


def _flag(ent, name):
    v = attr(ent, name)
    return str(v).strip().lower() in ('1', 'true', 'ja', 'yes')


# ---------------------------------------------------------------- Koordinaten
class Frame:
    """Rohteil-Koordinatensystem aus occurrence.transform2 (Welt -> lokal, cm -> mm)."""

    def __init__(self, occ=None):
        self.o, self.x, self.y, self.z = (0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1)
        cs = _safe(lambda: occ.transform2.getAsCoordinateSystem()) if occ is not None else None
        if cs and len(cs) == 4:
            o, x, y, z = cs
            self.o = (o.x, o.y, o.z)
            self.x, self.y, self.z = ((x.x, x.y, x.z), (y.x, y.y, y.z), (z.x, z.y, z.z))

    def local(self, p):
        """Weltpunkt (cm, Objekt mit x/y/z oder Tupel) -> lokal (mm)."""
        q = (p.x, p.y, p.z) if hasattr(p, 'x') else tuple(p)
        d = (q[0] - self.o[0], q[1] - self.o[1], q[2] - self.o[2])
        return tuple(sum(a * b for a, b in zip(d, ax)) / MM for ax in (self.x, self.y, self.z))

    def ldir(self, v):
        q = (v.x, v.y, v.z) if hasattr(v, 'x') else tuple(v)
        return tuple(sum(a * b for a, b in zip(q, ax)) for ax in (self.x, self.y, self.z))


def loop_points(loop, frame, seg_edge=None, einfo=None):
    """Punkte (x, y, z in mm, Rohteil) einer BRepLoop in Coedge-Reihenfolge + Kanten + erste Coedge gegenläufig?
    seg_edge (Liste, 2.0.1): wird mit dem Kantenindex je Strecke pts[i] -> pts[i+1] (zyklisch) gefüllt.
    einfo (Liste, 2.0.2): je Kante {'start': natürlicher Anfang (x, y), 'z': (min, max), 'len': projizierte Länge}."""
    pts, edges = [], []
    owner = []
    first_opp = None
    for ce in items(_safe(lambda: loop.coEdges)):
        edge = ce.edge
        ev = edge.evaluator
        ok, p0, p1 = ev.getParameterExtents()
        ok2, strokes = ev.getStrokes(p0, p1, STROKE_TOL)
        if not (ok and ok2) or not strokes:
            raise RuntimeError('Kante nicht abtastbar')
        q = [frame.local(p) for p in strokes]
        if einfo is not None:
            einfo.append({'start': (q[0][0], q[0][1]), 'end': (q[-1][0], q[-1][1]),
                          'z': (min(v[2] for v in q), max(v[2] for v in q)),
                          'len': sum(math.hypot(q[i + 1][0] - q[i][0], q[i + 1][1] - q[i][1])
                                     for i in range(len(q) - 1))})
        opp = bool(_safe(lambda: ce.isOpposedToEdge, False))
        if first_opp is None:
            first_opp = opp
        if opp:
            q.reverse()
        if pts and abs(pts[-1][0] - q[0][0]) < 1e-3 and abs(pts[-1][1] - q[0][1]) < 1e-3:
            q = q[1:]
        pts.extend(q)
        owner.extend([len(edges)] * len(q))
        edges.append(edge)
    if len(pts) > 1 and abs(pts[0][0] - pts[-1][0]) < 1e-3 and abs(pts[0][1] - pts[-1][1]) < 1e-3:
        pts.pop()
        owner.pop()
    if seg_edge is not None:
        n = len(pts)
        seg_edge[:] = [owner[i + 1] if i + 1 < n else len(edges) - 1 for i in range(n)]
    return pts, edges, bool(first_opp)


def _planar_z_faces(body, frame, stats=None):
    """Ebene Flächen mit Normale ±Z (Rohteil-System): Liste (face, nz, z_mm, area_cm2).
    stats: dict für die Diagnose (geprüfte Flächen, Ebenen, Normalen der Ebenen)."""
    out = []
    for f in items(_safe(lambda: body.faces)):
        if stats is not None:
            stats['faces'] = stats.get('faces', 0) + 1
        try:
            n = _safe(lambda: f.geometry.normal)        # nur Ebenen haben eine Normale
            if n is None:
                continue
            ln = frame.ldir(n)
            ok_n = _safe(lambda: f.evaluator.getNormalAtPoint(f.pointOnFace))
            if ok_n and ok_n[0]:                        # Flächennormale nach außen (berücksichtigt Umkehrung)
                ln = frame.ldir(ok_n[1])
            elif _safe(lambda: f.isParamReversed, False):
                ln = tuple(-c for c in ln)
            if stats is not None:
                stats['planes'] = stats.get('planes', 0) + 1
                nl = stats.setdefault('normals', [])
                if len(nl) < 8:
                    nl.append([round(c, 3) for c in ln])
            if abs(abs(ln[2]) - 1.0) > 1e-3:
                continue
            z = frame.local(f.pointOnFace)[2]
            out.append((f, 1 if ln[2] > 0 else -1, z, float(_safe(lambda: f.area, 0.0))))
        except Exception as e:
            if stats is not None:
                stats.setdefault('errors', []).append(str(e)[:120])
            continue
    return out


def _face_loops(face, frame):
    outer, holes = None, []
    for loop in items(_safe(lambda: face.loops)):
        pts, edges, opp = loop_points(loop, frame)
        rec = {'pts': [(p[0], p[1]) for p in pts], 'edges': edges, 'first_opposed': opp}
        if _safe(lambda: loop.isOuter, False):
            outer = rec
        else:
            holes.append(rec)
    return outer, holes


def collect_bodies(occ, depth=0, why=None):
    """Volumenkörper eines Teils als PROXYS im Kontext der Occurrence (occ.bRepBodies), auch aus
    verschachtelten Unter-Occurrences (Baugruppen-Teile). Körper „Rohteil“ (Plattenkörper) ausgenommen."""
    out = []
    for b in items(_safe(lambda: occ.bRepBodies)):
        nm = _safe(lambda: b.name, '')
        if nm == 'Rohteil':
            if why is not None:
                why.append('Körper „Rohteil“ (Plattenkörper) ausgenommen')
            continue
        if _safe(lambda: b.isSolid, True) is False:
            continue
        if _safe(lambda: b.isVisible, True) is False and why is not None:
            why.append('Körper %s ist ausgeblendet (trotzdem verwendet)' % nm)
        out.append(b)
    if depth < 5:
        for c in items(_safe(lambda: occ.childOccurrences)):
            out += collect_bodies(c, depth + 1, why)
    return out


def curve_kind(edge):
    """'line' | 'arc' (Kreis/Bogen) | 'poly' (alles andere: Spline, Ellipse, unbekannt -> Strecken)."""
    t = _safe(lambda: edge.geometry.objectType, '') or ''
    if 'Line3D' in t:
        return 'line'
    if 'Arc3D' in t or 'Circle3D' in t:
        return 'arc'
    return 'poly'


def arc_info(edge, frame):
    """2.0.2: Mittelpunkt (x, y mm) und Radius (mm) einer Kreis-/Bogenkante, wenn ihre Achse parallel Z ist
    (dann ist die Draufsicht wieder ein Kreisbogen). Sonst None."""
    g = _safe(lambda: edge.geometry)
    c, r, n = _safe(lambda: g.center), _safe(lambda: g.radius), _safe(lambda: g.normal)
    if c is None or r is None or n is None:
        return None
    ln = frame.ldir(n)
    if abs(abs(ln[2]) - 1.0) > 1e-6:
        return None
    lc = frame.local(c)
    return {'c': (lc[0], lc[1]), 'r': float(r) / MM}


def _face_order_key(f, frame):
    """Priorität bei deckungsgleichen Kanten: ebene Unterseiten (tiefste zuerst), ebene Oberseiten, Rest."""
    n = _safe(lambda: f.geometry.normal)
    if n is not None:
        ln = frame.ldir(n)
        ok_n = _safe(lambda: f.evaluator.getNormalAtPoint(f.pointOnFace))
        if ok_n and ok_n[0]:
            ln = frame.ldir(ok_n[1])
        if abs(abs(ln[2]) - 1.0) <= 1e-3:
            z = _safe(lambda: frame.local(f.pointOnFace)[2], 0.0)
            return (0, z) if ln[2] < 0 else (1, -z)
    return (2, 0.0)


def _face_regions(bodies, frame, why):
    """Alle Flächen aller Körper: je Fläche die Schleifen (mm, Rohteil-System) mit Kanten-Tags."""
    faces = []
    for body in bodies:
        for f in items(_safe(lambda: body.faces)):
            faces.append(f)
    keyed = sorted(((_face_order_key(f, frame), i, f) for i, f in enumerate(faces)), key=lambda t: (t[0], t[1]))
    regs, recs, keys, bad = [], [], [], 0
    for key, _i, f in keyed:
        rings, rr = [], []
        for loop in items(_safe(lambda: f.loops)):
            tags, ei = [], []
            try:
                pts, edges, opp = loop_points(loop, frame, tags, ei)
            except Exception:
                bad += 1
                continue
            p2 = [(p[0], p[1]) for p in pts]
            rings.append((p2, tags))
            kinds = [curve_kind(e) for e in edges]
            rr.append({'pts': p2, 'edges': edges, 'first_opposed': opp, 'einfo': ei, 'kinds': kinds,
                       'arcs': [arc_info(e, frame) if kd == 'arc' else None for e, kd in zip(edges, kinds)],
                       'outer_flag': _safe(lambda: loop.isOuter)})
        if rings:
            regs.append(rings)
            recs.append(rr)
            keys.append(key)
    if bad:
        why.append('%d Schleife(n) nicht abtastbar (für die Silhouette ignoriert)' % bad)
    return regs, recs, keys


def _merge_straight(pts):
    """Kollineare Zwischenpunkte entfernen (nur für gerade Läufe/Strecken)."""
    out = []
    for p in pts:
        if len(out) >= 2:
            a, b = out[-2], out[-1]
            cr = (b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0])
            ln = math.hypot(p[0] - a[0], p[1] - a[1])
            dot = (b[0] - a[0]) * (p[0] - b[0]) + (b[1] - a[1]) * (p[1] - b[1])
            if ln > 0 and abs(cr) / ln < 1e-4 and dot >= 0:
                out[-1] = p
                continue
        out.append(p)
    return out


def _sil_loop(lp, recs):
    """Silhouetten-Schleife -> Kontur-Datensatz. Genau eine vorhandene B-Rep-Schleife: deren Kanten
    (method 'kante'); sonst zusammengesetzt: Läufe für die Silhouetten-Skizze (method 'skizze')."""
    if lp['src'] is not None:
        r, k = lp['src']
        rec = recs[r][k]
        return {'pts': rec['pts'], 'edges': rec['edges'], 'first_opposed': rec['first_opposed'], 'method': 'kante'}
    we = _whole_edges(lp, recs)
    if we is not None:
        return we
    rs = []
    for (r, k, ei), pts in SIL.runs(lp):
        kind = recs[r][k]['kinds'][ei] if ei is not None and ei < len(recs[r][k]['kinds']) else 'poly'
        if kind == 'arc' and len(pts) < 3:
            kind = 'line'
        arc = None
        if kind == 'arc':
            arc = (recs[r][k].get('arcs') or [None] * (ei + 1))[ei] if ei is not None else None
            if arc is None:
                kind = 'poly'                 # 2.0.2: kein echter Kreis in der Draufsicht -> Strecken
        if kind != 'arc':
            pts = _merge_straight(pts)
        if kind == 'line' and len(pts) > 2:
            kind = 'poly'                     # gerade Kante, aber durch Teilung geknickt? -> Strecken
        if rs and kind != 'arc' and rs[-1]['kind'] != 'arc':
            q = _merge_straight(rs[-1]['pts'] + pts[1:])
            rs[-1] = {'kind': 'poly' if len(q) > 2 else 'line', 'pts': q}
            continue
        rs.append({'kind': kind, 'pts': pts, 'arc': arc} if arc else {'kind': kind, 'pts': pts})
    pts = [q for run in rs for q in run['pts'][:-1]]
    return {'pts': pts, 'edges': [], 'first_opposed': False, 'method': 'skizze', 'runs': rs}


def _whole_edges(lp, recs, tol=0.02):
    """2.0.2: Zusammengesetzte Silhouetten-Schleife, die nur aus GANZEN B-Rep-Kanten (verschiedener Flächen)
    in EINER Höhe besteht -> diese Kanten als Kette (method 'kante', keine Skizze). Sonst None."""
    rl = SIL.runs(lp)
    if not rl or any(t[2] is None for t, _p in rl):
        return None
    seq, lens = [], {}
    for (r, k, ei), pts in rl:
        key = (r, k, ei)
        ln = sum(math.hypot(pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1]) for i in range(len(pts) - 1))
        if seq and seq[-1][0] == key:
            return None
        seq.append((key, pts))
        lens[key] = lens.get(key, 0.0) + ln
    if len(lens) != len(seq):
        return None                                   # Kante in mehreren Stücken -> nicht ganz
    edges, z = [], None
    first_opp = None
    for (r, k, ei), pts in seq:
        try:
            inf = recs[r][k]['einfo'][ei]
            e = recs[r][k]['edges'][ei]
        except (IndexError, KeyError, TypeError):
            return None
        if abs(lens[(r, k, ei)] - inf['len']) > max(tol, 1e-3 * inf['len']):
            return None
        if inf['z'][1] - inf['z'][0] > tol or (z is not None and abs(inf['z'][0] - z) > tol):
            return None
        z = inf['z'][0]
        if first_opp is None:
            d0 = math.dist(pts[0], inf['start'])
            d1 = math.dist(pts[0], inf['end'])
            if min(d0, d1) > tol:
                return None
            first_opp = d1 < d0
        edges.append(e)
    return {'pts': lp['pts'], 'edges': edges, 'first_opposed': bool(first_opp), 'method': 'kante',
            'mixed': len(set((t[0], t[1]) for t, _p in seq)) > 1}


def _from_rec(rec):
    return {'pts': rec['pts'], 'edges': rec['edges'], 'first_opposed': rec['first_opposed'], 'method': 'kante'}


def _project_loop(pts):
    """Kontur aus den LazyNest-Projekt-Daten als Skizzen-Schleife (Polylinie)."""
    P = list(pts)
    if len(P) >= 3 and P[0] == P[-1]:
        P = P[:-1]
    return {'pts': P, 'edges': [], 'first_opposed': False, 'method': 'skizze', 'source': 'projekt',
            'runs': [{'kind': 'poly', 'pts': P + [P[0]]}]}


def edge_extent(regs):
    """Hüllbox (mm) aller projizierten Kantenpunkte aller Flächen = Ausdehnung der Silhouette (2.0.2: ersetzt
    BRepBody.boundingBox, das bei gekrümmten Flächen zu groß sein kann)."""
    xs = [p[0] for r in regs for P, _T in r for p in P]
    ys = [p[1] for r in regs for P, _T in r for p in P]
    return (min(xs), min(ys), max(xs), max(ys)) if xs else None


def face_dump(regs, recs, keys, fp=None, info=None):
    """Diagnose-Silhouette (2.0.2): Flächendaten je Teil als JSON-fähiges dict."""
    out = {'faces': [], 'fast_path': fp, 'silhouette': info}
    for i, (rings, rr) in enumerate(zip(regs, recs)):
        out['faces'].append({'index': i, 'key': list(keys[i]) if keys else None, 'loops': [
            {'n_pts': len(P), 'area_mm2': round(SIL.signed_area(P), 3) if len(P) >= 3 else 0.0,
             'kinds': rec.get('kinds'), 'is_outer': rec.get('outer_flag'),
             'bbox': [round(v, 3) for v in G.bbox(P)] if P else None,
             'z': [list(map(lambda v: round(v, 3), e['z'])) for e in rec.get('einfo') or []][:50],
             'pts': [[round(p[0], 3), round(p[1], 3)] for p in P[:400]]}
            for (P, _T), rec in zip(rings, rr)]})
    return out


DIAG = {'on': False, 'parts': []}
FAST_TOL_LOOSE = 0.5   # mm (2.0.3): Schnellweg-Toleranz der letzten Stufe (nur wenn die Silhouette offen bleibt)
CACHE_SIG = None       # 2.0.2: Konstruktionsstand (fs_run.core_sig); None = kein Zwischenspeicher
GEO_CACHE = {}         # (Stand, Occurrence-Token, Rahmen, Körper-Tokens) -> (Ergebnis, Hinweise)
CACHE_STATS = {'hit': 0, 'miss': 0}


def clear_cache():
    GEO_CACHE.clear()


def _cache_key(occ, frame, bodies):
    if CACHE_SIG is None:
        return None
    t = _safe(lambda: occ.entityToken)
    bt = tuple(_safe(lambda b=b: b.entityToken) for b in bodies)
    if not t or not all(bt):
        return None
    return (CACHE_SIG, t, tuple(round(v, 6) for v in frame.o + frame.x + frame.y), bt)


def _fresh_copy(res):
    """Zwischengespeichertes Ergebnis als neue Struktur (Kurven/Fehlerflags früherer Läufe nie übernehmen)."""
    def lp(d):
        return {k: v for k, v in d.items() if k not in ('curves', 'sketch_failed', 'warn')}
    out = dict(res)
    out['outer'] = lp(res['outer'])
    out['holes'] = [lp(h) for h in res['holes']]
    out['pockets'] = [dict(q) for q in res['pockets']]
    return out      # 2.0.2 Diagnose-Silhouette: an -> part_geometry legt Flächendaten ab


def part_geometry(occ, frame, warn=None, expect=None, why=None, bodies=None, use_cache=True):
    why = why if why is not None else []
    bodies = bodies if bodies is not None else collect_bodies(occ, 0, why)
    key = _cache_key(occ, frame, bodies) if (use_cache and bodies and not DIAG['on']) else None
    if key is not None and key in GEO_CACHE:
        res, notes = GEO_CACHE[key]
        CACHE_STATS['hit'] += 1
        why.extend(notes)
        return _fresh_copy(res) if res is not None else None
    n0 = len(why)
    res = _part_geometry(occ, frame, warn, expect, why, bodies)
    if key is not None:
        CACHE_STATS['miss'] += 1
        GEO_CACHE[key] = (_fresh_copy(res) if res is not None else None, list(why[n0:]))
    return res


def _part_geometry(occ, frame, warn=None, expect=None, why=None, bodies=None):
    """2.0.1: Konturen eines Teils = SILHOUETTE (Draufsicht aller Flächen, fs_silhouette): Außenkontur =
    äußerster Umriss, Durchbrüche = nur durchgehende Öffnungen. Sacklöcher/Taschen/Nuten werden nie zu
    Durchbrüchen. Taschen (Option) = nach oben zeigende ebene Flächen zwischen Unter- und Oberseite.
    expect (Projekt-Kontur) wird nur noch zum Vergleich/zur Warnung benutzt. Rückgabe dict oder None."""
    why = why if why is not None else []
    bodies = bodies if bodies is not None else collect_bodies(occ, 0, why)
    if not bodies:
        why.append('keine Volumenkörper (auch nicht in Unter-Occurrences)')
        return None
    stats = {}
    faces_all = []
    for body in bodies:
        faces_all += _planar_z_faces(body, frame, stats)
    if not faces_all:
        why.append('keine ebene Fläche mit Normale ±Z (Flächen %s, Ebenen %s, Normalen %s%s)' % (
            stats.get('faces', 0), stats.get('planes', 0), stats.get('normals'),
            ', Fehler %s' % stats['errors'][:2] if stats.get('errors') else ''))
        return None
    zmin = min(e[2] for e in faces_all)
    zmax = max(e[2] for e in faces_all)
    regs, recs, keys = _face_regions(bodies, frame, why)
    exp = expect if isinstance(expect, dict) else ({'outer': expect, 'holes': None} if expect else None)
    # 2.0.2 Reihenfolge: Schnellweg (eine Fläche umschließt alles) -> volle Silhouette -> LazyNest-Kontur
    cand = [i for i, k in enumerate(keys) if k[0] in (0, 1)]
    fp = SIL.fast_path(regs, cand) if regs else {'region': None, 'why': ['keine Flächen']}
    info = {}
    shells = []
    path = 'schnell'
    if fp.get('region') is not None:
        r = fp['region']
        outer = _from_rec(recs[r][fp['outer']])
        holes = [_from_rec(recs[r][k]) for k in fp['holes']]
        n_shells = 1
    else:
        path = 'silhouette'
        shells = SIL.silhouette(regs, info) if regs else []
        if info.get('open'):
            why.append('Silhouette: %d offene Kette(n) (Enden %s) – Ergebnis prüfen' % (
                len(info['open']), '; '.join('%s→%s Lücke %.3f mm' % (o['start'], o['end'], o['gap_mm'])
                                             for o in info['open'][:4])))
        if info.get('closed_tol'):
            why.append('Silhouette: %d Schleife(n) tolerant geschlossen (≤ %.2f mm)' % (info['closed_tol'], SIL.CLOSE))
        if info.get('bridged'):
            why.append('Silhouette: %d Lücke(n) entlang der Flächenkanten geschlossen (%s)' % (
                info['bridged'], '; '.join(info.get('bridge_desc') or [])))
        fp2 = None
        if not shells or info.get('open'):
            # 2.0.3: letzte Stufe vor der LazyNest-Kontur – Schnellweg mit größerer Toleranz (Ober-/Unterseite
            # umschließt alle Projektionen bis FAST_TOL_LOOSE), Fläche geprüft gegen die LazyNest-Kontur
            fp2 = SIL.fast_path(regs, cand, tol=FAST_TOL_LOOSE) if regs else None
            if fp2 is not None and fp2.get('region') is not None:
                r2 = fp2['region']
                a_sil = abs(SIL.signed_area(recs[r2][fp2['outer']]['pts']))
                a_exp = abs(G.area(exp['outer'])) if exp and exp.get('outer') else None
                if a_exp is not None and abs(a_sil - a_exp) > 0.01 * a_exp:
                    why.append('Schnellweg (Toleranz %.2f mm) verworfen: Fläche %.0f statt %.0f mm² (LazyNest)'
                               % (FAST_TOL_LOOSE, a_sil, a_exp))
                    fp2 = None
            else:
                fp2 = None
        if fp2 is not None:
            path = 'schnell'
            why.append('Silhouette: Außenkontur der Ober-/Unterseite übernommen (Schnellweg, Toleranz %.2f mm)'
                       % FAST_TOL_LOOSE)
            fp = fp2
            r = fp2['region']
            outer = _from_rec(recs[r][fp2['outer']])
            holes = [_from_rec(recs[r][k]) for k in fp2['holes']]
            n_shells = 1
            info['open_resolved'] = info.get('open') or []
            info['open'] = []
        elif not shells:
            if exp and exp.get('outer'):
                path = 'projekt'
                why.append('Silhouette nicht bestimmbar – Kontur aus den LazyNest-Projekt-Daten (Skizze)')
                outer = _project_loop(exp['outer'])
                holes = [_project_loop(h) for h in exp.get('holes') or []]
                n_shells = 1
            else:
                why.append('Silhouette nicht bestimmbar (keine projizierbare Fläche, keine Projekt-Kontur)')
                if DIAG['on']:
                    DIAG['parts'].append({'occ': _safe(lambda: occ.name), 'why': list(why),
                                          'data': face_dump(regs, recs, keys, fp, info)})
                return None
        else:
            if len(shells) > 1:
                why.append('Silhouette mehrteilig (%d getrennte Umrisse) – nur der größte wird geschnitten' % len(shells))
            sh = shells[0]
            outer = _sil_loop(sh['outer'], recs)
            holes = [_sil_loop(h, recs) for h in sh['holes']]
            n_shells = len(shells)
    if DIAG['on']:
        DIAG['parts'].append({'occ': _safe(lambda: occ.name), 'path': path, 'why': list(why),
                              'data': face_dump(regs, recs, keys, fp, info)})
    meth = [outer['method']] + [h['method'] for h in holes]
    downs = [e for e in faces_all if e[1] < 0 and e[2] <= zmin + 0.01]
    face = max(downs, key=lambda e: e[3])[0] if downs else None
    how = 'Silhouette%s (Außen %s, Durchbrüche %d: %d Kanten / %d Skizze)' % (
        {'schnell': ' Schnellweg', 'silhouette': '', 'projekt': ' aus LazyNest-Projekt'}[path],
        'Kanten' if outer['method'] == 'kante' else 'Skizze', len(holes),
        sum(1 for m in meth[1:] if m == 'kante'), sum(1 for m in meth[1:] if m == 'skizze'))
    res = {'face': face, 'z_bottom': zmin, 'z_top': zmax, 'z_face': zmin, 'side': 'Silhouette',
           'how': how, 'outer': outer, 'holes': holes, 'pockets': [], 'bodies': len(bodies),
           'faces_pz': len(faces_all), 'sil_shells': n_shells, 'path': path,
           'sil_open': len(info.get('open') or []),
           'methods': {'kante': meth.count('kante'), 'skizze': meth.count('skizze')}}
    # 2.0.2 Hüllbox-Prüfung: gegen die Ausdehnung ALLER projizierten Kanten (statt BRepBody.boundingBox)
    sb = G.bbox(outer['pts'])
    gaps = []
    bb = edge_extent(regs)
    if bb is not None:
        gaps.append(('Kanten', max(sb[0] - bb[0], sb[1] - bb[1], bb[2] - sb[2], bb[3] - sb[3])))
    # (Vergleich mit der LazyNest-Kontur: compare_project in read_sheet – Fläche, Hüllbox, Durchbrüche)
    res['bbox_gap'] = max([g for _n, g in gaps] or [0.0])
    for nm_, d in gaps:
        if d > 0.3:
            why.append('Silhouette-Hüllbox weicht bis %.1f mm von der %s-Ausdehnung ab' % (d, nm_))
    for f, fnz, z, _a2 in faces_all:
        if fnz > 0 and zmin + 0.05 < z < zmax - 0.05:
            for loop in items(_safe(lambda: f.loops)):
                if _safe(lambda: loop.isOuter, False):
                    pts, edges, opp = loop_points(loop, frame)
                    res['pockets'].append({'pts': [(p[0], p[1]) for p in pts], 'edges': edges, 'face': f,
                                           'depth': zmax - z, 'first_opposed': opp})
    return res


def _body_bbox_local(bodies, frame):
    """Hüllbox (xmin, ymin, xmax, ymax, mm, Rohteil) aus body.boundingBox – nur bei achsparalleler Lage."""
    if any(abs(c) > 1e-6 and abs(abs(c) - 1.0) > 1e-6 for ax in (frame.x, frame.y) for c in ax):
        return None
    out = None
    for b in bodies:
        bx = _safe(lambda: b.boundingBox)
        if bx is None:
            return None
        ps = [frame.local(bx.minPoint), frame.local(bx.maxPoint)]
        q = (min(p[0] for p in ps), min(p[1] for p in ps), max(p[0] for p in ps), max(p[1] for p in ps))
        out = q if out is None else (min(out[0], q[0]), min(out[1], q[1]), max(out[2], q[2]), max(out[3], q[3]))
    return out


def _bbox_overlap(a, b):
    """Überdeckung zweier Hüllboxen, bezogen auf die kleinere (0…1)."""
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    if w <= 0 or h <= 0:
        return 0.0
    sm = min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1]))
    return w * h / max(sm, 1e-9)


def compare_project(g, q):
    """Silhouette gegen LazyNest-Projektkontur: (abweichend?, Text)."""
    a1, a2 = abs(G.area(g['outer']['pts'])), abs(G.area(q['outer']))
    dev = (a1 - a2) / max(a2, 1e-9)
    b1, b2 = G.bbox(g['outer']['pts']), G.bbox(q['outer'])
    dbb = max(abs(x - y) for x, y in zip(b1, b2))
    nh = None if q.get('holes') is None else len(q['holes'])
    bad = abs(dev) > 0.01 or dbb > 1.0 or (nh is not None and nh != len(g['holes']))
    txt = 'Fläche %+.1f %%, Hüllbox bis %.1f mm, Durchbrüche %d%s' % (
        dev * 100, dbb, len(g['holes']), '' if nh is None else ' (LazyNest %d)' % nh)
    return bad, txt


def chain_geom(lp):
    """Geometrie einer Kontur für die Kettenauswahl: Silhouetten-Skizzenkurven oder B-Rep-Kanten."""
    return lp.get('curves') or lp.get('edges') or []


def edges_valid(edges):
    """Alle Kanten-Objekte noch gültig? (Fusion: BRepEdge.isValid; unbekannt = gültig)"""
    for e in edges or []:
        if _safe(lambda: e.isValid, True) is False:
            return False
    return True


def _poly_key(pts):
    if not pts or len(pts) < 3:
        return None
    return G.centroid(G.orient(pts, True)), abs(G.area(pts))


def _match_loops(old, new, tol_mm=2.0):
    """Schleifen (dicts mit pts/edges) nach Lage zuordnen: Rückgabe Liste in der Reihenfolge von old
    (None = keine passende neue Schleife)."""
    keys = [_poly_key(n['pts']) for n in new]
    used, out = set(), []
    for o in old:
        ko = _poly_key(o['pts'])
        best = None
        if ko is not None:
            for j, kn in enumerate(keys):
                if j in used or kn is None:
                    continue
                d = math.dist(ko[0], kn[0])
                if d <= tol_mm and abs(ko[1] - kn[1]) <= max(1.0, 0.02 * ko[1]) and (best is None or d < best[0]):
                    best = (d, j)
        if best is None:
            out.append(None)
        else:
            used.add(best[1])
            out.append(new[best[1]])
    return out


def reread_geometry(sheet, part, why=None):
    """1.3.1: Kanten eines Teils FRISCH aus der B-Rep lesen (Occurrence im CAM-Kontext, sonst Design), gleiche
    Konturerkennung wie beim Einlesen, Zuordnung von Außenkontur/Durchbrüchen/Taschen über die Lage.
    Aktualisiert part['geo'] an Ort und Stelle (auch der Plan sieht es). Rückgabe True/False."""
    why = why if why is not None else []
    old = part.get('geo') or {}
    if old.get('no_edges'):
        return False
    frame = Frame(sheet.get('occ'))
    expect = (old.get('outer') or {}).get('pts')
    g = None
    for src in [s for s in (part.get('cam_occ'), part.get('occ')) if s is not None]:
        g = part_geometry(src, frame, None, expect, why, use_cache=False)
        if g is not None and _match_loops([old['outer']], [g['outer']])[0] is not None:
            break
        why.append('Außenkontur passt nicht zur geplanten Lage' if g is not None else 'keine Geometrie')
        g = None
    if g is None:
        return False
    holes = _match_loops(old.get('holes') or [], g['holes'])
    miss = sum(1 for o, n in zip(old.get('holes') or [], holes)
               if n is None and o.get('edges') and not o.get('curves'))
    pockets = _match_loops(old.get('pockets') or [], g['pockets'])

    def keep(o, n):
        # 2.0.1: Silhouetten-Schleifen aus der Skizze bleiben (Skizzenkurven, keine B-Rep-Kanten)
        if o.get('curves'):
            return o
        return n if n is not None else dict(o, edges=[])
    old['outer'] = keep(old['outer'], g['outer'])
    old['holes'] = [keep(o, n) for o, n in zip(old.get('holes') or [], holes)]
    old['pockets'] = [n if n is not None else dict(o, face=None) for o, n in zip(old.get('pockets') or [], pockets)]
    old['face'] = g['face']
    if miss:
        why.append('%d Durchbruch/Durchbrüche nicht wiedergefunden' % miss)
    return True


def map_occurrence(cam, occ):
    """Design-Occurrence -> gleichnamige Occurrence unter cam.designRootOccurrence (wie ContourNest)."""
    root = _safe(lambda: cam.designRootOccurrence) if cam is not None else None
    path = _safe(lambda: occ.fullPathName)
    if root is None or not isinstance(path, str):
        return occ, 'design'
    cur = root
    for nm in path.split('+'):
        nxt = next((c for c in items(_safe(lambda: cur.childOccurrences)) if _safe(lambda: c.name) == nm), None)
        if nxt is None:
            return occ, 'design'
        cur = nxt
    return cur, 'cam'


def _children(sheet_occ):
    return items(_safe(lambda: sheet_occ.childOccurrences))


# ---------------------------------------------------------------- Attribute (Proxy / nativ / Komponente)
KNOWN = ('part_id', 'part_name', 'copy', 'sheet', 'small_part', 'critical_vacuum', 'area_mm2', 'pos_x_mm',
         'pos_y_mm', 'rotation_deg', 'flipped', 'project_id')


def attrs_of(ent, group=CN):
    """Alle Attribute einer Gruppe als dict (über die Sammlung; Rückfall itemByName für bekannte Namen)."""
    out = {}
    coll = _safe(lambda: ent.attributes)
    if coll is None:
        return out
    for a in items(coll):
        if _safe(lambda: a.groupName) == group:
            out[_safe(lambda: a.name)] = _safe(lambda: a.value)
    if not out:
        for k in KNOWN:
            a = _safe(lambda: coll.itemByName(group, k))
            if a:
                out[k] = _safe(lambda: a.value)
    out.pop(None, None)
    return out


def part_attrs(occ, parent_comp=None):
    """ContourNest-Attribute eines Teils. ContourNest schreibt sie an die NATIVE Occurrence in der Rohteil-
    Komponente; über den Proxy (Kind der Rohteil-Occurrence) sind sie in Fusion nicht immer lesbar.
    Gelesen wird deshalb: Proxy, occ.nativeObject, gleichnamige Occurrence in rohteil.component.occurrences,
    Komponente. Rückgabe (zusammengeführt, {Quelle: [Schlüssel]})."""
    srcs = [('occurrence', occ), ('nativeObject', _safe(lambda: occ.nativeObject))]
    if parent_comp is not None:
        nm = _safe(lambda: occ.name)
        nat = next((o for o in items(_safe(lambda: parent_comp.occurrences)) if _safe(lambda: o.name) == nm), None)
        srcs.append(('rohteil.component.occurrences', nat))
    srcs.append(('component', _safe(lambda: occ.component)))
    merged, found = {}, {}
    seen = set()
    for tag, ent in srcs:
        if ent is None or id(ent) in seen:
            continue
        seen.add(id(ent))
        a = attrs_of(ent)
        if a:
            found[tag] = sorted(a)
            for k, v in a.items():
                merged.setdefault(k, v)
    return merged, found


def describe_tree(occ, depth=0, maxd=4, parent_comp=None, out=None):
    """Occurrence-Baum für das Protokoll."""
    out = out if out is not None else []
    _a, found = part_attrs(occ, parent_comp) if depth else ({}, {'occurrence': sorted(attrs_of(occ))})
    bodies = items(_safe(lambda: occ.bRepBodies))
    out.append('%s- %s | Pfad %s | Komponente %s | Körper %d %s | Attribute %s' % (
        '  ' * depth, _safe(lambda: occ.name), _safe(lambda: occ.fullPathName), _safe(lambda: occ.component.name),
        len(bodies), [_safe(lambda: b.name) for b in bodies][:6], found or '-'))
    if depth < maxd:
        comp = _safe(lambda: occ.component)
        for c in items(_safe(lambda: occ.childOccurrences)):
            describe_tree(c, depth + 1, maxd, comp, out)
    return out


# ---------------------------------------------------------------- Projekt-Daten (Design-Attribut)
def load_project(design, pid):
    if not pid or design is None:
        return None
    a = _safe(lambda: design.attributes.itemByName(CN, 'project_' + pid))
    v = _safe(lambda: a.value) if a else None
    return _safe(lambda: json.loads(v)) if v else None


def place_2d(pts, rot, flip, x, y):
    import math
    r = math.radians(rot)
    c, s = math.cos(r), math.sin(r)
    out = []
    for u, v in pts:
        if flip:
            v = -v
        out.append((c * u - s * v + x, s * u + c * v + y))
    return out


def project_parts(project, sheet_no, info=None):
    """Platzierte Teile eines Rohteils aus dem ContourNest-Projekt (Rohteil-mm, Materialsystem).
    ContourNest ≥ 1.10.0 speichert Maschinen-Lagen (coords = 'maschine'): quer liegende Rohteile werden ins
    Materialsystem der Rohteil-Komponente zurückgerechnet (info = fs_sheet.sheet_info)."""
    if not project:
        return []
    conv = info if (info and info.get('orient') == 'quer' and S.project_coords_machine(project)) else None
    jp = {p.get('id'): p for p in (project.get('job') or {}).get('parts', [])}
    out = []
    for pl in project.get('placements', []):
        if int(pl.get('sheet', 0)) != int(sheet_no):
            continue
        p = jp.get(pl.get('id'))
        if not p or not p.get('outer'):
            continue
        args = (float(pl.get('rot', 0)), bool(pl.get('flip')), float(pl['x']), float(pl['y']))
        mat = (lambda pts: [S.to_material(q, conv) for q in pts]) if conv else (lambda pts: pts)
        out.append({'id': pl.get('id'), 'copy': int(pl.get('copy', 0)), 'key': pl.get('key'),
                    'name': pl.get('name') or p.get('name', 'Teil'),
                    'outer': G.clean(mat(place_2d(p['outer'], *args))),
                    'holes': [G.clean(mat(place_2d(h, *args))) for h in p.get('holes') or [] if len(h) >= 3]})
    return out


def _match_placement(pp, used, attrs, outer):
    """Projekt-Platzierung zu einem Teil: über part_id + copy (Attribut copy = Projekt-copy + 1), sonst
    über die Geometrie (Schwerpunkt < 5 mm, Fläche ± 3 %)."""
    pid = attrs.get('part_id')
    if pid:
        try:
            cp = int(str(attrs.get('copy', '')).strip('"')) - 1
        except ValueError:
            cp = None
        for k, q in enumerate(pp):
            if k not in used and q['id'] == pid and (cp is None or q['copy'] == cp):
                return k, 'Attribut part_id/copy'
    if outer:
        a, c = G.area(outer), G.centroid(G.orient(outer))
        best = None
        for k, q in enumerate(pp):
            if k in used:
                continue
            qa, qc = G.area(q['outer']), G.centroid(G.orient(q['outer']))
            d = abs(qc[0] - c[0]) + abs(qc[1] - c[1])
            if abs(qa - a) / max(qa, 1e-9) < 0.03 and d < 5.0 and (best is None or d < best[1]):
                best = (k, d)
        if best:
            return best[0], 'Geometrie (Abstand %.2f mm)' % best[1]
    return None, ''


def _bbox_local(occ, frame):
    bb = _safe(lambda: occ.boundingBox)
    if bb is None:
        return None
    a, b = frame.local(bb.minPoint), frame.local(bb.maxPoint)
    return (min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]), max(a[1], b[1]))


def _is_stock_occ(occ):
    nm = (_safe(lambda: occ.component.name, '') or '') + ' ' + (_safe(lambda: occ.name, '') or '')
    bodies = items(_safe(lambda: occ.bRepBodies))
    names = [_safe(lambda: b.name, '') for b in bodies]
    if bodies and all(n == 'Rohteil' for n in names) and not items(_safe(lambda: occ.childOccurrences)):
        return 'nur Körper „Rohteil“'
    if nm.strip().lower().startswith('platte') and not attrs_of(occ):
        return 'Platten-Komponente älterer ContourNest-Versionen'
    return ''


def find_sheets(design):
    """Rohteile (Attribut ContourNest/sheet) als Liste (occ, attr-dict), sortiert."""
    out = []
    for occ in items(_safe(lambda: design.rootComponent.occurrences)):
        d = attr(occ, 'sheet', as_json=True)
        if not isinstance(d, dict):
            d = attr(_safe(lambda: occ.nativeObject), 'sheet', as_json=True) if _safe(lambda: occ.nativeObject) else None
        if isinstance(d, dict):
            out.append((occ, d))
    out.sort(key=lambda e: (str(e[1].get('project_id') or ''), int(e[1].get('project_sheet') or e[1].get('index') or 0),
                            _safe(lambda: e[0].name, '')))
    return out


def read_sheet(occ, d, cam=None, warn=None, design=None, log=None):
    """Ein Rohteil mit allen Teilkonturen (für fs_geom.plan_sheet) inkl. Fusion-Objekten.
    2D-Kontur: aus der B-Rep (Unter-/Oberseite), sonst aus den Projekt-Daten (Design-Attribut
    ContourNest/project_<id>). Kanten für die Kettenauswahl immer aus der B-Rep, bevorzugt im CAM-Kontext.
    log(text): Protokoll-Funktion (jede Zeile)."""
    warn = warn if warn is not None else []
    log = log or (lambda t: None)
    frame = Frame(occ)
    cam_sheet, how = map_occurrence(cam, occ)
    sheet = {'occ': occ, 'cam_occ': cam_sheet, 'context': how, 'attr': d, 'no': int(d.get('index') or 0),
             'project_id': d.get('project_id') or '', 'project_sheet': int(d.get('project_sheet') or d.get('index') or 0),
             'name': _safe(lambda: occ.name, 'Rohteil'), 'length': float(d.get('length_mm') or 0),
             'width': float(d.get('width_mm') or 0), 'thickness': float(d.get('thickness_mm') or 0), 'parts': [],
             'diag': {'tree': [], 'parts': [], 'source': ''}}
    dg = sheet['diag']
    log('Rohteil %s: %g × %g × %g mm, Projekt %s/%s, Ursprung (cm) %s, CAM-Kontext %s' % (
        sheet['name'], sheet['length'], sheet['width'], sheet['thickness'], sheet['project_id'] or '-',
        sheet['project_sheet'], [round(v, 3) for v in frame.o], how))
    if cam is not None and how != 'cam':
        log('  WARNUNG: Rohteil nicht unter cam.designRootOccurrence gefunden (Pfad %s) – Kanten aus dem '
            'Design-Kontext; Fusion meldet dann evtl. „entity could not be matched“' % _safe(lambda: occ.fullPathName))
    try:
        dg['tree'] = describe_tree(occ)
        for ln in dg['tree']:
            log('  Baum ' + ln)
    except Exception as e:
        log('  Baum nicht lesbar: %s' % e)
    project = load_project(design, sheet['project_id'])
    # 1.3.0: Ausrichtung/Nullpunkt/Maß je Rohteil (Projekt vor Attribut, ältere Daten: längs, unten links)
    info = S.sheet_info(d, S.project_sheet_rec(project, sheet['project_sheet']),
                        (project or {}).get('default_zero') or ((project or {}).get('opts') or {}).get('cam_origin'),
                        sheet['no'])
    sheet.update({k: info[k] for k in ('orient', 'kind', 'zero', 'box_point', 'W', 'H', 'grain_axis', 'label',
                                       'zero_x', 'zero_y', 'zero_z', 'zero_u', 'zero_v', 'zero_side', 'zero_text',
                                       'zero_explicit')})
    sheet['sheet_info'] = info
    log('  %s (Quelle %s, WCS %s)' % (info['label'], info['source'], info['box_point']))
    pp = project_parts(project, sheet['project_sheet'], info)
    log('  Projekt-Daten: %s' % ('%d Platzierungen' % len(pp) if project else 'nicht gefunden (Design-Attribut '
                                  'ContourNest/project_%s)' % (sheet['project_id'] or '?')))
    used = set()
    sheet_comp = _safe(lambda: occ.component)
    cam_children = {(_safe(lambda: c.name)): c for c in _children(cam_sheet)} if how == 'cam' else {}
    for k, po in enumerate(_children(occ)):
        why = []
        rec = {'occurrence': _safe(lambda: po.name), 'path': _safe(lambda: po.fullPathName)}
        dg['parts'].append(rec)
        stock = _is_stock_occ(po)
        if stock:
            rec['result'] = 'übersprungen: ' + stock
            log('  Teil %s: %s' % (rec['occurrence'], rec['result']))
            continue
        attrs, found = part_attrs(po, sheet_comp)
        rec['attributes'] = found
        nm = attrs.get('part_name') or _safe(lambda: po.component.name) or _safe(lambda: po.name, 'Teil')
        cam_po = cam_children.get(_safe(lambda: po.name))
        src = cam_po or po
        rec['edge_context'] = 'cam' if cam_po is not None else 'design'
        # erwartete Kontur aus dem Projekt (über Attribut, sonst über die Lage der Hüllbox)
        kpl, mhow = _match_placement(pp, used, attrs, None)
        if kpl is None and pp:
            bb = _bbox_local(po, frame)
            if bb:
                for kk, q in enumerate(pp):
                    qb = G.bbox(q['outer'])
                    if kk not in used and all(abs(a - b) < 2.0 for a, b in zip(bb, qb)):
                        kpl, mhow = kk, 'Hüllbox'
                        break
        expect = pp[kpl] if kpl is not None else None
        g = None
        try:
            g = part_geometry(src, frame, warn, expect, why)
            if g is None and cam_po is not None and cam_po is not po:
                why.append('CAM-Kontext ohne Ergebnis – Design-Kontext versucht')
                g = part_geometry(po, frame, warn, expect, why)
                rec['edge_context'] = 'design'
        except Exception as e:
            why.append('Ausnahme beim Lesen: %s' % e)
            g = None
        if kpl is None and g is not None and pp:
            kpl, mhow = _match_placement(pp, used, attrs, g['outer']['pts'])
        if kpl is not None:
            used.add(kpl)
            rec['project_match'] = mhow
        if g is None and kpl is None:
            rec['result'] = 'abgelehnt: ' + '; '.join(why or ['keine Geometrie'])
            log('  Teil %s: %s (Attribute %s)' % (rec['occurrence'], rec['result'], found or 'keine'))
            warn.append('%s / %s: %s' % (sheet['name'], rec['occurrence'], rec['result']))
            continue
        small = str(attrs.get('small_part', '')).lower() in ('true', '1') or \
            str(attrs.get('critical_vacuum', '')).lower() in ('true', '1')
        if g is not None:
            outer2d, holes2d = G.clean(g['outer']['pts']), [G.clean(h['pts']) for h in g['holes']]
            rec['geometry'] = '%s, z %.2f…%.2f mm, %d Körper' % (g['how'], g['z_bottom'], g['z_top'], g['bodies'])
            rec['silhouette'] = g.get('methods')
            if g.get('bbox_gap', 0.0) > 0.3 or g.get('sil_shells', 1) > 1 or g.get('sil_open') or \
                    g.get('path') == 'projekt':
                warn.append('%s / %s: Silhouette prüfen – %s' % (sheet['name'], nm, '; '.join(
                    w for w in why if w.startswith('Silhouette'))))
            if kpl is not None:
                bad, txt = compare_project(g, pp[kpl])
                ov = _bbox_overlap(G.bbox(g['outer']['pts']), G.bbox(pp[kpl]['outer']))
                if ov < 0.5:
                    # Hüllboxen überlappen kaum: anderer Koordinatenraum? 2D-Planung aus dem Projekt, Kanten B-Rep
                    outer2d, holes2d = pp[kpl]['outer'], pp[kpl]['holes']
                    rec['geometry'] += ' – 2D-Planung aus Projekt-Daten (Silhouette-Lage weicht ab, Überdeckung ' \
                        '%.0f %%)' % (ov * 100)
                    warn.append('%s / %s: Silhouette liegt nicht an der LazyNest-Position – Vorschau aus Projekt-Daten'
                                % (sheet['name'], nm))
                elif bad:
                    msg = '%s / %s: Silhouette weicht von der LazyNest-Kontur ab (%s) – geschnitten wird die ' \
                          'Silhouette' % (sheet['name'], nm, txt)
                    why.append('Silhouette ≠ LazyNest: ' + txt)
                    warn.append(msg)
        else:
            q = pp[kpl]
            outer2d, holes2d = q['outer'], q['holes']
            g = {'face': None, 'z_bottom': 0.0, 'outer': {'pts': outer2d, 'edges': [], 'first_opposed': False},
                 'holes': [{'pts': h, 'edges': [], 'first_opposed': False} for h in holes2d], 'pockets': [],
                 'side': '-', 'how': 'Projekt', 'no_edges': True}
            rec['geometry'] = 'Projekt-Daten (B-Rep: %s) – KEINE Kanten für CAM' % '; '.join(why)
        key_id = attrs.get('part_id') or (pp[kpl]['id'] if kpl is not None else nm)
        key_cp = attrs.get('copy') or (pp[kpl]['copy'] + 1 if kpl is not None else k)
        if kpl is not None and not attrs.get('part_name'):
            nm = pp[kpl]['name']
        sheet['parts'].append({
            'key': '%s#%s' % (key_id, key_cp), 'name': nm, 'occ': po, 'cam_occ': src,
            'outer': outer2d, 'holes': holes2d, 'pockets': [G.clean(q['pts']) for q in g['pockets']],
            'small': True if small else None, 'geo': g})
        rec['result'] = 'ok'
        rec['name'] = nm
        rec['notes'] = why
        log('  Teil %s: ok – %s, Kanten aus %s-Kontext, Projekt %s, Fläche %.0f cm², %d Durchbrüche%s' % (
            rec['occurrence'], rec['geometry'], rec['edge_context'], rec.get('project_match') or '-',
            G.area(outer2d) / 100, len(holes2d), (' | ' + '; '.join(why)) if why else ''))
    # Projekt-Platzierungen ohne passende Occurrence
    missing = [q for kk, q in enumerate(pp) if kk not in used]
    if missing:
        log('  %d Projekt-Platzierung(en) ohne Teil-Occurrence: %s' % (len(missing), [q['name'] for q in missing]))
        if not sheet['parts']:
            for q in missing:          # nur Planung/Vorschau – ohne Kanten keine CAM-Operation
                sheet['parts'].append({
                    'key': '%s#%s' % (q['id'], q['copy'] + 1), 'name': q['name'], 'occ': None, 'cam_occ': None,
                    'outer': q['outer'], 'holes': q['holes'], 'pockets': [], 'small': None,
                    'geo': {'face': None, 'z_bottom': 0.0, 'pockets': [], 'no_edges': True, 'side': '-', 'how': 'Projekt',
                            'outer': {'pts': q['outer'], 'edges': [], 'first_opposed': False},
                            'holes': [{'pts': h, 'edges': [], 'first_opposed': False} for h in q['holes']]}})
            warn.append('%s: keine Teil-Occurrence lesbar – Konturen aus den Projekt-Daten (nur Vorschau, '
                        'keine CAM-Operationen)' % sheet['name'])
    n_b = sum(1 for p in sheet['parts'] if not p['geo'].get('no_edges'))
    dg['source'] = 'B-Rep %d, Projekt %d' % (n_b, len(sheet['parts']) - n_b)
    log('  Ergebnis %s: %d Teil(e) (%s)' % (sheet['name'], len(sheet['parts']), dg['source']))
    return sheet


def chain_reverted(pts, first_opposed, want_cw):
    """isReverted für ChainSelection: Fusion legt die Werkzeugseite über die Richtung der ERSTEN Kante fest
    (API-Doku ChainSelection). Annahme: Werkzeug links der Kettenrichtung. Außenkontur -> Kette im
    Uhrzeigersinn (Werkzeug außen), Durchbruch -> gegen den Uhrzeigersinn (Werkzeug innen)."""
    ccw_loop = G.signed_area(pts) > 0                  # Coedge-Reihenfolge, von oben (+Z) gesehen
    ccw_edge = ccw_loop != bool(first_opposed)          # Richtung der ersten Kante
    return ccw_edge == bool(want_cw)                    # umdrehen, wenn Richtung nicht passt
