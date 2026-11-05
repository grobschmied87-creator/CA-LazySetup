# -*- coding: utf-8 -*-
"""LazySetup 2.0.3 – Silhouette eines Teils (Draufsicht = Projektion auf die Plattenebene).

Silhouette = Vereinigung der XY-Projektionen ALLER Flächen des Teils. Jede Fläche liefert ein Gebiet
(größte projizierte Schleife = außen, übrige = Löcher); senkrechte Flächen haben keine Fläche und fallen weg.
  • Außenkontur  = äußerster Umriss (inkl. Fase, Falz, Überstand – egal ob oben oder unten)
  • Durchbrüche  = nur Öffnungen, durch die man entlang Z durch das GANZE Teil sieht
  • Sacklöcher, Taschen, Nuten werden vom Boden/Deckel überdeckt und verschwinden
Reines Python (keine Fusion-Abhängigkeit): Kanten an allen Schnittpunkten teilen, jede Teilkante behalten,
die nicht im Innern eines anderen Gebiets liegt (deckungsgleiche Kanten: gleiche Richtung -> einmal,
Gegenrichtung -> innen, weg), dann zu Schleifen verbinden (Gebiet immer links, engste Linkskurve).
Jede Ergebniskante trägt ihre Herkunft (Gebiet, Schleife, Kante) – so kann der Aufrufer erkennen, ob eine
Silhouetten-Schleife genau einer vorhandenen B-Rep-Schleife entspricht (dann deren Kanten) oder neu
zusammengesetzt ist (dann Skizze).
Einheiten: mm. Gebiete in Prioritätsreihenfolge (bei deckungsgleichen Kanten gewinnt das frühere)."""
import math

Q = 1e5             # Rundung 0,00001 mm (nur für exakte Schlüssel)
TOL = 0.005         # mm: EINE Toleranz für Teilen, Kollinearität und „liegt auf der Kante“ (2.0.2)
SNAP = 0.01         # mm: Punkte verschiedener Flächen verschweißen
EDGE_SNAP = 0.06    # mm: Punkte/Kanten späterer Flächen auf frühere ziehen (Fusion-Abtastung: Sehne ≤ 0,05 mm)
CLOSE = 0.05        # mm: tolerantes Schließen offener Ketten (= Abtasttoleranz STROKE_TOL)
EPS_ON = TOL
MIN_AREA = 0.5      # mm²: kleinere Gebiete/Schleifen (Splitter) verwerfen
MIN_WIDTH = 0.1     # mm: Gebiete mit kleinerer mittlerer Breite (2·Fläche/Umfang) sind Splitter (2.0.2)
BAND = 2.0          # mm: Höhe der Streifen für den Punkt-in-Gebiet-Test
FAST_TOL = 0.12     # mm (2.0.3): Schnellweg-Toleranz = 2 × Abtasttoleranz + Reserve (vorher 0,05 = genau die
                    #   Sehnenabweichung -> Bögen/Rundungen anderer Flächen lagen knapp „außerhalb“)
BRIDGE_SNAP = 0.06  # mm (2.0.3): Kettenende liegt auf einer Flächenschleife
BRIDGE_GAP_MAX = 250.0   # mm: größte überbrückbare Lücke (Luftlinie)
BRIDGE_FACTOR = 2.0      # Weg entlang der Schleife ≤ Faktor × Lücke …
BRIDGE_ADD = 40.0        # … oder ≤ Lücke + 40 mm (der größere Wert gilt)


def _q(p):
    return (round(p[0] * Q) / Q, round(p[1] * Q) / Q)


def signed_area(p):
    a = 0.0
    n = len(p)
    for i in range(n):
        x0, y0 = p[i]
        x1, y1 = p[(i + 1) % n]
        a += x0 * y1 - x1 * y0
    return a / 2.0


def _clean(pts, tags):
    """Fangen, doppelte Punkte entfernen (Kante i = pts[i] -> pts[i+1], Tag je Kante)."""
    P, T = [], []
    n = len(pts)
    for i in range(n):
        p = _q(pts[i])
        if P and P[-1] == p:
            T[-1] = tags[i]          # Null-Kante: Tag der folgenden Kante übernehmen
            continue
        P.append(p)
        T.append(tags[i])
    while len(P) > 1 and P[-1] == P[0]:
        P.pop()
        T.pop()
    return P, T


def _reverse(pts, tags):
    n = len(pts)
    return pts[::-1], [tags[(n - 2 - j) % n] for j in range(n)]


def make_region(rings):
    """rings = [(pts, tags)] einer Fläche -> [(pts, tags)] mit größter Schleife zuerst (CCW), Löcher CW;
    None, wenn die projizierte Fläche (fast) null ist (senkrechte Fläche)."""
    rs = []
    for k, (pts, tags) in enumerate(rings):
        P, T = _clean(pts, tags)
        if len(P) < 3:
            continue
        a = signed_area(P)
        rs.append((abs(a), a, P, T, k))
    if not rs:
        return None
    rs.sort(key=lambda r: -r[0])
    out_a = rs[0][0]
    holes_a = sum(r[0] for r in rs[1:] if r[0] >= MIN_AREA * 0.01)
    if out_a - holes_a < max(MIN_AREA, 1e-4 * out_a):
        return None
    # 2.0.2: schmale Splitter (senkrechte Wand mit Abtast-/Lagerauschen): mittlere Breite 2·A/Umfang < MIN_WIDTH
    per = sum(math.hypot(P[(i + 1) % len(P)][0] - P[i][0], P[(i + 1) % len(P)][1] - P[i][1])
              for _aa, _a, P, _T, _k in rs for i in range(len(P)))
    if per > 0 and 2.0 * (out_a - holes_a) / per < MIN_WIDTH:
        return None
    reg = []
    for j, (aa, a, P, T, k) in enumerate(rs):
        if j > 0 and aa < MIN_AREA * 0.01:
            continue
        want_ccw = j == 0
        if (a > 0) != want_ccw:
            P, T = _reverse(P, T)
        reg.append((P, T, k))
    return reg


class _Index:
    """Rasterindex für Strecken (Rechteck-Raster) + Streifenindex in y für Strahltests."""

    def __init__(self, cell):
        self.cell = cell
        self.g = {}

    def cells(self, a, b, pad=0.0):
        c = self.cell
        x0, x1 = min(a[0], b[0]) - pad, max(a[0], b[0]) + pad
        y0, y1 = min(a[1], b[1]) - pad, max(a[1], b[1]) + pad
        for i in range(int(math.floor(x0 / c)), int(math.floor(x1 / c)) + 1):
            for j in range(int(math.floor(y0 / c)), int(math.floor(y1 / c)) + 1):
                yield (i, j)

    def add(self, s, a, b):
        for k in self.cells(a, b, EPS_ON):
            self.g.setdefault(k, []).append(s)

    def near(self, p):
        c = self.cell
        return self.g.get((int(math.floor(p[0] / c)), int(math.floor(p[1] / c))), ())


def _cross(ax, ay, bx, by):
    return ax * by - ay * bx


def _inter(a, b, c, d):
    """Berührungen/Schnitte von ab und cd: (Punkte auf ab, Punkte auf cd) – Teilungspunkte als Koordinaten.
    2.0.2: kollinear innerhalb TOL (gleiche Toleranz wie „auf der Kante“); Teilungspunkte sind die echten
    Endpunkte der anderen Strecke (keine Projektion) -> identische Schlüssel beim Verbinden."""
    rx, ry = b[0] - a[0], b[1] - a[1]
    sx, sy = d[0] - c[0], d[1] - c[1]
    lr, ls = math.hypot(rx, ry), math.hypot(sx, sy)
    if lr < 1e-9 or ls < 1e-9:
        return [], []
    pa, pc = [], []
    # Endpunkte der einen Strecke, die (innerhalb TOL) im Innern der anderen liegen: T-Stoß/Überdeckung
    for p in (c, d):
        if p != a and p != b and _dist_seg(p, a, b) <= TOL:
            t = ((p[0] - a[0]) * rx + (p[1] - a[1]) * ry) / (lr * lr)
            if TOL / lr < t < 1 - TOL / lr:
                pa.append(p)
    for p in (a, b):
        if p != c and p != d and _dist_seg(p, c, d) <= TOL:
            u = ((p[0] - c[0]) * sx + (p[1] - c[1]) * sy) / (ls * ls)
            if TOL / ls < u < 1 - TOL / ls:
                pc.append(p)
    den = _cross(rx, ry, sx, sy)
    if abs(den) > 1e-9 * lr * ls and not pa and not pc:
        qx, qy = c[0] - a[0], c[1] - a[1]
        t = _cross(qx, qy, sx, sy) / den
        u = _cross(qx, qy, rx, ry) / den
        if TOL / lr < t < 1 - TOL / lr and TOL / ls < u < 1 - TOL / ls:   # echter Schnitt im Innern
            p = _q((a[0] + t * rx, a[1] + t * ry))
            pa.append(p)
            pc.append(p)
    return pa, pc


def _dist_seg(p, a, b):
    rx, ry = b[0] - a[0], b[1] - a[1]
    l2 = rx * rx + ry * ry
    t = 0.0 if l2 < 1e-18 else max(0.0, min(1.0, ((p[0] - a[0]) * rx + (p[1] - a[1]) * ry) / l2))
    return math.hypot(p[0] - a[0] - t * rx, p[1] - a[1] - t * ry)


TOL_SAME = 0.1      # mm: Schleifen gleicher Lage (Ober-/Unterkante eines Lochs, anders abgetastet; 2.0.2: 0,1)


def _near_all(A, B, tol):
    for p in A:
        if min(_dist_seg(p, B[i], B[(i + 1) % len(B)]) for i in range(len(B))) > tol:
            return False
    return True


def _unify(regs):
    """Fast deckungsgleiche Schleifen verschiedener Gebiete (≤ TOL_SAME, z. B. unterschiedlich abgetastete
    Ober-/Unterkante desselben Lochs) auf die Punkte der früheren (höher priorisierten) Schleife setzen –
    sonst entstünden Splitter und unnötige Skizzen. Tags der späteren Schleife: (Gebiet, Schleife, None)."""
    seen = []           # (bbox, |Fläche|, pts, ccw, Gebiet)
    for ri, reg in enumerate(regs):
        if reg is None:
            continue
        for j, (P, T, k) in enumerate(reg):
            if len(P) > 1500:
                continue
            xs, ys = [p[0] for p in P], [p[1] for p in P]
            bb = (min(xs), min(ys), max(xs), max(ys))
            a = signed_area(P)
            hit = None
            for bb2, a2, P2, ccw2, r2 in seen:
                if r2 == ri or max(abs(x - y) for x, y in zip(bb, bb2)) > TOL_SAME:
                    continue
                if abs(abs(a) - a2) > max(0.005 * a2, 0.5):
                    continue
                if P2 == P or (_near_all(P, P2, TOL_SAME) and _near_all(P2, P, TOL_SAME)):
                    hit = (P2, ccw2)
                    break
            if hit is not None and hit[0] != P:
                P2 = list(hit[0]) if hit[1] == (a > 0) else hit[0][::-1]
                tg = T[0] if len(set(T)) == 1 else None
                reg[j] = (P2, [tg] * len(P2), k)
                continue
            seen.append((bb, abs(a), P, a > 0, ri))


class _PIdx:
    """Punktraster (für Verschweißen/tolerantes Schließen)."""

    def __init__(self, cell):
        self.cell = cell
        self.g = {}

    def key(self, p):
        return (int(math.floor(p[0] / self.cell)), int(math.floor(p[1] / self.cell)))

    def add(self, p, v=None):
        self.g.setdefault(self.key(p), []).append((p, p if v is None else v))

    def nearest(self, p, tol):
        i, j = self.key(p)
        best, bd = None, tol
        for di in (-1, 0, 1):
            for dj in (-1, 0, 1):
                for q, v in self.g.get((i + di, j + dj), ()):
                    d = math.hypot(q[0] - p[0], q[1] - p[1])
                    if d <= bd:
                        best, bd = v, d
        return best


def _proj(p, a, b):
    rx, ry = b[0] - a[0], b[1] - a[1]
    l2 = rx * rx + ry * ry
    if l2 < 1e-18:
        return a, 0.0
    t = ((p[0] - a[0]) * rx + (p[1] - a[1]) * ry) / l2
    return (a[0] + t * rx, a[1] + t * ry), t


def _weld(regs):
    """2.0.2 Rauschfestigkeit: Punkte späterer Gebiete auf Punkte (≤ SNAP) bzw. Kanten (≤ EDGE_SNAP) früherer
    ziehen und Punkte früherer Gebiete, die nahe an einer späteren Kante liegen, dort einfügen. Danach sind
    nahezu deckungsgleiche Kanten exakt deckungsgleich -> kein Splitter, kein offenes Ende."""
    cell = max(EDGE_SNAP * 4, 1.0)
    pidx = _PIdx(cell)
    sidx = _Index(cell)
    sl = []                                           # frühere Strecken
    for ri, reg in enumerate(regs):
        if reg is None:
            continue
        out = []
        for P, T, k in reg:
            P2 = []
            for p in P:
                w = pidx.nearest(p, SNAP)
                if w is None:
                    best, bd = None, EDGE_SNAP
                    for s in set(x for c in sidx.cells(p, p, EDGE_SNAP) for x in sidx.g.get(c, ())):
                        a, b = sl[s]
                        d = _dist_seg(p, a, b)
                        if d <= bd:
                            pr, t = _proj(p, a, b)
                            if 0.0 < t < 1.0:
                                best, bd = _q(pr), d
                    if best is None:              # Ecke ohne Kante dazwischen: nächster Punkt ≤ EDGE_SNAP
                        best = pidx.nearest(p, EDGE_SNAP)
                    w = best if best is not None else p
                P2.append(w)
            # frühere Punkte nahe einer eigenen Kante einfügen (Sehnenversatz bei unterschiedlicher Abtastung)
            P3, T3 = [], []
            n = len(P2)
            for i in range(n):
                a, b = P2[i], P2[(i + 1) % n]
                P3.append(a)
                T3.append(T[i])
                if a == b:
                    continue
                ins = []
                for c in sidx.cells(a, b, EDGE_SNAP):
                    for q, _v in pidx.g.get(c, ()):
                        if q in (a, b):
                            continue
                        pr, t = _proj(q, a, b)
                        L = math.hypot(b[0] - a[0], b[1] - a[1])
                        if 1e-9 < t < 1 - 1e-9 and t * L > SNAP and (1 - t) * L > SNAP and \
                                math.hypot(q[0] - pr[0], q[1] - pr[1]) <= EDGE_SNAP:
                            ins.append((t, q))
                for _t, q in sorted(set(ins)):
                    if q != P3[-1]:
                        P3.append(q)
                        T3.append(T[i])
            P4, T4 = _clean(P3, T3)
            P4, T4 = _despike(P4, T4)
            if len(P4) >= 3 and abs(signed_area(P4)) >= MIN_AREA * 0.01:
                out.append((P4, T4, k))
        regs[ri] = out or None
        if regs[ri] is None:
            continue
        for P, _T, _k in out:
            n = len(P)
            for i in range(n):
                pidx.add(P[i])
                sl.append((P[i], P[(i + 1) % n]))
                sidx.add(len(sl) - 1, P[i], P[(i + 1) % n])


def _despike(P, T):
    """Hin-und-zurück-Spitzen (a -> b -> a) entfernen."""
    changed = True
    while changed and len(P) >= 3:
        changed = False
        n = len(P)
        for i in range(n):
            if P[(i - 1) % n] == P[(i + 1) % n]:
                for j in sorted({i, (i + 1) % n}, reverse=True):
                    P.pop(j)
                    T.pop(j)
                changed = True
                break
    return P, T


def _drop_degenerate(regs):
    """2.0.2: Gebiete ohne echte Fläche entfernen – Außen- und Innenschleife deckungsgleich (z. B. Zylinder-/
    Langlochwand, oben und unten verschieden abgetastet, nach _unify auf dieselben Punkte gezogen) oder
    Nettofläche < MIN_AREA. Sonst löschen ihre gegenläufigen Kanten die echten Durchbruchkanten."""
    for ri, reg in enumerate(regs):
        if reg is None:
            continue
        P0 = reg[0][0]
        k0 = frozenset(P0)
        rest = [r for r in reg[1:] if frozenset(r[0]) != k0]
        if len(rest) < len(reg) - 1:
            regs[ri] = None
            continue
        net = abs(signed_area(P0)) - sum(abs(signed_area(r[0])) for r in reg[1:])
        if net < max(MIN_AREA, 1e-4 * abs(signed_area(P0))):
            regs[ri] = None


LAST_INFO = {}


def silhouette(regions, info=None):
    """regions = [[(pts, tags), …] je Fläche] (Priorität = Reihenfolge; Rohdaten, make_region wird angewandt).
    Rückgabe: Liste von Schalen {'outer': loop, 'holes': [loop]} (größte zuerst), loop = {'pts', 'tags', 'src'}
    (src = (Gebiet, Original-Schleifenindex), wenn die Schleife vollständig aus genau einer Eingangsschleife
    besteht, sonst None). Tags sind (Gebiet, Original-Schleifenindex, Tag der Eingangskante).
    2.0.2: Gebietsindex = Index in `regions` (auch wenn senkrechte Flächen davor wegfallen); Punkte werden
    verschweißt; offene Ketten werden tolerant (≤ CLOSE) geschlossen, sonst in info['open'] gemeldet."""
    info = {} if info is None else info
    info.update(open=[], closed_tol=0, dropped_small=0, bridged=0)
    info.pop('_open_raw', None)
    LAST_INFO.clear()
    regs = [make_region(r) for r in regions]           # None bleibt an seinem Platz -> Originalindex
    if all(r is None for r in regs):
        LAST_INFO.update(info)
        return []
    _unify(regs)
    _drop_degenerate(regs)
    _weld(regs)
    _drop_degenerate(regs)
    act = [ri for ri, r in enumerate(regs) if r is not None]
    if not act:
        LAST_INFO.update(info)
        return []
    segs = []           # (a, b, region, ring, tag)
    rb = {}             # bbox je Gebiet
    perim = {}          # (region, ring) -> Umfang
    for ri in act:
        reg = regs[ri]
        xs = [p[0] for P, _T, _k in reg for p in P]
        ys = [p[1] for P, _T, _k in reg for p in P]
        rb[ri] = (min(xs), min(ys), max(xs), max(ys))
        for P, T, k in reg:
            n = len(P)
            per = 0.0
            for i in range(n):
                a, b = P[i], P[(i + 1) % n]
                if a == b:
                    continue
                segs.append((a, b, ri, k, (ri, k, T[i])))
                per += math.hypot(b[0] - a[0], b[1] - a[1])
            perim[(ri, k)] = per
    W = max(v[2] for v in rb.values()) - min(v[0] for v in rb.values())
    H = max(v[3] for v in rb.values()) - min(v[1] for v in rb.values())
    cell = max(2.0, max(W, H) / 64.0)
    idx = _Index(cell)
    for s, (a, b, _r, _k, _t) in enumerate(segs):
        idx.add(s, a, b)
    # --- teilen
    splits = [[] for _ in segs]
    seen = set()
    for lst in idx.g.values():
        for x in range(len(lst)):
            s = lst[x]
            for y in range(x + 1, len(lst)):
                t = lst[y]
                if segs[s][2] == segs[t][2]:
                    continue
                key = (s, t) if s < t else (t, s)
                if key in seen:
                    continue
                seen.add(key)
                pa, pc = _inter(segs[s][0], segs[s][1], segs[t][0], segs[t][1])
                splits[s].extend(pa)
                splits[t].extend(pc)
    # --- Streifenindex je Gebiet für den Strahltest
    bands = {ri: {} for ri in act}
    for s, (a, b, r, _k, _t) in enumerate(segs):
        for j in range(int(math.floor(min(a[1], b[1]) / BAND)), int(math.floor(max(a[1], b[1]) / BAND)) + 1):
            bands[r].setdefault(j, []).append(s)

    def inside(p, r):
        bx = rb[r]
        if not (bx[0] - EPS_ON <= p[0] <= bx[2] + EPS_ON and bx[1] - EPS_ON <= p[1] <= bx[3] + EPS_ON):
            return False
        c = False
        for s in bands[r].get(int(math.floor(p[1] / BAND)), ()):
            a, b = segs[s][0], segs[s][1]
            if (a[1] > p[1]) != (b[1] > p[1]):
                x = a[0] + (p[1] - a[1]) * (b[0] - a[0]) / (b[1] - a[1])
                if x > p[0]:
                    c = not c
        return c

    kept = []
    for s, (a, b, r, k, tag) in enumerate(segs):
        pts = [a] + sorted(set(splits[s]) - {a, b},
                           key=lambda p: (p[0] - a[0]) * (b[0] - a[0]) + (p[1] - a[1]) * (b[1] - a[1])) + [b]
        for p, q in zip(pts, pts[1:]):
            if p == q:
                continue
            m = ((p[0] + q[0]) / 2.0, (p[1] + q[1]) / 2.0)
            dx, dy = q[0] - p[0], q[1] - p[1]
            ln = math.hypot(dx, dy)
            drop = False
            on = set()
            for t in idx.near(m):
                rt = segs[t][2]
                if rt == r or rt in on:
                    continue
                c0, c1 = segs[t][0], segs[t][1]
                if _dist_seg(m, c0, c1) <= TOL:
                    ex, ey = c1[0] - c0[0], c1[1] - c0[1]
                    le = math.hypot(ex, ey)
                    # parallel innerhalb TOL über die Teilstrecke (dieselbe Toleranz wie beim Teilen)
                    if le < 1e-12 or abs(_cross(dx, dy, ex, ey)) / le > max(2 * TOL, 0.02 * ln):
                        continue                           # berührt nur (quer) – kein Deckungsfall
                    on.add(rt)
                    if (dx * ex + dy * ey) < 0 or rt < r:  # Gegenrichtung: innen / gleich: früheres gewinnt
                        drop = True
                        break
            if drop:
                continue
            for r2 in act:
                if r2 == r or r2 in on:
                    continue
                if inside(m, r2):
                    drop = True
                    break
            if not drop:
                kept.append((p, q, tag))
    loops = _stitch(kept, info)
    if info['open']:                      # 2.0.3: Lücken entlang vorhandener Flächenschleifen schließen
        loops = _bridge(kept, regs, act, loops, info)
    info.pop('_open_raw', None)
    out = []
    for chain_pts, tags, chain_len in loops:
        a = signed_area(chain_pts)
        if abs(a) < MIN_AREA:
            info['dropped_small'] += 1
            continue
        srcs = set((t[0], t[1]) for t in tags)
        src = None
        if len(srcs) == 1:
            s0 = next(iter(srcs))
            if abs(chain_len - perim[s0]) <= max(0.01, 1e-4 * perim[s0]):
                src = s0
        out.append({'pts': chain_pts, 'tags': tags, 'src': src, 'area': a})
    outers = sorted([lp for lp in out if lp['area'] > 0], key=lambda lp: -lp['area'])
    shells = [{'outer': o, 'holes': []} for o in outers]
    for h in [lp for lp in out if lp['area'] < 0]:
        m = ((h['pts'][0][0] + h['pts'][1][0]) / 2.0, (h['pts'][0][1] + h['pts'][1][1]) / 2.0)
        host = None
        for sh in reversed(shells):                  # kleinste umschließende Außenkontur
            if point_in(m, sh['outer']['pts']):
                host = sh
                break
        if host is not None:
            host['holes'].append(h)
    LAST_INFO.update(info)
    return shells


def _stitch(kept, info):
    """Teilkanten zu Schleifen verbinden (Gebiet links; an Knoten die stärkste Linkskurve). Endet eine Kette
    ohne exakten Anschluss, wird der nächste freie Anfang ≤ CLOSE genommen (tolerant); bleibt sie offen,
    wird sie in info['open'] gemeldet (nie stillschweigend)."""
    out_of = {}
    starts = _PIdx(max(CLOSE * 8, 0.5))
    for e, (p, _q2, _t) in enumerate(kept):
        out_of.setdefault(p, []).append(e)
        starts.add(p, e)
    used = [False] * len(kept)
    loops = []

    def turn(din, a2, b2):
        dout = (b2[0] - a2[0], b2[1] - a2[1])
        return math.atan2(_cross(din[0], din[1], dout[0], dout[1]), din[0] * dout[0] + din[1] * dout[1])

    for e0 in range(len(kept)):
        if used[e0]:
            continue
        used[e0] = True
        chain = [e0]
        start = kept[e0][0]
        ok = False
        tol_used = False
        for _guard in range(len(kept) + 1):
            p, q, _t = kept[chain[-1]]
            din = (q[0] - p[0], q[1] - p[1])
            best, best_ang = None, None
            cands = [e for e in out_of.get(q, ()) if not used[e]]
            if q == start:
                cands.append(-1)
            for e in cands:
                a2, b2 = (kept[e][0], kept[e][1]) if e >= 0 else (kept[e0][0], kept[e0][1])
                ang = turn(din, a2, b2)
                if best_ang is None or ang > best_ang + 1e-12:
                    best, best_ang = e, ang
            if best is None:
                # tolerant: Schluss zum Anfang oder nächster freier Anfang in der Nähe
                if math.hypot(q[0] - start[0], q[1] - start[1]) <= CLOSE:
                    tol_used = True
                    ok = True
                    break
                cand = _near_free(starts, q, used)
                if cand is None:
                    break
                tol_used = True
                best = cand
            if best == -1:
                ok = True
                break
            used[best] = True
            chain.append(best)
        if not ok:
            pts = [kept[e][0] for e in chain] + [kept[chain[-1]][1]]
            info.setdefault('_open_raw', []).append((pts[0], pts[-1]))
            ln = sum(math.hypot(kept[e][1][0] - kept[e][0][0], kept[e][1][1] - kept[e][0][1]) for e in chain)
            info['open'].append({'start': [round(pts[0][0], 4), round(pts[0][1], 4)],
                                 'end': [round(pts[-1][0], 4), round(pts[-1][1], 4)],
                                 'segments': len(chain), 'length_mm': round(ln, 3),
                                 'gap_mm': round(math.hypot(pts[-1][0] - pts[0][0], pts[-1][1] - pts[0][1]), 4)})
            continue
        if tol_used:
            info['closed_tol'] += 1
        pts = [kept[e][0] for e in chain]
        tags = [kept[e][2] for e in chain]
        ln = sum(math.hypot(kept[e][1][0] - kept[e][0][0], kept[e][1][1] - kept[e][0][1]) for e in chain)
        loops.append((pts, tags, ln))
    return loops


def _locate(p, rings):
    """Lage eines Punkts auf den Flächenschleifen: [(Schleife, Kante i, t)] (Abstand ≤ BRIDGE_SNAP)."""
    out = []
    for ri, (P, _T, _tag) in enumerate(rings):
        n = len(P)
        best = None
        for i in range(n):
            a, b = P[i], P[(i + 1) % n]
            d = _dist_seg(p, a, b)
            if d <= BRIDGE_SNAP and (best is None or d < best[0]):
                _pr, t = _proj(p, a, b)
                best = (d, i, max(0.0, min(1.0, t)))
        if best is not None:
            out.append((ri, best[1], best[2]))
    return out


def _ring_path(P, i, ti, j, tj):
    """Weg vorwärts entlang der Schleife von (Kante i, t) bis (Kante j, t): Liste der Zwischen-Eckpunkte
    (Indizes) und Länge-Hilfswert. Gleiche Kante und tj ≥ ti -> direkt."""
    n = len(P)
    if i == j and tj >= ti:
        return []
    idx = []
    k = (i + 1) % n
    for _g in range(n + 1):
        idx.append(k)
        if k == j:
            break
        k = (k + 1) % n
    return idx


def _bridge(kept, regs, act, loops, info):
    """2.0.3: Offene Ketten über die Flächenschleifen schließen, auf denen ihre Enden liegen (typisch: eine
    Bogen-/Rundungskante, deren Kopien auf Ober- und Unterseite sich gegenseitig verdrängt haben). Nur kurze
    Wege (≤ max(BRIDGE_FACTOR × Lücke, Lücke + BRIDGE_ADD)), Richtung = Schleifenrichtung (Gebiet links).
    Ergebnis wird nur übernommen, wenn danach weniger Ketten offen sind."""
    raw = list(info.get('_open_raw') or [])
    if not raw:
        return loops
    rings = []
    for ri in act:
        for P, T, k in regs[ri]:
            rings.append((P, T, (ri, k)))
    cands = []
    ends = [(c, q, _locate(q, rings)) for c, (_s, q) in enumerate(raw)]
    starts = [(d, p, _locate(p, rings)) for d, (p, _e) in enumerate(raw)]
    for c, q, lq in ends:
        for d, p, lp in starts:
            gap = math.hypot(p[0] - q[0], p[1] - q[1])
            if gap > BRIDGE_GAP_MAX:
                continue
            limit = max(BRIDGE_FACTOR * gap, gap + BRIDGE_ADD)
            for rq, i, ti in lq:
                for rp, j, tj in lp:
                    if rq != rp:
                        continue
                    P, T, (ri, k) = rings[rq]
                    idx = _ring_path(P, i, ti, j, tj)
                    pts = [q] + [P[x] for x in idx] + [p]
                    tg = [(ri, k, T[i])] + [(ri, k, T[x]) for x in idx]
                    ln = sum(math.hypot(pts[m + 1][0] - pts[m][0], pts[m + 1][1] - pts[m][1])
                             for m in range(len(pts) - 1))
                    if ln <= limit:
                        cands.append((ln, c, d, pts, tg, gap))
    if not cands:
        info['bridge_why'] = 'kein kurzer Weg entlang einer Flächenschleife'
        return loops
    cands.sort(key=lambda x: x[0])
    used_c, used_d, add, desc = set(), set(), [], []
    for ln, c, d, pts, tg, gap in cands:
        if c in used_c or d in used_d:
            continue
        used_c.add(c)
        used_d.add(d)
        for m in range(len(pts) - 1):
            if pts[m] != pts[m + 1]:
                add.append((pts[m], pts[m + 1], tg[m]))
        if gap > CLOSE:
            desc.append('Lücke %.1f mm über %.1f mm Schleifenweg' % (gap, ln))
    info2 = {'open': [], 'closed_tol': 0, 'dropped_small': 0}
    loops2 = _stitch(kept + add, info2)
    if len(info2['open']) < len(info['open']):
        info['bridged'] = len(desc) or 1
        info['bridge_desc'] = desc
        info['open_before_bridge'] = info['open']
        info['open'] = info2['open']
        info['closed_tol'] += info2['closed_tol']
        return loops2
    info['bridge_why'] = 'Überbrückung ohne Erfolg (%s)' % '; '.join(desc)
    return loops


def _near_free(starts, q, used):
    i, j = starts.key(q)
    best, bd = None, CLOSE
    for di in (-1, 0, 1):
        for dj in (-1, 0, 1):
            for p, e in starts.g.get((i + di, j + dj), ()):
                if used[e]:
                    continue
                d = math.hypot(p[0] - q[0], p[1] - q[1])
                if d <= bd:
                    best, bd = e, d
    return best


def point_in(p, poly):
    c = False
    n = len(poly)
    for i in range(n):
        a, b = poly[i], poly[(i + 1) % n]
        if (a[1] > p[1]) != (b[1] > p[1]):
            x = a[0] + (p[1] - a[1]) * (b[0] - a[0]) / (b[1] - a[1])
            if x > p[0]:
                c = not c
    return c


def runs(loop):
    """Aufeinanderfolgende Kanten gleicher Herkunft -> [(tag, [punkte inkl. Endpunkt])], Start an einem
    Herkunftswechsel (damit kein Lauf über den Schleifenanfang geteilt wird)."""
    pts, tags = loop['pts'], loop['tags']
    n = len(pts)
    st = next((i for i in range(n) if tags[i] != tags[i - 1]), 0)
    out = []
    for j in range(n):
        i = (st + j) % n
        a, b = pts[i], pts[(i + 1) % n]
        if out and out[-1][0] == tags[i]:
            out[-1][1].append(b)
        else:
            out.append((tags[i], [a, b]))
    return out


# ---------------------------------------------------------------- 2.0.2 Schnellweg für gewöhnliche Platten
class _Poly:
    """Polygon mit Streifenindex: Punkt-im-Polygon und Abstand zum Rand in ~O(1) je Punkt."""

    def __init__(self, P, cell=None):
        self.P = P
        n = len(P)
        xs, ys = [p[0] for p in P], [p[1] for p in P]
        self.bb = (min(xs), min(ys), max(xs), max(ys))
        self.cell = cell or max(1.0, max(self.bb[2] - self.bb[0], self.bb[3] - self.bb[1]) / 128.0)
        self.idx = _Index(self.cell)
        self.bands = {}
        for i in range(n):
            a, b = P[i], P[(i + 1) % n]
            self.idx.add(i, a, b)
            for j in range(int(math.floor(min(a[1], b[1]) / self.cell)), int(math.floor(max(a[1], b[1]) / self.cell)) + 1):
                self.bands.setdefault(j, []).append(i)

    def dist(self, p, tol):
        """Abstand zum Rand, falls ≤ tol, sonst None."""
        P, n = self.P, len(self.P)
        best = None
        for c in self.idx.cells(p, p, tol):
            for i in self.idx.g.get(c, ()):
                d = _dist_seg(p, P[i], P[(i + 1) % n])
                if d <= tol and (best is None or d < best):
                    best = d
        return best

    def contains(self, p):
        b = self.bb
        if not (b[0] <= p[0] <= b[2] and b[1] <= p[1] <= b[3]):
            return False
        P, n = self.P, len(self.P)
        c = False
        for i in self.bands.get(int(math.floor(p[1] / self.cell)), ()):
            a, q = P[i], P[(i + 1) % n]
            if (a[1] > p[1]) != (q[1] > p[1]):
                x = a[0] + (p[1] - a[1]) * (q[0] - a[0]) / (q[1] - a[1])
                if x > p[0]:
                    c = not c
        return c


def _interior_point(P):
    """Ein Punkt sicher im Innern eines einfachen Polygons (Mitte der längsten waagerechten Innen-Sehne)."""
    ys = sorted(set(p[1] for p in P))
    best = None
    cands = [(ys[i] + ys[i + 1]) / 2.0 for i in range(len(ys) - 1)] or [ys[0]]
    if len(cands) > 40:
        cands = [cands[int(i * (len(cands) - 1) / 39.0)] for i in range(40)]
    n = len(P)
    for y in cands:
        xs = []
        for i in range(n):
            a, b = P[i], P[(i + 1) % n]
            if (a[1] > y) != (b[1] > y):
                xs.append(a[0] + (y - a[1]) * (b[0] - a[0]) / (b[1] - a[1]))
        xs.sort()
        for k in range(0, len(xs) - 1, 2):
            w = xs[k + 1] - xs[k]
            if best is None or w > best[0]:
                best = (w, ((xs[k] + xs[k + 1]) / 2.0, y))
    return best[1] if best else None


def fast_path(regions, order=None, tol=None):
    """Gewöhnliche Platte: umschließt die Außenschleife EINER (Unter-/Ober-)Fläche alle Projektionen aller
    Flächen (≤ tol mm), ist sie die Silhouette-Außenkontur – deren Kanten direkt. Durchbrüche = Innenschleifen
    dieser Fläche, deren Innenpunkt von keiner anderen Fläche überdeckt wird und in denen kein Punkt einer
    anderen Fläche liegt (sonst teilweise überdeckt -> volle Silhouette).
    regions wie silhouette(); order = zu prüfende Gebietsindizes (Kandidaten). Rückgabe dict oder None + Grund
    in dict['why'] (immer gesetzt)."""
    tol = FAST_TOL if tol is None else tol
    cand = list(order if order is not None else range(len(regions)))
    allpts = [(ri, k, P) for ri, r in enumerate(regions) for k, (P, _T) in enumerate(r)]
    why = []
    for ri in cand:
        rings = regions[ri]
        if not rings:
            continue
        ar = [abs(signed_area(P)) if len(P) >= 3 else 0.0 for P, _T in rings]
        ko = max(range(len(rings)), key=lambda k: ar[k])
        if ar[ko] < MIN_AREA:
            continue
        poly = _Poly(rings[ko][0])
        ok = True
        for rj, k, P in allpts:
            if rj == ri and k == ko:
                continue
            for p in P:
                if not poly.contains(p) and poly.dist(p, tol) is None:
                    ok = False
                    break
            if not ok:
                break
        if not ok:
            why.append('Gebiet %d: Projektionen ragen über die Außenschleife' % ri)
            continue
        holes = []
        for k, (P, _T) in enumerate(rings):
            if k == ko or ar[k] < MIN_AREA:
                continue
            hp = _Poly(P)
            ip = _interior_point(P)
            covered = False
            partial = False
            for rj, r in enumerate(regions):
                if rj == ri or not r:
                    continue
                rar = [abs(signed_area(Q)) if len(Q) >= 3 else 0.0 for Q, _T2 in r]
                kq = max(range(len(r)), key=lambda x: rar[x])
                if rar[kq] < MIN_AREA:
                    continue                      # senkrechte Fläche: überdeckt nichts
                for Q, _T2 in r:
                    for p in Q:
                        if hp.contains(p) and hp.dist(p, tol) is None:
                            partial = True
                            break
                    if partial:
                        break
                if partial:
                    break
                if ip is not None and point_in(ip, r[kq][0]) and \
                        not any(point_in(ip, Q) for x, (Q, _T2) in enumerate(r) if x != kq and rar[x] >= MIN_AREA):
                    covered = True
            if partial:
                ok = False
                why.append('Gebiet %d: Innenschleife %d teilweise überdeckt' % (ri, k))
                break
            if not covered:
                holes.append(k)
        if ok:
            return {'region': ri, 'outer': ko, 'holes': holes, 'why': why}
    return {'region': None, 'why': why or ['kein Kandidat']}
