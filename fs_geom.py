# -*- coding: utf-8 -*-
"""Finalschnitt – reine 2D-Geometrie (ohne Fusion testbar). Alle Maße in mm, Koordinaten im Rohteil
(X = Plattenlänge, Y = Plattenbreite, Ursprung links vorne).

* Reihenfolge der Außenkonturen (ab 1.1.0): gierig – vor jedem Teil wird für jeden Kandidaten die größte
  zusammenhängende Restfläche nach seinem Schnitt berechnet (Raster, geschnittene Teile gelten als entfernt);
  gewählt wird der Kandidat mit der größten Restfläche (am wenigsten Zerstückelung, gut fürs Vakuum),
  bei Gleichstand (± Toleranz) der mit dem kürzesten Eilgang. Kleinteile optional zuerst (eigene Gruppe).
* Startpunkt je Außenkontur: zeigt zum Schwerpunkt der größten verbleibenden Restfläche (Startpunkt-Lage:
  Ecke / Kantenmitte / nächster Punkt).
* Haltestege: Anzahl nach Umfang (auch große Teile), Lage auf geraden Kanten mit Mindestabstand
  (nie zwei Stege nebeneinander), weg von Start, Ecken, engen Radien und Kanten ohne Restmaterial;
  Brückenstege nur bei ausreichender Überlappung, nicht an Ecken/T-Stößen, mehrere auf langen Kanten.
"""
import math

DEFAULTS = {
    'tool_d': 8.0,              # Werkzeug-Ø (aus der Werkzeugbibliothek)
    'durchstich': 0.3,          # unter Plattenunterseite (Opferplatte)
    'zustellung': 6.0,          # maximale Zustellung (maximumStepdown)
    'schlicht_zugabe': 0.0,     # radiale Aufmaßzugabe beim Schruppen
    'schlichtgang': False,      # zweiter Umlauf ohne Aufmaß
    'vorfraesen': False,        # Schrupp-Op vor Final (Resttiefe + seitl. Aufmaß)
    'vorfraes_rest_mm': 1.0,     # Bodentiefe / Rest zum Fertig
    'vorfraes_aufmass': 0.5,     # radiales Aufmaß der Vorfräs-Op
    'richtung': 'gleich',       # legacy; Migration → richtung_vor/final
    'richtung_vor': 'gleich',
    'richtung_final': 'gleich',
    'anfahr_art_vor': 'rampe',
    'rampenwinkel_vor': 3.0,
    'rampenlaenge_vor': 10.0,
    'bogenradius_vor': 5.0,
    'einfahrt_pct_vor': 50.0,
    'az_vor': 6.0,
    'vc_vor': 800.0,
    'fz_vor': 0.15,
    'spindle_vor': 12000.0,
    'vf_vor': 3600.0,
    'anfahr_art_final': 'bogen',
    'rampenwinkel_final': 2.0,
    'rampenlaenge_final': 8.0,
    'bogenradius_final': 4.0,
    'einfahrt_pct_final': 40.0,
    'az_final': 3.0,
    'vc_final': 1000.0,
    'fz_final': 0.08,
    'spindle_final': 15000.0,
    'vf_final': 2400.0,
    'innen_zuerst': True,
    'taschen': False,
    'gruppierung': 'je_teil',   # 'je_teil' / 'eine'
    'seite_umkehren': False,
    'w_flaeche': 60,            # 0..100: Gewicht Fläche (Rest = Randnähe) – nur Reihenfolge „gewichtung“
    'reihenfolge': 'rest',      # 'rest' (größte zusammenhängende Restfläche, ab 1.1.0) / 'gewichtung' (alt)
    'rest_raster': 10.0,        # Rastergröße für die Restflächen-Berechnung (mm)
    'rest_toleranz': 2.0,       # Gleichstand der Restfläche (%) -> kürzester Eilgang entscheidet
    'kleinteile_zuerst': True,
    'stege': True,              # Planung; Final-Op: stege_final (Vorfräs nie Tabs)
    'stege_vor': False,         # immer aus (2.0.9)
    'stege_final': True,
    'steg_breite': 8.0,
    'steg_hoehe': 3.0,
    'steg_form': 'rechteckig',  # 'rechteckig' / 'dreieckig' (Planung)
    'steg_breite_vor': 8.0,     # legacy keys kept for alte user_settings
    'steg_hoehe_vor': 3.0,
    'steg_form_vor': 'rechteckig',
    'steg_breite_final': 3.0,
    'steg_hoehe_final': 1.5,
    'steg_form_final': 'rechteckig',
    'vak_min_cm2': 100.0,       # Mindestfläche Vakuum (wie ContourNest)
    'steg_abstand_klein': 250.0,
    'steg_abstand_mittel': 500.0,
    'gross_ab_cm2': 2500.0,     # Grenze große Teile (cm²)
    'stege_gross_an': True,     # Einzelstege an großen Teilen (aus: nur Brücken zu kleinen/mittleren Teilen)
    'stege_gross': 4,           # Mindestzahl bei großen Teilen (ab 1.1.0 zusätzlich nach Umfang)
    'steg_abstand_min': 100.0,  # Min. Stegabstand entlang der Kontur (gleiche Kante: auch ≥ 25 % der Kante)
    'steg_min': 2,
    'steg_min_klein': 3,
    'steg_max': 12,
    'start_abstand_min': 60.0,  # Mindestabstand Steg <-> Startpunkt (entlang der Kontur)
    'radius_min_faktor': 1.5,   # keine Stege, wo der Konturradius < Faktor × Werkzeug-Ø
    'steg_rest_min': 3.0,       # verbleibender Materialsteg außen, damit ein Steg „hält“
    'bruecken': True,           # Planung
    'bruecken_vor': False,
    'bruecken_final': True,
    'bruecke_extra': 2.5,       # Brücke, wenn Abstand der Teile ≤ Werkzeug-Ø + extra
    'bruecke_je_mm': 300.0,     # Abstand mehrerer Brücken auf langen gemeinsamen Kanten (mm)
    'bruecke_min_mm': 70.0,     # Mindest-Überlappung zweier Kanten für eine Brücke (≈ 2 × Eckabstand + Steg)
    'vertex_suche': 25.0,       # Ecke als Startpunkt, wenn höchstens so weit (entlang der Kontur) entfernt
    'ecke_min_grad': 30.0,
    'start_modus': 'ecke',      # 'ecke' (Ecke nahe Plattenmitte) / 'kante' (Kantenmitte zur Plattenmitte) /
                                # 'naechster' (nächster Punkt zur Mitte, ohne Eckbevorzugung)
    'kleinteile_kante': False,  # Kleinteile immer „Kantenmitte“ (Drehmoment an der Ecke schiebt kleine Teile)
    'start_ecke_min': 15.0,     # „Kantenmitte“: Mindestabstand des Startpunkts zu jeder Ecke (mm)
    'steg_raster': 4.0,
    'skizze_start': False,      # Startpunkte aus Skizze „Finalschnitt Startpunkte“ übernehmen (statt berechnen)
    'skizze_stege': False,      # Stege aus Skizze „Finalschnitt Stege“ übernehmen (statt berechnen)
    'ersetzen': True,
    'berechnen': False,         # Werkzeugwege NUR auf ausdrücklichen Wunsch berechnen (ab 1.0.2)
    'neuberechnen': 'auto',     # 2.0.2: computeAll vor CAM nur, wenn die Zeitachse seit der letzten Neuberechnung
                                # (LazyNest/LazySetup) geändert wurde; 'immer' | 'nie'
}

EPS = 1e-9


# ---------------------------------------------------------------- Grundlagen
def signed_area(p):
    a = 0.0
    n = len(p)
    for i in range(n):
        x0, y0 = p[i]
        x1, y1 = p[(i + 1) % n]
        a += x0 * y1 - x1 * y0
    return a / 2.0


def area(p):
    return abs(signed_area(p))


def clean(p, eps=1e-6):
    out = []
    for q in p:
        q = (float(q[0]), float(q[1]))
        if not out or math.hypot(q[0] - out[-1][0], q[1] - out[-1][1]) > eps:
            out.append(q)
    if len(out) > 1 and math.hypot(out[0][0] - out[-1][0], out[0][1] - out[-1][1]) <= eps:
        out.pop()
    return out


def orient(p, ccw=True):
    p = clean(p)
    return p if (signed_area(p) > 0) == ccw else p[::-1]


def perimeter(p):
    return sum(math.hypot(p[(i + 1) % len(p)][0] - p[i][0], p[(i + 1) % len(p)][1] - p[i][1]) for i in range(len(p)))


def centroid(p):
    a = signed_area(p)
    if abs(a) < EPS:
        return (sum(q[0] for q in p) / len(p), sum(q[1] for q in p) / len(p))
    cx = cy = 0.0
    n = len(p)
    for i in range(n):
        x0, y0 = p[i]
        x1, y1 = p[(i + 1) % n]
        c = x0 * y1 - x1 * y0
        cx += (x0 + x1) * c
        cy += (y0 + y1) * c
    return (cx / (6 * a), cy / (6 * a))


def bbox(p):
    xs = [q[0] for q in p]
    ys = [q[1] for q in p]
    return (min(xs), min(ys), max(xs), max(ys))


def cum(p):
    """Bogenlänge an jedem Eckpunkt (s[0] = 0) und Gesamtlänge."""
    s = [0.0]
    for i in range(len(p)):
        a, b = p[i], p[(i + 1) % len(p)]
        s.append(s[-1] + math.hypot(b[0] - a[0], b[1] - a[1]))
    return s[:-1], s[-1]


def point_at(p, s, _c=None):
    """Punkt bei Bogenlänge s (zyklisch): (punkt, segment, tangente)."""
    c, tot = _c or cum(p)
    if tot <= 0:
        return p[0], 0, (1.0, 0.0)
    s %= tot
    lo, hi = 0, len(c) - 1
    while lo < hi:                         # letztes i mit c[i] <= s
        mid = (lo + hi + 1) // 2
        if c[mid] <= s:
            lo = mid
        else:
            hi = mid - 1
    i = lo
    a, b = p[i], p[(i + 1) % len(p)]
    L = math.hypot(b[0] - a[0], b[1] - a[1])
    t = 0.0 if L < EPS else (s - c[i]) / L
    tg = (1.0, 0.0) if L < EPS else ((b[0] - a[0]) / L, (b[1] - a[1]) / L)
    return (a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1])), i, tg


def closest_on_seg(q, a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    L2 = dx * dx + dy * dy
    t = 0.0 if L2 < EPS else max(0.0, min(1.0, ((q[0] - a[0]) * dx + (q[1] - a[1]) * dy) / L2))
    x, y = a[0] + t * dx, a[1] + t * dy
    return (x, y), t, math.hypot(q[0] - x, q[1] - y)


def closest_on_poly(p, q, _c=None):
    c, tot = _c or cum(p)
    best = None
    for i in range(len(p)):
        a, b = p[i], p[(i + 1) % len(p)]
        pt, t, d = closest_on_seg(q, a, b)
        if best is None or d < best['d'] - 1e-12:
            best = {'pt': pt, 'i': i, 'd': d, 's': c[i] + t * math.hypot(b[0] - a[0], b[1] - a[1])}
    best['s'] %= tot if tot > 0 else 1
    return best


def cyc_dist(s1, s2, tot):
    d = abs(s1 - s2) % tot
    return min(d, tot - d)


def turn_deg(p, i):
    """Richtungsänderung am Eckpunkt i (0 = gerade, 90 = rechter Winkel)."""
    a, b, c = p[i - 1], p[i], p[(i + 1) % len(p)]
    v1 = (b[0] - a[0], b[1] - a[1])
    v2 = (c[0] - b[0], c[1] - b[1])
    l1, l2 = math.hypot(*v1), math.hypot(*v2)
    if l1 < EPS or l2 < EPS:
        return 0.0
    cs = max(-1.0, min(1.0, (v1[0] * v2[0] + v1[1] * v2[1]) / (l1 * l2)))
    return math.degrees(math.acos(cs))


def corners(p, min_turn=30.0, _c=None, merge=6.0):
    """Ecken als (Eckpunkt-Index, Bogenlänge, Knickwinkel). Verrundete Ecken (Bogen aus vielen kurzen
    Segmenten, jedes nur wenige Grad) werden zusammengefasst und zählen als EINE Ecke in der Bogenmitte."""
    c, tot = _c or cum(p)
    n = len(p)
    turns = [turn_deg(p, i) for i in range(n)]
    runs, cur = [], []
    for i in range(n):
        if turns[i] < 1.0:
            if cur:
                runs.append(cur)
                cur = []
            continue
        if cur and c[i] - c[cur[-1]] > merge:
            runs.append(cur)
            cur = []
        cur.append(i)
    if cur:
        runs.append(cur)
    if len(runs) > 1 and runs[0][0] == 0 and runs[-1][-1] == n - 1 and tot - c[runs[-1][-1]] <= merge:
        runs[0] = runs.pop() + runs[0]
    out = []
    for r in runs:
        t = sum(turns[i] for i in r)
        if t >= min_turn:
            mid = r[len(r) // 2]
            out.append((mid, c[mid], t))
    return out


def local_radius(p, s, h, _c=None):
    """Krümmungsradius aus drei Punkten im Abstand h entlang der Kontur (gerade -> inf)."""
    a = point_at(p, s - h, _c)[0]
    b = point_at(p, s, _c)[0]
    c = point_at(p, s + h, _c)[0]
    ab, bc, ca = math.dist(a, b), math.dist(b, c), math.dist(c, a)
    cr = abs((b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]))
    if cr < 1e-9:
        return float('inf')
    return ab * bc * ca / (2.0 * cr)


def ray_seg(o, d, a, b):
    """Abstand t >= 0 vom Ursprung o in Richtung d bis Segment ab (None, wenn kein Schnitt)."""
    ex, ey = b[0] - a[0], b[1] - a[1]
    den = d[0] * ey - d[1] * ex
    if abs(den) < EPS:
        return None
    wx, wy = a[0] - o[0], a[1] - o[1]
    t = (wx * ey - wy * ex) / den
    u = (wx * d[1] - wy * d[0]) / den
    if t >= 0 and -1e-9 <= u <= 1 + 1e-9:
        return t
    return None


def ray_clearance(o, d, polys, rect, max_d=400.0):
    """Freier Weg von o in Richtung d: (abstand, 'teil'|'rand'|'frei', index des Teils)."""
    best, kind, idx = max_d, 'frei', -1
    for k, p in enumerate(polys):
        bx = bbox(p)
        if (o[0] < bx[0] - max_d or o[0] > bx[2] + max_d or o[1] < bx[1] - max_d or o[1] > bx[3] + max_d):
            continue
        for i in range(len(p)):
            t = ray_seg(o, d, p[i], p[(i + 1) % len(p)])
            if t is not None and t < best:
                best, kind, idx = t, 'teil', k
    x0, y0, x1, y1 = rect
    for a, b in (((x0, y0), (x1, y0)), ((x1, y0), (x1, y1)), ((x1, y1), (x0, y1)), ((x0, y1), (x0, y0))):
        t = ray_seg(o, d, a, b)
        if t is not None and t < best:
            best, kind, idx = t, 'rand', -1
    return best, kind, idx


def dist_point_poly(q, p):
    return min(closest_on_seg(q, p[i], p[(i + 1) % len(p)])[2] for i in range(len(p)))


def min_distance(pa, pb):
    """Kleinster Abstand zweier geschlossener Polygone (ohne Überschneidung)."""
    return min(min(dist_point_poly(q, pb) for q in pa), min(dist_point_poly(q, pa) for q in pb))


def resample(p, step, _c=None):
    c, tot = _c or cum(p)
    n = max(8, int(math.ceil(tot / step)))
    return [(k * tot / n,) + point_at(p, k * tot / n, (c, tot))[0] for k in range(n)]


# ---------------------------------------------------------------- Teile vorbereiten
def prepare(sheet, cfg):
    """Teile normieren: Außenkontur gegen den Uhrzeigersinn, Fläche, Umfang, Schwerpunkt, Kleinteil."""
    out = []
    vmin = float(cfg['vak_min_cm2']) * 100.0
    for k, pt in enumerate(sheet['parts']):
        outer = orient(pt['outer'], True)
        holes = [orient(h, False) for h in pt.get('holes') or [] if len(h) >= 3]
        a = area(outer) - sum(area(h) for h in holes)
        small = pt.get('small')
        if small is None:
            small = a < vmin
        c = cum(outer)
        out.append(dict(pt, idx=k, outer=outer, holes=holes, pockets=[orient(q, False) for q in pt.get('pockets') or []],
                        area=a, per=c[1], centroid=centroid(outer), small=bool(small) or a < vmin, _c=c))
    return out


# ---------------------------------------------------------------- 1) Reihenfolge
def order_parts(parts, sheet, cfg):
    """ALT („gewichtung“): Schlüssel = w·Fläche/Fläche_max + (1−w)·(1 − Abstand/Abstand_max)
    (klein + randnah -> zuerst). Kleinteile (unter Mindestfläche Vakuum) optional immer zuerst."""
    if not parts:
        return []
    cx, cy = sheet['length'] / 2.0, sheet['width'] / 2.0
    dmax = math.hypot(cx, cy) or 1.0
    amax = max(p['area'] for p in parts) or 1.0
    w = max(0.0, min(1.0, float(cfg['w_flaeche']) / 100.0))
    for p in parts:
        p['dist_center'] = math.hypot(p['centroid'][0] - cx, p['centroid'][1] - cy)
        p['sort_key'] = w * p['area'] / amax + (1 - w) * (1 - p['dist_center'] / dmax)
    first = (lambda p: 0 if p['small'] else 1) if cfg['kleinteile_zuerst'] else (lambda p: 0)
    return [p['idx'] for p in sorted(parts, key=lambda p: (first(p), p['sort_key'], p.get('name', ''), p['idx']))]


def _scan_x(poly, y):
    """x-Intervalle des Polygons auf der Höhe y (gerade/ungerade-Regel)."""
    xs = []
    n = len(poly)
    for i in range(n):
        (x0, y0), (x1, y1) = poly[i], poly[(i + 1) % n]
        if (y0 <= y < y1) or (y1 <= y < y0):
            xs.append(x0 + (y - y0) * (x1 - x0) / (y1 - y0))
    xs.sort()
    return [(xs[k], xs[k + 1]) for k in range(0, len(xs) - 1, 2)]


class Raster:
    """Platte als Raster; jede Zeile ist eine Bitmaske (Python-int) der noch vorhandenen Zellen.
    Zusammenhang (4-Nachbarschaft) über Zeilen-Läufe + Union-Find – schnell genug ohne numpy."""

    def __init__(self, length, width, cell):
        cell = max(float(cell), 1.0)
        while (length / cell) * (width / cell) > 80000:      # Obergrenze Zellen (Laufzeit)
            cell *= 1.25
        self.cell = cell
        self.nx = max(1, int(math.ceil(length / cell)))
        self.ny = max(1, int(math.ceil(width / cell)))
        self.full = (1 << self.nx) - 1

    def mask(self, poly, r):
        """Zeilenmasken (dict zeile -> bits) des Polygons, um r (Schnittbreite/2) vergrößert."""
        cell, out = self.cell, {}
        bx = bbox(poly)
        j0 = max(0, int((bx[1] - r) / cell))
        j1 = min(self.ny - 1, int((bx[3] + r) / cell) + 1)
        for j in range(j0, j1 + 1):
            yc = (j + 0.5) * cell
            m = 0
            for y in (yc - r, yc, yc + r):
                for x0, x1 in _scan_x(poly, y):
                    i0 = max(0, int(math.ceil((x0 - r) / cell - 0.5)))
                    i1 = min(self.nx - 1, int(math.floor((x1 + r) / cell - 0.5)))
                    if i1 >= i0:
                        m |= ((1 << (i1 - i0 + 1)) - 1) << i0
            if m:
                out[j] = m
        if not out:                                          # winziges Teil: Zelle des Schwerpunkts
            c = centroid(poly)
            j = min(self.ny - 1, max(0, int(c[1] / cell)))
            out[j] = 1 << min(self.nx - 1, max(0, int(c[0] / cell)))
        return out

    def components(self, rows, keep_runs=False):
        """[(fläche_mm2, (cx, cy))] aller zusammenhängenden Bereiche, größter zuerst
        (keep_runs: zusätzlich die Läufe (zeile, i0, i1) je Bereich als drittes Element)."""
        runs, prev, parent = [], [], []

        def find(a):
            while parent[a] != a:
                parent[a] = parent[parent[a]]
                a = parent[a]
            return a
        for j, m in enumerate(rows):
            cur = []
            i = 0
            while m:
                low = (m & -m).bit_length() - 1
                m >>= low
                i += low
                ln = (~m & (m + 1)).bit_length() - 1        # Länge des Laufs aus Einsen
                k = len(runs)
                runs.append((j, i, i + ln - 1))
                parent.append(k)
                cur.append(k)
                m >>= ln
                i += ln
            a = b = 0
            while a < len(prev) and b < len(cur):            # überlappende Läufe der Nachbarzeile verbinden
                ra, rb = runs[prev[a]], runs[cur[b]]
                if ra[2] >= rb[1] and rb[2] >= ra[1]:
                    x, y = find(prev[a]), find(cur[b])
                    if x != y:
                        parent[y] = x
                if ra[2] < rb[2]:
                    a += 1
                else:
                    b += 1
            prev = cur
        acc = {}
        c = self.cell
        for k, (j, i0, i1) in enumerate(runs):
            r = find(k)
            n = i1 - i0 + 1
            e = acc.setdefault(r, [0, 0.0, 0.0, []])
            e[0] += n
            e[1] += n * (i0 + i1 + 1) / 2.0 * c
            e[2] += n * (j + 0.5) * c
            if keep_runs:
                e[3].append((j, i0, i1))
        out = [(e[0] * c * c, (e[1] / e[0], e[2] / e[0])) + ((e[3],) if keep_runs else ()) for e in acc.values()]
        out.sort(key=lambda t: -t[0])
        return out

    def nearest_cell(self, runs, q):
        """Zellmitte der Läufe, die q am nächsten liegt."""
        c, best = self.cell, None
        for j, i0, i1 in runs:
            y = (j + 0.5) * c
            x = min(max(q[0], (i0 + 0.5) * c), (i1 + 0.5) * c)
            d = (x - q[0]) ** 2 + (y - q[1]) ** 2
            if best is None or d < best[0]:
                best = (d, (x, y))
        return best[1] if best else q


def _inside(q, poly):
    return any(x0 <= q[0] <= x1 for x0, x1 in _scan_x(poly, q[1]))


def _target(ras, rows, part, centroid_, r):
    """Zielpunkt für die Startrichtung: Schwerpunkt der größten Restfläche – liegt er im Teil selbst
    (Restfläche umschließt das Teil) oder nicht in der Restfläche, die nächste Zelle dieser Restfläche."""
    comps = ras.components(rows, keep_runs=True)
    if not comps:
        return centroid_
    q = comps[0][1]
    j = int(q[1] / ras.cell)
    i = int(q[0] / ras.cell)
    in_rest = 0 <= j < ras.ny and 0 <= i < ras.nx and any(j == jj and i0 <= i <= i1 for jj, i0, i1 in comps[0][2])
    if in_rest and not _inside(q, part['outer']):
        return q
    return ras.nearest_cell(comps[0][2], q)


def order_by_remainder(parts, sheet, cfg, start_fn=None):
    """Reihenfolge nach größter zusammenhängender Restfläche (Vakuum).
    Rückgabe (order, info, targets): info je Schritt {idx, rest_mm2, rest_pct, bereiche, eilgang_mm,
    kandidaten}; targets[idx] = Schwerpunkt der größten Restfläche NACH dem Schnitt des Teils (Richtung für
    den Startpunkt)."""
    import time
    t0 = time.time()
    L, W = float(sheet['length']), float(sheet['width'])
    ras = Raster(L, W, float(cfg.get('rest_raster', 10.0)))
    r = float(cfg['tool_d']) / 2.0
    masks = {p['idx']: ras.mask(p['outer'], r) for p in parts}
    rows = [ras.full] * ras.ny
    total = L * W
    tol = float(cfg.get('rest_toleranz', 2.0)) / 100.0
    start_fn = start_fn or start_point
    centre = (L / 2.0, W / 2.0)
    if cfg.get('kleinteile_zuerst'):
        groups = [[p for p in parts if p['small']], [p for p in parts if not p['small']]]
    else:
        groups = [list(parts)]
    order, info, targets = [], [], {}
    prev = (0.0, 0.0)                                         # Maschinennullpunkt
    evals = 0
    for grp in groups:
        left = list(grp)
        while left:
            res = []
            for p in left:
                m = masks[p['idx']]
                new = [rows[j] & ~m[j] if j in m else rows[j] for j in range(ras.ny)]
                comps = ras.components(new)
                evals += 1
                big = comps[0] if comps else (0.0, centre)
                res.append((big[0], p, new, big[1], len(comps)))
            best = max(e[0] for e in res)
            tied = [e for e in res if e[0] >= best * (1.0 - tol) - 1e-6]
            pick = None
            for e in tied:
                if e[0] > 0:
                    e = e[:3] + (_target(ras, e[2], e[1], e[3], r),) + e[4:]
                st = start_fn(e[1], e[3], cfg)
                d = math.dist(prev, st['entry'] if st.get('entry') else st['pt'])
                if pick is None or d < pick[0] - 1e-6 or (abs(d - pick[0]) <= 1e-6 and e[0] > pick[1][0]):
                    pick = (d, e, st)
            d, e, st = pick
            p = e[1]
            rows = e[2]
            order.append(p['idx'])
            targets[p['idx']] = e[3] if e[0] > 0 else centre
            info.append({'idx': p['idx'], 'rest_mm2': e[0], 'rest_pct': 100.0 * e[0] / total if total else 0.0,
                         'bereiche': e[4], 'eilgang_mm': d, 'kandidaten': len(left), 'gleichstand': len(tied)})
            prev = st['pt']
            left.remove(p)
    for p in parts:
        p['dist_center'] = math.hypot(p['centroid'][0] - centre[0], p['centroid'][1] - centre[1])
    return order, info, targets, {'sekunden': time.time() - t0, 'raster_mm': ras.cell, 'auswertungen': evals,
                                  'zellen': ras.nx * ras.ny}


def nn_order(points, start=(0.0, 0.0)):
    """Indizes der Punkte als Kette „nächster Nachbar“ ab start."""
    left = list(range(len(points)))
    out, cur = [], start
    while left:
        k = min(left, key=lambda i: (math.dist(cur, points[i]), i))
        out.append(k)
        cur = points[k]
        left.remove(k)
    return out


# ---------------------------------------------------------------- 2) Startpunkt
START_MODES = ('ecke', 'kante', 'naechster')


def straight_runs(p, _c=None, tol=2.0):
    """Gerade Abschnitte der Kontur (aufeinanderfolgende Segmente mit Knick < tol°) als
    [(s_anfang, länge, normale_außen)] – Kontur gegen den Uhrzeigersinn."""
    c, tot = _c or cum(p)
    n = len(p)
    brk = [i for i in range(n) if turn_deg(p, i) >= tol]
    if not brk:
        return []
    runs = []
    for k, i0 in enumerate(brk):
        i1 = brk[(k + 1) % len(brk)]
        ln = (c[i1] - c[i0]) % tot if tot > 0 else 0.0
        if len(brk) == 1:
            ln = tot
        a, b = p[i0], p[(i0 + 1) % n]
        L = math.hypot(b[0] - a[0], b[1] - a[1]) or 1.0
        runs.append((c[i0], ln, ((b[1] - a[1]) / L, -(b[0] - a[0]) / L)))
    return runs


def _edge_mid_start(part, centre, cfg):
    """Längster gerader Abschnitt, dessen Außennormale zur Plattenmitte zeigt (Wertung Länge × Ausrichtung);
    Start in seiner Mitte, mindestens start_ecke_min von jeder Ecke entfernt. None, wenn keiner passt."""
    outer, c = part['outer'], part['_c']
    cmin = max(float(cfg['start_ecke_min']), float(cfg['tool_d']))
    cs = [e[1] for e in corners(outer, cfg['ecke_min_grad'], c)]
    best = None
    for s0, ln, nrm in straight_runs(outer, c):
        if ln < 2 * cmin:
            continue
        sm = (s0 + ln / 2.0) % c[1]
        pt, i, _t = point_at(outer, sm, c)
        vx, vy = centre[0] - pt[0], centre[1] - pt[1]
        d = math.hypot(vx, vy) or 1.0
        facing = (nrm[0] * vx + nrm[1] * vy) / d
        if facing <= 0.05 or any(cyc_dist(sm, q, c[1]) < cmin for q in cs):
            continue
        score = ln * facing
        if best is None or score > best[0] + 1e-9:
            best = (score, pt, sm, i)
    if best is None:
        return None
    return {'pt': best[1], 's': best[2], 'vertex': False, 'i': best[3]}


def start_point(part, centre, cfg):
    """Startpunkt je nach „Startpunkt-Lage“: Ecke nahe Plattenmitte (Vorgabe), Kantenmitte zur Plattenmitte
    (Rückfall: nächster Punkt) oder nächster Punkt zur Mitte ohne Eckbevorzugung."""
    outer, c = part['outer'], part['_c']
    mode = cfg.get('start_modus', 'ecke')
    if part.get('small') and cfg.get('kleinteile_kante'):
        mode = 'kante'
    near = closest_on_poly(outer, centre, c)
    best = {'pt': near['pt'], 's': near['s'], 'vertex': False, 'i': near['i']}
    used = 'naechster'
    if mode == 'kante':
        e = _edge_mid_start(part, centre, cfg)
        if e is not None:
            best, used = e, 'kante'
    elif mode == 'ecke':
        cands = [(i, s, t) for i, s, t in corners(outer, cfg['ecke_min_grad'], c)
                 if cyc_dist(s, near['s'], c[1]) <= cfg['vertex_suche']]
        if cands:
            i, s, _t = min(cands, key=lambda e: (math.dist(outer[e[0]], centre), e[0]))
            best, used = {'pt': outer[i], 's': s, 'vertex': True, 'i': i}, 'ecke'
    best['mode'] = used
    best['to_centre'] = (centre[0] - best['pt'][0], centre[1] - best['pt'][1])
    nx, ny = outward_normal(outer, best['s'], c, best['i'] if best['vertex'] else None)
    off = float(cfg['tool_d']) / 2.0 + 2.0              # Einstichpunkt im Abfall, Werkzeug berührt das Teil nicht
    best['entry'] = (best['pt'][0] + nx * off, best['pt'][1] + ny * off)
    return best


def hole_start(hole, cfg, manual=False, s=None):
    """Startpunkt einer Innenkante (Durchbruch): Einstich im Ausschnitt, Richtung zur Lochmitte."""
    poly = hole.get('poly') if isinstance(hole, dict) else hole
    c = cum(poly)
    tot = c[1] or 1.0
    cen = centroid(poly)
    if s is not None:
        ss = float(s) % tot
        pt, _tg, i = point_at(poly, ss, c)
        hit = {'pt': pt, 's': ss, 'i': i}
    else:
        near = closest_on_poly(poly, cen, c)
        hit = {'pt': near['pt'], 's': near['s'], 'i': near['i']}
        runs = straight_runs(poly, c)
        if runs:
            best = max(runs, key=lambda r: r[1])
            if best[1] >= max(float(cfg.get('tool_d', 8)) * 2, 20.0):
                sm = (best[0] + best[1] / 2.0) % tot
                pt, _tg, i = point_at(poly, sm, c)
                hit = {'pt': pt, 's': sm, 'i': i}
    dx, dy = cen[0] - hit['pt'][0], cen[1] - hit['pt'][1]
    L = math.hypot(dx, dy) or 1.0
    off = float(cfg['tool_d']) / 2.0 + 2.0
    return {'pt': hit['pt'], 's': hit['s'], 'i': hit.get('i'), 'vertex': False, 'mode': 'loch',
            'manual': bool(manual), 'to_centre': (dx, dy),
            'entry': (hit['pt'][0] + dx / L * off, hit['pt'][1] + dy / L * off)}


def hole_start_at(hole, s, cfg, manual=True):
    return hole_start(hole, cfg, manual=manual, s=s)


def outward_normal(p, s, _c=None, vertex=None):
    """Normale nach außen (Kontur gegen den Uhrzeigersinn); an einer Ecke die Winkelhalbierende."""
    if vertex is not None:
        a, b, c = p[vertex - 1], p[vertex], p[(vertex + 1) % len(p)]
        ns = []
        for u, v in ((a, b), (b, c)):
            L = math.hypot(v[0] - u[0], v[1] - u[1]) or 1.0
            ns.append(((v[1] - u[1]) / L, -(v[0] - u[0]) / L))
        nx, ny = ns[0][0] + ns[1][0], ns[0][1] + ns[1][1]
        L = math.hypot(nx, ny)
        if L > 1e-6:
            return nx / L, ny / L
    tg = point_at(p, s, _c)[2]
    return tg[1], -tg[0]


# ---------------------------------------------------------------- 3) Haltestege
def tab_count(part, cfg):
    """(Anzahl, Begründung). Ab 1.1.0 auch große Teile nach Umfang (mindestens „stege_gross“)."""
    per = part['per']
    if part['small']:
        n, why = max(int(cfg['steg_min_klein']), int(math.ceil(per / float(cfg['steg_abstand_klein'])))), 'Kleinteil'
    elif not cfg['stege']:
        return 0, 'Stege aus'
    elif is_large(part, cfg):
        if not cfg.get('stege_gross_an', True):
            return 0, 'großes Teil – Stege aus'
        n, why = max(int(cfg['stege_gross']), int(math.ceil(per / float(cfg['steg_abstand_mittel'])))), 'großes Teil'
    else:
        n, why = max(int(cfg['steg_min']), int(math.ceil(per / float(cfg['steg_abstand_mittel'])))), 'mittleres Teil'
    return max(0, min(n, int(cfg['steg_max']))), why


def is_large(part, cfg):
    return (not part['small']) and part['area'] >= float(cfg['gross_ab_cm2']) * 100.0


def tab_spacing(part, n, cfg):
    """Mindestabstand zweier Stege entlang der Kontur: „Min. Stegabstand“, mindestens 3 × Stegbreite bzw.
    2 × Werkzeug-Ø; bei sehr kleinen Teilen (Umfang/Anzahl zu klein) auf Umfang/(1,5·Anzahl) reduziert."""
    tw, td = float(cfg['steg_breite']), float(cfg['tool_d'])
    floor_ = max(3 * tw, 2 * td)
    want = float(cfg.get('steg_abstand_min', 100.0))
    return max(floor_, min(want, part['per'] / (1.5 * max(1, n))))


def corner_gap(cfg):
    return max(25.0, 2 * float(cfg['tool_d']) + float(cfg['steg_breite']))


def _run_index(runs, s, tot):
    """Index des geraden Abschnitts, der die Bogenlänge s enthält (oder None)."""
    for k, (s0, ln, _n) in enumerate(runs):
        if (s - s0) % tot <= ln:
            return k
    return None


def _prep_edges(part, cfg):
    if '_runs' not in part:
        c = part['_c']
        part['_runs'] = straight_runs(part['outer'], c)
        part['_sharp'] = [s for _i, s, _t in corners(part['outer'], 45.0, c)]
    return part['_runs'], part['_sharp']


def _tab_candidates(part, others, rect, start_s, cfg):
    """Mögliche Steg-Positionen (Raster entlang der Kontur) mit Filtern: Abstand zum Start, zu scharfen Ecken,
    Mindestradius, Restmaterial außen (Kanten, die einem Nachbarteil näher als 2·Ø + Restmaterial gegenüber
    liegen, halten keinen Einzelsteg). Bevorzugt gerade Kanten (Kandidaten auf Bögen nur, wenn das Teil keine
    geraden Kanten hat)."""
    outer, c = part['outer'], part['_c']
    tot = c[1]
    td, tw = float(cfg['tool_d']), float(cfg['steg_breite'])
    min_start = max(float(cfg['start_abstand_min']), 3 * td) + tw / 2
    runs, sharp = _prep_edges(part, cfg)
    cg = corner_gap(cfg)
    min_run = 2 * tw
    cands = []
    for s, x, y in resample(outer, float(cfg['steg_raster']), c):
        if start_s is not None and cyc_dist(s, start_s, tot) < min_start:
            continue
        if any(cyc_dist(s, sc, tot) < cg for sc in sharp):
            continue
        if local_radius(outer, s, max(tw, td), c) < float(cfg['radius_min_faktor']) * td:
            continue
        tg = point_at(outer, s, c)[2]
        nrm = (tg[1], -tg[0])                       # außen (Kontur gegen den Uhrzeigersinn)
        o = (x + nrm[0] * 0.01, y + nrm[1] * 0.01)
        clr, kind, idx = ray_clearance(o, nrm, others, rect)
        web = clr - td - (td if kind == 'teil' else 0.0)
        if web < float(cfg['steg_rest_min']):
            continue                                 # dort bleibt nach den Schnitten kein Material
        ri = _run_index(runs, s, tot)
        dc = min([cyc_dist(s, sc, tot) for sc in sharp] or [100.0])
        cands.append({'s': s, 'pt': (x, y), 'score': 1.0 + min(web, 100.0) / 100.0 + 0.4 * min(dc, 100.0) / 100.0,
                      'web': web, 'kind': kind, 'facing': idx, 'run': ri,
                      'straight': ri is not None and runs[ri][1] >= min_run})
    if any(cd['straight'] for cd in cands):
        cands = [cd for cd in cands if cd['straight']]
    return cands


def _spacing_ok(part, s, run, tabs, D):
    tot = part['per']
    runs = part.get('_runs') or []
    for t in tabs:
        d = cyc_dist(s, t['s'], tot)
        if d < D - 1e-6:
            return False
        if run is not None and t.get('run') == run and d < max(D, 0.25 * runs[run][1]) - 1e-6:
            return False
    return True


def place_tabs(part, n, forced, others, rect, start_s, cfg):
    """n Stege inkl. Brücken ('forced'). 2.0.5: zuerst gleichmäßig am Umfang (Soll = Umfang/n ab Start),
    je Slot den nächsten gültigen Kandidaten; Rest mit max-min-Abstand auffüllen. Nie dichter als D."""
    runs, _sharp = _prep_edges(part, cfg)
    tot = part['per']
    tabs = []
    for t in forced:
        tt = dict(t)
        tt.setdefault('run', _run_index(runs, tt['s'], tot))
        tabs.append(tt)
    need = n - len(tabs)
    part['tabs_dropped'] = 0
    part['tab_spacing'] = D = tab_spacing(part, n, cfg)
    if need <= 0:
        return tabs
    cands = _tab_candidates(part, others, rect, start_s, cfg)
    if not cands:
        part['tabs_dropped'] = need
        return tabs
    # Soll-Positionen gleichmäßig ab Start (bzw. 0)
    base = float(start_s) if start_s is not None else 0.0
    step = tot / float(n) if n > 0 else tot
    targets = [((base + (k + 0.5) * step) % tot) for k in range(n)]
    # bereits belegte Slots (forced) nahe an targets markieren
    used_tgt = set()
    for t in tabs:
        if not targets:
            break
        k = min(range(len(targets)), key=lambda i: cyc_dist(t['s'], targets[i], tot) if i not in used_tgt else 1e18)
        if k not in used_tgt and cyc_dist(t['s'], targets[k], tot) < step * 0.45:
            used_tgt.add(k)
    placed = 0
    for k, tgt in enumerate(targets):
        if k in used_tgt or placed >= need:
            continue
        best = None
        for cd in cands:
            if not _spacing_ok(part, cd['s'], cd['run'], tabs, D):
                continue
            d = cyc_dist(cd['s'], tgt, tot)
            # Fenster: lieber nah am Soll, dann web/Ecke
            if d > step * 0.55:
                continue
            val = -d + 8.0 * min(cd['web'], 100.0) / 100.0 + 0.1 * min(
                min([cyc_dist(cd['s'], sc, tot) for sc in part['_sharp']] or [150.0]), 150.0)
            if best is None or val > best[0] + 1e-9:
                best = (val, cd)
        if best is None:
            continue
        tabs.append(dict(best[1], bridge=False))
        placed += 1
        used_tgt.add(k)
    # Rest: klassisch max-min, falls Slots leer blieben
    while placed < need:
        best = None
        for cd in cands:
            if not _spacing_ok(part, cd['s'], cd['run'], tabs, D):
                continue
            ref = [t['s'] for t in tabs] + ([start_s] if start_s is not None else [])
            md = min([cyc_dist(cd['s'], q, tot) for q in ref] or [tot])
            dc = min([cyc_dist(cd['s'], sc, tot) for sc in part['_sharp']] or [150.0])
            val = md + 40.0 * min(cd['web'], 100.0) / 100.0 + 0.5 * min(dc, 150.0)
            if best is None or val > best[0] + 1e-9:
                best = (val, cd)
        if best is None:
            part['tabs_dropped'] = need - placed
            break
        tabs.append(dict(best[1], bridge=False))
        placed += 1
    return tabs


def detect_bridges(parts, cfg):
    """Brücken zwischen eng benachbarten Teilen (Abstand ≤ Werkzeug-Ø + Zugabe). Nur wo sich die Kanten
    mindestens „bruecke_min_mm“ überlappen; auf langen Überlappungen mehrere (Abstand „bruecke_je_mm“).
    Jeder Brückenpunkt muss dieselben Filter bestehen wie ein Einzelsteg (Eckabstand, Mindestradius) an
    BEIDEN Teilen, direkt gegenüber liegen (Strahl senkrecht zur Kante trifft das Nachbarteil) und darf
    keinem dritten Teil nahe sein (T-Stoß / Ecke, an der 3–4 Teile zusammenkommen)."""
    td = float(cfg['tool_d'])
    thr = td + float(cfg['bruecke_extra']) + 0.05
    tw = float(cfg['steg_breite'])
    cg = corner_gap(cfg)
    rmin = float(cfg['radius_min_faktor']) * td
    min_len = max(float(cfg.get('bruecke_min_mm', 70.0)), 3 * tw)
    spacing = max(float(cfg['bruecke_je_mm']), 2 * tw)
    out, rejected = [], []
    for p in parts:
        _prep_edges(p, cfg)
    for ia in range(len(parts)):
        for ib in range(ia + 1, len(parts)):
            A, B = parts[ia], parts[ib]
            ba, bb = bbox(A['outer']), bbox(B['outer'])
            if ba[0] > bb[2] + thr or bb[0] > ba[2] + thr or ba[1] > bb[3] + thr or bb[1] > ba[3] + thr:
                continue
            samples = resample(A['outer'], 2.0, A['_c'])
            close = [(s, (x, y)) for s, x, y in samples if dist_point_poly((x, y), B['outer']) <= thr]
            if not close:
                continue
            runs, cur = [], [close[0]]
            step = A['per'] / len(samples)
            for e in close[1:]:
                if e[0] - cur[-1][0] <= step * 1.5:
                    cur.append(e)
                else:
                    runs.append(cur)
                    cur = [e]
            runs.append(cur)
            if len(runs) > 1 and runs[0][0][0] <= step and A['per'] - runs[-1][-1][0] <= step * 1.5:
                runs[0] = runs.pop() + runs[0]           # über den Konturanfang hinweg
            for r in runs:
                length = len(r) * step
                if length < min_len:
                    if length >= 3 * tw:
                        rejected.append({'a': A['idx'], 'b': B['idx'], 'why': 'Überlappung %.0f mm < %.0f mm'
                                         % (length, min_len)})
                    continue
                use = max(0.0, length - 2 * cg)
                k = 1 + int(use // spacing) if use > 0 else 1
                pos = [length / 2.0] if k == 1 else [cg + j * use / (k - 1) for j in range(k)]
                half = (use / (2.0 * (k - 1))) if k > 1 else max(0.0, length / 2.0 - cg)
                for d in pos:
                    alts, why0 = [], None
                    offs = [0.0] + [sg * j * 10.0 for j in range(1, 40) for sg in (1, -1) if j * 10.0 <= half]
                    for off in offs[:15]:       # Ausweichstellen auf derselben Kante (z. B. Start liegt dort)
                        dd = min(max(d + off, 0.0), length)
                        sa, qa = r[min(len(r) - 1, max(0, int(round(dd / step))))]
                        qb = closest_on_poly(B['outer'], qa, B['_c'])
                        why = _bridge_reject(A, B, sa, qa, qb, parts, thr, cg, rmin, tw, td)
                        if why:
                            why0 = why0 or (why, qa)
                            continue
                        alts.append({'a': A['idx'], 'b': B['idx'], 'sa': sa, 'pa': qa, 'sb': qb['s'], 'pb': qb['pt'],
                                     'gap': qb['d'], 'length': length})
                    if not alts:
                        rejected.append({'a': A['idx'], 'b': B['idx'], 'pt': why0[1], 'why': why0[0]})
                        continue
                    out.append(dict(alts[0], alts=alts))
    detect_bridges.rejected = rejected
    return out


def _bridge_reject(A, B, sa, qa, qb, parts, thr, cg, rmin, tw, td):
    for P, s in ((A, sa), (B, qb['s'])):
        if any(cyc_dist(s, sc, P['per']) < cg for sc in P['_sharp']):
            return 'zu nah an einer Ecke von %s' % P.get('name')
        if local_radius(P['outer'], s, max(tw, td), P['_c']) < rmin:
            return 'enger Radius an %s' % P.get('name')
    tg = point_at(A['outer'], sa, A['_c'])[2]
    nrm = (tg[1], -tg[0])
    o = (qa[0] + nrm[0] * 0.01, qa[1] + nrm[1] * 0.01)
    clr, kind, idx = ray_clearance(o, nrm, [B['outer']], (-1e9, -1e9, 1e9, 1e9), max_d=thr + 1.0)
    if kind != 'teil' or clr > thr + 0.5:
        return 'Kanten liegen sich nicht direkt gegenüber'
    mid = ((qa[0] + qb['pt'][0]) / 2.0, (qa[1] + qb['pt'][1]) / 2.0)
    lim = thr + tw / 2.0
    for C in parts:
        if C is A or C is B:
            continue
        bx = bbox(C['outer'])
        if mid[0] < bx[0] - lim - 5 or mid[0] > bx[2] + lim + 5 or mid[1] < bx[1] - lim - 5 or mid[1] > bx[3] + lim + 5:
            continue
        if min(dist_point_poly(q, C['outer']) for q in (mid, qa, qb['pt'])) <= lim:
            return 'drittes Teil %s zu nah (T-Stoß/Ecke)' % C.get('name')
    return None


# ---------------------------------------------------------------- Gesamtplan je Rohteil
# ---------------------------------------------------------------- Bearbeitungen aus der Palette (ab 1.2.0)
def part_sig(part):
    """Kennung der Lage/Form eines Teils – passt sie nicht mehr, gilt eine Bearbeitung als veraltet."""
    return {'a': round(part['area'] / 100.0, 1), 'cx': round(part['centroid'][0], 1),
            'cy': round(part['centroid'][1], 1), 'per': round(part['per'], 1)}


def sig_match(part, sg, tol=1.5):
    if not sg:
        return False
    try:
        return (abs(part['centroid'][0] - float(sg['cx'])) <= tol and abs(part['centroid'][1] - float(sg['cy'])) <= tol
                and abs(part['per'] - float(sg['per'])) <= max(2.0, 0.005 * part['per'])
                and abs(part['area'] / 100.0 - float(sg['a'])) <= max(0.5, 0.005 * part['area'] / 100.0))
    except (KeyError, TypeError, ValueError):
        return False


def s_ref(part):
    """Bogenlänge des Bezugs-Eckpunkts (kleinstes x+y, dann kleinstes x) – unabhängig vom Konturanfang der
    B-Rep-Schleife, damit Konturparameter beim erneuten Lesen gleich bleiben."""
    if '_sref' not in part:
        o, c = part['outer'], part['_c'][0]
        best = min(range(len(o)), key=lambda i: (round(o[i][0] + o[i][1], 2), round(o[i][0], 2), i))
        part['_sref'] = c[best]
    return part['_sref']


def to_u(part, s):
    """Konturparameter 0…1 ab Bezugs-Eckpunkt."""
    return ((s - s_ref(part)) % part['per']) / part['per'] if part['per'] > 0 else 0.0


def from_u(part, u):
    return (s_ref(part) + float(u) * part['per']) % part['per']


def start_at(part, s, cfg, manual=True):
    """Startpunkt an Bogenlänge s (Einstich im Abfall, Richtung zum Ziel des Teils)."""
    pt, i, _t = point_at(part['outer'], s, part['_c'])
    tgt = part.get('target') or pt
    st = {'pt': pt, 's': s, 'vertex': False, 'i': i, 'manual': manual, 'mode': 'manuell',
          'to_centre': (tgt[0] - pt[0], tgt[1] - pt[1])}
    nx, ny = outward_normal(part['outer'], s, part['_c'])
    off = float(cfg['tool_d']) / 2.0 + 2.0
    st['entry'] = (pt[0] + nx * off, pt[1] + ny * off)
    return st


def _resolve_overrides(parts, ov, info):
    """Bearbeitungen den aktuellen Teilen zuordnen (Schlüssel = ContourNest-Teil-ID#Kopie, Lage/Form muss
    passen). Rückgabe {idx: eintrag}; Veraltetes landet in info['stale']."""
    by_key = {p.get('key'): p for p in parts}
    res = {}
    for key, e in ((ov or {}).get('parts') or {}).items():
        if not (e.get('tabs') is not None or e.get('start') is not None or e.get('starts_holes')):
            continue
        p = by_key.get(key)
        if p is None:
            info['stale'].append('%s: Teil nicht mehr im Nesting' % (e.get('name') or key))
        elif not sig_match(p, e.get('sig')):
            info['stale'].append('%s: Lage/Form geändert (Nesting geändert)' % (p.get('name') or key))
        else:
            res[p['idx']] = e
    return res


def _ov_part(parts, ov, key, info, what):
    by_key = {p.get('key'): p for p in parts}
    p = by_key.get(key)
    sg = (((ov or {}).get('parts') or {}).get(key) or {}).get('sig')
    if p is None or (sg is not None and not sig_match(p, sg)):
        info['stale'].append('%s: %s passt nicht mehr (Nesting geändert)' % (key, what))
        return None
    return p


# ---------------------------------------------------------------- Gesamtplan je Rohteil
def plan_sheet(sheet, cfg=None, ov=None):
    """Plan eines Rohteils. ov = Bearbeitungen aus der Palette (fs_edit): je Teil feste Einzelstege /
    Startpunkt, zusätzliche und gelöschte Brücken. Werden von Vorschau UND Operationen gleich verwendet."""
    cfg = dict(DEFAULTS, **(cfg or {}))
    parts = prepare(sheet, cfg)
    for p in parts:
        p['large'] = is_large(p, cfg)
    rect = (0.0, 0.0, float(sheet['length']), float(sheet['width']))
    centre = (rect[2] / 2.0, rect[3] / 2.0)
    warnings = []
    ovi = {'stale': [], 'parts': [], 'bridges_add': 0, 'bridges_del': 0, 'bridges_del_unmatched': 0, 'order_manual': False}
    pov = _resolve_overrides(parts, ov, ovi)
    order_info, timing = [], {}
    if cfg.get('reihenfolge', 'rest') == 'rest' and parts:
        order, order_info, targets, timing = order_by_remainder(parts, sheet, cfg)
    else:
        order = order_parts(parts, sheet, cfg)
        targets = {p['idx']: centre for p in parts}
    # 2.0.5: manuelle Reihenfolge (ov['order'] = [part keys …])
    man_ord = [k for k in ((ov or {}).get('order') or []) if isinstance(k, str)]
    if man_ord and parts:
        by_key = {p.get('key'): p['idx'] for p in parts if p.get('key')}
        seen, new_order = set(), []
        for k in man_ord:
            i = by_key.get(k)
            if i is not None and i not in seen:
                new_order.append(i); seen.add(i)
        for i in order:
            if i not in seen:
                new_order.append(i)
        if new_order:
            order = new_order
            ovi['order_manual'] = True
    for p in parts:
        p['target'] = targets.get(p['idx'], centre)
        e = pov.get(p['idx'])
        if e is not None and e.get('start') is not None:
            p['start'] = start_at(p, from_u(p, e['start']), cfg)
        else:
            p['start'] = start_point(p, p['target'], cfg)
        # 2.0.5: Start je Innenkante (Durchbruch)
        hs_ov = (e or {}).get('starts_holes') if e is not None else None
        hole_starts = []
        for hi, hpoly in enumerate(p['holes']):
            u = None
            if isinstance(hs_ov, dict):
                u = hs_ov.get(str(hi), hs_ov.get(hi))
            elif isinstance(hs_ov, list) and hi < len(hs_ov):
                u = hs_ov[hi]
            if u is not None:
                hc = cum(hpoly)
                hole_starts.append(hole_start_at(hpoly, float(u) * (hc[1] or 1.0), cfg, manual=True))
            else:
                hole_starts.append(hole_start(hpoly, cfg))
        p['hole_starts'] = hole_starts
    td, tw = float(cfg['tool_d']), float(cfg['steg_breite'])
    min_start = max(float(cfg['start_abstand_min']), 3 * td) + tw / 2
    counts = {p['idx']: tab_count(p, cfg) for p in parts}
    space = {p['idx']: tab_spacing(p, counts[p['idx']][0], cfg) for p in parts}
    bridges = detect_bridges(parts, cfg) if cfg['bruecken'] else []
    rejected = list(getattr(detect_bridges, 'rejected', [])) if cfg['bruecken'] else []
    forced = {p['idx']: [] for p in parts}
    used_bridges = []

    def add_bridge(br, manual=False):
        forced[br['a']].append({'s': br['sa'], 'pt': br['pa'], 'bridge': True, 'kind': 'bruecke', 'facing': br['b'],
                                'score': 0.7, 'web': 0.0, 'manual': manual})
        forced[br['b']].append({'s': br['sb'], 'pt': br['pb'], 'bridge': True, 'kind': 'bruecke', 'facing': br['a'],
                                'score': 0.7, 'web': 0.0, 'manual': manual})
        used_bridges.append(dict(br, manual=manual))
    # 1) von Hand hinzugefügte Brücken (gelten auch bei „Brückenstege“ aus und ohne Filter)
    for e in (ov or {}).get('bridges_add') or []:
        A = _ov_part(parts, ov, e.get('a'), ovi, 'Brücke')
        B = _ov_part(parts, ov, e.get('b'), ovi, 'Brücke') if A is not None else None
        if A is None or B is None:
            continue
        sa, sb = from_u(A, e['ua']), from_u(B, e['ub'])
        pa, pb = point_at(A['outer'], sa, A['_c'])[0], point_at(B['outer'], sb, B['_c'])[0]
        add_bridge({'a': A['idx'], 'b': B['idx'], 'sa': sa, 'pa': pa, 'sb': sb, 'pb': pb,
                    'gap': math.dist(pa, pb), 'length': 0.0}, manual=True)
        ovi['bridges_add'] += 1
    dels = []
    for e in (ov or {}).get('bridges_del') or []:
        A = next((p for p in parts if p.get('key') == e.get('a')), None)
        B = next((p for p in parts if p.get('key') == e.get('b')), None)
        if A is None or B is None:
            ovi['bridges_del_unmatched'] += 1
            continue
        dels.append([A['idx'], B['idx'], from_u(A, e['ua']), False])
    gross_off = not cfg.get('stege_gross_an', True)
    for slot in sorted(bridges, key=lambda b: (-b['length'], b['a'], b['b'], b['sa'])):
        A, B = parts[slot['a']], parts[slot['b']]
        if gross_off and A['large'] and B['large']:          # 1.2.1: nur groß–groß entfällt
            rejected.append({'a': slot['a'], 'b': slot['b'], 'pt': slot['pa'],
                             'why': 'zwei große Teile ohne Stege (keine Brücke groß–groß)'})
            continue
        hit = None
        for d in dels:                       # von Hand gelöschte Brücke (gleiches Paar, ≤ 40 mm)
            for alt in slot.get('alts') or [slot]:
                sa = alt['sa'] if d[0] == slot['a'] else alt['sb']
                if {d[0], d[1]} == {slot['a'], slot['b']} and cyc_dist(sa, d[2], parts[d[0]]['per']) <= 40.0:
                    hit = d
                    break
            if hit:
                break
        if hit:
            hit[3] = True
            rejected.append({'a': slot['a'], 'b': slot['b'], 'pt': slot['pa'], 'why': 'von Hand gelöscht'})
            continue
        br, why = None, None
        for alt in slot.get('alts') or [slot]:
            if (cyc_dist(alt['sa'], A['start']['s'], A['per']) < min_start
                    or cyc_dist(alt['sb'], B['start']['s'], B['per']) < min_start):
                why = why or 'zu nah am Startpunkt'
                continue
            if (any(cyc_dist(alt['sa'], t['s'], A['per']) < space[A['idx']] for t in forced[A['idx']])
                    or any(cyc_dist(alt['sb'], t['s'], B['per']) < space[B['idx']] for t in forced[B['idx']])):
                why = 'Abstand zu anderer Brücke'
                continue
            br = alt
            break
        if br is None:
            rejected.append({'a': slot['a'], 'b': slot['b'], 'pt': slot['pa'], 'why': why})
            continue
        add_bridge({k: v for k, v in br.items() if k != 'alts'})
    ovi['bridges_del'] = sum(1 for d in dels if d[3])
    ovi['bridges_del_unmatched'] += sum(1 for d in dels if not d[3])
    for p in parts:
        others = [q['outer'] for q in parts if q is not p]
        n, why = counts[p['idx']]
        if p['small'] and not cfg['stege']:
            warnings.append('%s: Kleinteil unter Mindestfläche Vakuum – Stege trotz „Haltestege aus“' % p.get('name'))
        e = pov.get(p['idx'])
        if e is not None and e.get('tabs') is not None:          # Einzelstege von Hand festgelegt
            p['tabs'] = list(forced[p['idx']])
            for u in e['tabs']:
                sx = from_u(p, u)
                p['tabs'].append({'s': sx, 'pt': point_at(p['outer'], sx, p['_c'])[0], 'bridge': False,
                                  'kind': 'manuell', 'score': 0.0, 'web': 0.0, 'manual': True})
            p['tabs_dropped'] = 0
            p['tab_spacing'] = tab_spacing(p, n, cfg)
            p['tab_reason'] = 'von Hand (Palette)'
            p['tab_target'] = len(p['tabs'])
            ovi['parts'].append(p.get('key'))
            continue
        if e is not None:
            ovi['parts'].append(p.get('key'))
        n = max(n, len(forced[p['idx']]))
        p['tabs'] = place_tabs(p, n, forced[p['idx']], others, rect, p['start']['s'], cfg)
        p['tab_reason'] = why
        p['tab_target'] = n
        if p.get('tabs_dropped'):
            warnings.append('%s: nur %d von %d Stegen – übrige Stellen gesperrt (Nachbarteil zu nah, Ecke, Start) '
                            'oder Mindestabstand %.0f mm' % (p.get('name'), len(p['tabs']), n, p['tab_spacing']))
    for msg in ovi['stale']:
        warnings.append('Bearbeitung ignoriert – %s' % msg)
    if ovi['bridges_del_unmatched']:
        warnings.append('%d gelöschte Brücke(n) gibt es nicht mehr (Einstellungen/Nesting geändert) – ohne Wirkung'
                        % ovi['bridges_del_unmatched'])
    inner = []
    for i in order:
        p = parts[i]
        inner += [{'part': i, 'kind': 'loch', 'poly': h} for h in p['holes']]
        if cfg['taschen']:
            inner += [{'part': i, 'kind': 'tasche', 'poly': q} for q in p['pockets']]
    inner = [inner[k] for k in nn_order([centroid(it['poly']) for it in inner])]      # nächster Nachbar
    return {'sheet': {k: sheet.get(k) for k in ('no', 'name', 'length', 'width', 'thickness', 'orient', 'kind', 'zero',
                                                'W', 'H', 'label', 'zero_x', 'zero_y', 'zero_side', 'zero_text',
                                                'grain_axis') if k in sheet or k in ('no', 'name', 'length', 'width',
                                                                                     'thickness')},
            'cfg': cfg, 'parts': parts, 'order': order, 'bridges': used_bridges, 'inner': inner,
            'centre': centre, 'warnings': warnings, 'order_info': order_info, 'timing': timing,
            'bridges_rejected': rejected, 'overrides': ovi}


def apply_manual(plan, start_pts=None, tab_pts=None, max_d=15.0):
    """Von Hand gesetzte Skizzenpunkte übernehmen (Rohteil-mm). Jeder Punkt gehört zum Teil, dessen Außenkontur
    am nächsten liegt (höchstens max_d, sonst „ignoriert“ – passt nicht zum aktuellen Nesting). Startpunkt:
    ersetzt den berechneten; Stege: ersetzen ALLE berechneten Stege des Teils. Brückenkennung: liegt einem
    Stegpunkt ein Stegpunkt eines anderen Teils im Spalt gegenüber (≤ Werkzeug-Ø + Zugabe + 2 mm), sind beide
    Brückenstege. Rückgabe {'start', 'tabs', 'bridges', 'ignored', 'ignored_pts', 'parts_without'}."""
    res = {'start': 0, 'tabs': 0, 'bridges': 0, 'ignored': 0, 'ignored_pts': [], 'parts_without': []}
    parts = plan['parts']
    cfg = plan['cfg']

    def owner(q):
        best = None
        for p in parts:
            h = closest_on_poly(p['outer'], q, p['_c'])
            if h['d'] <= max_d and (best is None or h['d'] < best[1]['d']):
                best = (p, h)
        return best
    for q in start_pts or []:
        o = owner(q)
        if o is None:
            res['ignored'] += 1
            res['ignored_pts'].append(tuple(q))
            continue
        p, h = o
        tgt = p.get('target') or plan['centre']
        p['start'] = {'pt': h['pt'], 's': h['s'], 'vertex': False, 'i': h['i'], 'manual': True,
                      'to_centre': (tgt[0] - h['pt'][0], tgt[1] - h['pt'][1])}
        nx, ny = outward_normal(p['outer'], h['s'], p['_c'])
        off = float(cfg['tool_d']) / 2.0 + 2.0
        p['start']['entry'] = (h['pt'][0] + nx * off, h['pt'][1] + ny * off)
        res['start'] += 1
    manual = {}
    for q in tab_pts or []:
        o = owner(q)
        if o is None:
            res['ignored'] += 1
            res['ignored_pts'].append(tuple(q))
            continue
        p, h = o
        manual.setdefault(p['idx'], []).append({'s': h['s'], 'pt': h['pt'], 'bridge': False, 'kind': 'manuell',
                                                'score': 0.0, 'web': 0.0, 'manual': True, 'raw': tuple(q)})
        res['tabs'] += 1
    thr = float(cfg['tool_d']) + float(cfg['bruecke_extra']) + 2.0
    flat = [(idx, t) for idx, ts in manual.items() for t in ts]
    for ia, ta in flat:
        for ib, tb in flat:
            if ib != ia and math.dist(ta['pt'], tb['pt']) <= thr:
                ta['bridge'] = True
                ta['facing'] = ib
                ta['kind'] = 'bruecke'
    res['bridges'] = sum(1 for _i, t in flat if t['bridge'])
    for idx, tabs in manual.items():
        parts[idx]['tabs'] = tabs
        parts[idx]['tab_reason'] = 'manuell (Skizze)'
        parts[idx]['tabs_dropped'] = 0
    if tab_pts:
        res['parts_without'] = [p.get('name') for p in parts if p['idx'] not in manual]
    plan['manual'] = res
    return res


def plan_summary(plan):
    """Kompakte, JSON-fähige Zusammenfassung (für Protokoll und Tests)."""
    ps = plan['parts']
    return {
        'sheet': plan['sheet'], 'warnings': plan['warnings'],
        'order': [{'nr': k + 1, 'name': ps[i].get('name'), 'key': ps[i].get('key'), 'area_cm2': round(ps[i]['area'] / 100, 1),
                   'dist_center_mm': round(ps[i]['dist_center'], 1), 'small': ps[i]['small'],
                   'start': [round(v, 2) for v in ps[i]['start']['pt']], 'start_vertex': ps[i]['start']['vertex'],
                   'start_mode': ps[i]['start'].get('mode', 'manuell' if ps[i]['start'].get('manual') else ''),
                   'tabs': [{'pt': [round(v, 2) for v in t['pt']], 'bridge': t.get('bridge', False),
                             'web_mm': round(t.get('web', 0), 1), 'manual': bool(t.get('manual'))}
                            for t in ps[i]['tabs']], 'large': ps[i].get('large', False),
                   'tab_reason': ps[i]['tab_reason'], 'holes': len(ps[i]['holes']),
                   'tab_spacing_mm': round(ps[i].get('tab_spacing', 0.0), 1),
                   'target': [round(v, 1) for v in ps[i].get('target', plan['centre'])]}
                  for k, i in enumerate(plan['order'])],
        'order_rule': plan['cfg'].get('reihenfolge', 'rest'),
        'order_info': [{'nr': k + 1, 'name': ps[e['idx']].get('name'), 'rest_pct': round(e['rest_pct'], 2),
                        'rest_m2': round(e['rest_mm2'] / 1e6, 4), 'bereiche': e['bereiche'],
                        'eilgang_mm': round(e['eilgang_mm'], 1), 'gleichstand': e['gleichstand']}
                       for k, e in enumerate(plan.get('order_info') or [])],
        'timing': {k: (round(v, 3) if isinstance(v, float) else v) for k, v in (plan.get('timing') or {}).items()},
        'overrides': plan.get('overrides'),
        'bridges_rejected': [{'a': ps[r['a']].get('name'), 'b': ps[r['b']].get('name'), 'why': r['why'],
                              'pt': [round(v, 1) for v in r['pt']] if r.get('pt') else None}
                             for r in plan.get('bridges_rejected') or []],
        'bridges': [{'a': ps[b['a']].get('name'), 'b': ps[b['b']].get('name'), 'gap_mm': round(b['gap'], 2),
                     'length_mm': round(b['length'], 1)} for b in plan['bridges']],
        'inner': len(plan['inner'])}


# ---------------------------------------------------------------- Vorschau (PNG ohne Zusatzbibliotheken)
_FONT = {   # 5×7-Ziffern
    'X': ('10001', '10001', '01010', '00100', '01010', '10001', '10001'),
    'Y': ('10001', '10001', '01010', '00100', '00100', '00100', '00100'),
    '0': ('01110', '10001', '10011', '10101', '11001', '10001', '01110'),
    '1': ('00100', '01100', '00100', '00100', '00100', '00100', '01110'),
    '2': ('01110', '10001', '00001', '00010', '00100', '01000', '11111'),
    '3': ('11110', '00001', '00001', '01110', '00001', '00001', '11110'),
    '4': ('00010', '00110', '01010', '10010', '11111', '00010', '00010'),
    '5': ('11111', '10000', '11110', '00001', '00001', '10001', '01110'),
    '6': ('00110', '01000', '10000', '11110', '10001', '10001', '01110'),
    '7': ('11111', '00001', '00010', '00100', '01000', '01000', '01000'),
    '8': ('01110', '10001', '10001', '01110', '10001', '10001', '01110'),
    '9': ('01110', '10001', '10001', '01111', '00001', '00010', '01100'),
    'I': ('01110', '00100', '00100', '00100', '00100', '00100', '01110'),
}


class Canvas:
    def __init__(self, w, h, bg=(255, 255, 255)):
        self.w, self.h = int(w), int(h)
        self.px = bytearray(bytes(bg) * (self.w * self.h))

    def set(self, x, y, c):
        x, y = int(round(x)), int(round(y))
        if 0 <= x < self.w and 0 <= y < self.h:
            i = (y * self.w + x) * 3
            self.px[i:i + 3] = bytes(c)

    def disc(self, x, y, r, c):
        r = max(0.5, r)
        for yy in range(int(y - r), int(y + r) + 1):
            for xx in range(int(x - r), int(x + r) + 1):
                if (xx - x) ** 2 + (yy - y) ** 2 <= r * r:
                    self.set(xx, yy, c)

    def line(self, x0, y0, x1, y1, c, w=1.0):
        n = int(max(abs(x1 - x0), abs(y1 - y0)) * 2) + 1
        for k in range(n + 1):
            t = k / n
            x, y = x0 + (x1 - x0) * t, y0 + (y1 - y0) * t
            if w <= 1.0:
                self.set(x, y, c)
            else:
                self.disc(x, y, w / 2.0, c)

    def poly(self, pts, c, w=1.0):
        for i in range(len(pts)):
            a, b = pts[i], pts[(i + 1) % len(pts)]
            self.line(a[0], a[1], b[0], b[1], c, w)

    def fill(self, pts, c):
        ys = [p[1] for p in pts]
        for y in range(max(0, int(min(ys))), min(self.h - 1, int(max(ys))) + 1):
            xs = []
            for i in range(len(pts)):
                a, b = pts[i], pts[(i + 1) % len(pts)]
                if (a[1] <= y + 0.5 < b[1]) or (b[1] <= y + 0.5 < a[1]):
                    xs.append(a[0] + (y + 0.5 - a[1]) * (b[0] - a[0]) / (b[1] - a[1]))
            xs.sort()
            for j in range(0, len(xs) - 1, 2):
                for x in range(int(math.ceil(xs[j])), int(xs[j + 1]) + 1):
                    self.set(x, y, c)

    def text(self, x, y, s, c, scale=2):
        for k, ch in enumerate(s):
            g = _FONT.get(ch)
            if not g:
                continue
            for r, row in enumerate(g):
                for col, bit in enumerate(row):
                    if bit == '1':
                        for dy in range(scale):
                            for dx in range(scale):
                                self.set(x + (k * 6 + col) * scale + dx, y + r * scale + dy, c)

    def png(self, path):
        import struct
        import zlib
        raw = b''.join(b'\x00' + bytes(self.px[y * self.w * 3:(y + 1) * self.w * 3]) for y in range(self.h))

        def chunk(t, d):
            return struct.pack('>I', len(d)) + t + d + struct.pack('>I', zlib.crc32(t + d) & 0xffffffff)
        data = (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', self.w, self.h, 8, 2, 0, 0, 0))
                + chunk(b'IDAT', zlib.compress(raw, 6)) + chunk(b'IEND', b''))
        with open(path, 'wb') as f:
            f.write(data)
        return path


def machine_view(sheet):
    """(X-Maß, Y-Maß, Punkt Material->Maschine, Richtung Material->Maschine) – 1.3.0: Vorschau so, wie das
    Rohteil auf dem Maschinentisch liegt (quer: Länge in Y)."""
    Lm, Wm = float(sheet['length']), float(sheet['width'])
    if sheet.get('orient') == 'quer':
        return Wm, Lm, (lambda q: (Wm - q[1], q[0])), (lambda d: (-d[1], d[0]))
    return Lm, Wm, (lambda q: (q[0], q[1])), (lambda d: (d[0], d[1]))


def _margins(sheet, m=12, small=False):
    """(rechts, oben): Platz für das Achsenkreuz, wenn der Nullpunkt an der rechten/hinteren Kante liegt."""
    if sheet.get('zero_x') is None:
        return m, m
    L, W = machine_view(sheet)[:2]
    extra = 24 if small else 46
    return (m + extra if sheet['zero_x'] > L * 0.75 else m), (m + extra if sheet['zero_y'] > W * 0.75 else m)


def _plan_height(plan, width, m=12, small=False):
    L, W = machine_view(plan['sheet'])[:2]
    mr, mt = _margins(plan['sheet'], m, small)
    return int(W * (width - m - mr) / L) + m + mt


def _draw_zero(cv, sheet, trm, k_, sc):
    """Nullpunkt: Achsenkreuz X (rot) / Y (grün) + Kreuz; Kreis gefüllt = Oberseite, Ring = Unterseite."""
    if sheet.get('zero_x') is None:
        return
    zx, zy = trm((float(sheet['zero_x']), float(sheet['zero_y'])))
    ax = ay = 34.0 * k_                   # Pfeile immer in +X/+Y (Maschinenachsen); Platz schafft _margins
    w = 2.0 if k_ >= 1 else 1.4
    cv.line(zx, zy, zx + ax, zy, (210, 0, 0), w)
    cv.line(zx + ax, zy, zx + ax - 6 * k_, zy - 4 * k_, (210, 0, 0), w)
    cv.line(zx + ax, zy, zx + ax - 6 * k_, zy + 4 * k_, (210, 0, 0), w)
    cv.line(zx, zy, zx, zy - ay, (0, 140, 0), w)
    cv.line(zx, zy - ay, zx - 4 * k_, zy - ay + 6 * k_, (0, 140, 0), w)
    cv.line(zx, zy - ay, zx + 4 * k_, zy - ay + 6 * k_, (0, 140, 0), w)
    if k_ >= 1:
        cv.text(zx + ax + 3, zy - 3, 'X', (210, 0, 0), 1)
        cv.text(zx - 2, zy - ay - 10, 'Y', (0, 140, 0), 1)
    r = 6 * k_
    ring = [(zx + r * math.cos(t * math.pi / 12), zy + r * math.sin(t * math.pi / 12)) for t in range(24)]
    if sheet.get('zero_side') == 'oben':
        cv.fill(ring, (255, 255, 255))
    cv.poly(ring, (0, 0, 0), 1.4)
    cv.line(zx - 9 * k_, zy, zx + 9 * k_, zy, (0, 0, 0), 1.2)
    cv.line(zx, zy - 9 * k_, zx, zy + 9 * k_, (0, 0, 0), 1.2)


def _draw_plan(cv, plan, x0=0, y0=0, width=900, small=False):
    """Plan in eine vorhandene Leinwand zeichnen (Ursprung x0/y0, Breite width). Lage wie auf dem
    Maschinentisch (quer liegende Rohteile gedreht), mit Nullpunkt."""
    L, W, mach, mdir = machine_view(plan['sheet'])
    m = 12
    mr, mt = _margins(plan['sheet'], m, small)
    sc = (width - m - mr) / L
    k_ = 0.5 if small else 1.0           # Symbole in der Übersicht kleiner

    def trm(q):                          # Maschine -> Bild
        return (x0 + m + q[0] * sc, y0 + mt + (W - q[1]) * sc)

    def tr(q):                           # Material (Planung) -> Bild
        return trm(mach(q))
    cv.fill([trm(q) for q in ((0, 0), (L, 0), (L, W), (0, W))], (236, 222, 196))
    cv.poly([trm(q) for q in ((0, 0), (L, 0), (L, W), (0, W))], (120, 100, 70), 2)
    parts = plan['parts']
    n = max(1, len(plan['order']))
    for k, i in enumerate(plan['order']):
        p = parts[i]
        g = int(200 - 140 * k / n)
        cv.fill([tr(q) for q in p['outer']], (g, 225 - int(60 * k / n), 255))
        cv.poly([tr(q) for q in p['outer']], (30, 60, 120), 1.6 * k_ if small else 1.6)
        for h in p['holes']:
            cv.fill([tr(q) for q in h], (236, 222, 196))
            cv.poly([tr(q) for q in h], (200, 120, 0), 1.6)
        for q in p.get('pockets') or []:          # Taschen (nicht durchgehend): immer hell zeigen
            cv.poly([tr(v) for v in q], (90, 120, 170) if not plan['cfg'].get('taschen') else (200, 120, 0), 1.0)
    if not small:
        for it in plan['inner']:
            c = centroid(it['poly'])
            x, y = tr(c)
            cv.text(x - 2, y - 6, 'I', (200, 120, 0), 2)
    for k, i in enumerate(plan['order']):
        p = parts[i]
        sx, sy = tr(p['start']['pt'])
        tc = mdir(p['start'].get('to_centre') or (0.0, 0.0))      # Richtung zur größten Restfläche
        vx, vy = tc[0], -tc[1]
        L2 = math.hypot(vx, vy) or 1.0
        ex, ey = sx + vx / L2 * 28 * k_, sy + vy / L2 * 28 * k_
        cv.line(sx, sy, ex, ey, (200, 0, 0), 2 * k_ if small else 2)
        if not small:
            for a in (2.6, -2.6):
                ca, sa = math.cos(a), math.sin(a)
                cv.line(ex, ey, ex + (vx * ca - vy * sa) / L2 * 9, ey + (vx * sa + vy * ca) / L2 * 9, (200, 0, 0), 2)
        cv.disc(sx, sy, 4 * k_, (200, 0, 0))
        for t in p['tabs']:
            tx, ty = tr(t['pt'])
            cv.disc(tx, ty, 4.5 * k_, (140, 0, 170) if t.get('bridge') else
                    ((0, 200, 200) if t.get('manual') else (0, 140, 0)))
        c = tr(p['centroid'])
        txt = str(k + 1)
        sc_t = 1 if small else 2
        cv.disc(c[0], c[1], 13 * k_ + (1 if small else 0), (255, 255, 255))
        cv.text(c[0] - len(txt) * 3 * sc_t + 1, c[1] - 3.5 * sc_t, txt, (0, 0, 0), sc_t)
    _draw_zero(cv, plan['sheet'], trm, k_, sc)


def render_preview(plan, path, width=900):
    """Rohteil mit Reihenfolge (Nummern), Startpunkten (Pfeil zur Mitte), Stegen (Brücken violett),
    Innenkonturen (I). Y nach oben wie in Fusion."""
    cv = Canvas(width, _plan_height(plan, width))
    _draw_plan(cv, plan, 0, 0, width)
    return cv.png(path)


def render_contact(plans, path, width=900, cols=None):
    """Übersicht („Alle“): alle Rohteile als Kacheln (Raster), je Kachel oben links die laufende Nummer."""
    n = len(plans)
    if not n:
        raise ValueError('keine Rohteile')
    cols = cols or (1 if n == 1 else 2 if n <= 4 else 3)
    rows = (n + cols - 1) // cols
    gap, head = 8, 20
    cw = (width - gap * (cols + 1)) // cols
    hs = [_plan_height(p, cw, small=True) for p in plans]
    rh = [max(hs[r * cols:(r + 1) * cols]) + head for r in range(rows)]
    cv = Canvas(width, sum(rh) + gap * (rows + 1))
    y = gap
    for r in range(rows):
        for c in range(cols):
            k = r * cols + c
            if k >= n:
                break
            x = gap + c * (cw + gap)
            cv.text(x + 2, y + 2, str(k + 1), (60, 60, 60), 2)
            _draw_plan(cv, plans[k], x, y + head, cw, small=True)
        y += rh[r] + gap
    return cv.png(path)
