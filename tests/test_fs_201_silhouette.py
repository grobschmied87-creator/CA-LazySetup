# -*- coding: utf-8 -*-
"""LazySetup 2.0.1: Kontur = SILHOUETTE (Draufsicht). Synthetische Teile: Falz, Fase, Überstand, Sackloch oben/
unten, Durchgangsloch, Senkung, Stufenbohrung, Nut, Falz beidseitig (zusammengesetzt -> Skizze)."""
import math
import os
import shutil
import tempfile
import unittest

import fsfake as FK       # noqa: E402
import fs_testdata as TD  # noqa: E402
import fs_log as L        # noqa: E402
import fs_geom as G       # noqa: E402
import fs_fusion as F     # noqa: E402
import fs_cam as C        # noqa: E402
import fs_run as R        # noqa: E402
import fs_silhouette as S  # noqa: E402

HOLES_SHEET = os.path.join(TD.ROOT, 'cn_logs3', 'apply_20261009_102512_483.json')
TOOL = {'tool': FK.Tool(3, 8.0, 'Spiralfräser 8'), 'info': {'d_mm': 8.0}, 'label': 'T3 Ø 8'}
T = 15.0


class Curved:
    """Gekrümmte Fläche (Zylinder/Kegel/Rundung): keine Ebenen-Normale, nur Schleifen."""
    def __init__(self, loops):
        self.geometry = type('G', (), {'surfaceType': 1})()
        self.loops = FK.Coll(loops)
        self.area = 1.0


def L3(pts, outer=True, off=(0, 0, 0)):
    ces = []
    n = len(pts)
    for k in range(n):
        a = tuple(off[i] + pts[k][i] / 10.0 for i in range(3))
        b = tuple(off[i] + pts[(k + 1) % n][i] / 10.0 for i in range(3))
        ces.append(FK.CoEdge(FK.Edge(a, b), False))
    return FK.Loop(ces, outer)


def rect(x0, y0, x1, y1, z):
    return [(x0, y0, z), (x1, y0, z), (x1, y1, z), (x0, y1, z)]


def circ(cx, cy, r, z, n=32):
    return [(cx + r * math.cos(2 * math.pi * i / n), cy + r * math.sin(2 * math.pi * i / n), z) for i in range(n)]


def plane(nz, loops, off=(0, 0, 0)):
    p0 = loops[0][0][0]
    lps = [L3(p, o, off) for p, o in loops]
    return FK.Face((0, 0, nz), (off[0] + p0[0] / 10, off[1] + p0[1] / 10, off[2] + p0[2] / 10), lps, 1.0)


def side(pts, n=(1, 0, 0), off=(0, 0, 0)):
    """Ebene Seitenfläche/Fase mit beliebiger Normale (keine Z-Normale)."""
    p0 = pts[0]
    return FK.Face(n, (off[0] + p0[0] / 10, off[1] + p0[1] / 10, off[2] + p0[2] / 10), [L3(pts, True, off)], 1.0)


def walls(x0, y0, x1, y1, z0, z1, off=(0, 0, 0)):
    return [side([(x0, y0, z0), (x1, y0, z0), (x1, y0, z1), (x0, y0, z1)], (0, -1, 0), off),
            side([(x1, y0, z0), (x1, y1, z0), (x1, y1, z1), (x1, y0, z1)], (1, 0, 0), off),
            side([(x1, y1, z0), (x0, y1, z0), (x0, y1, z1), (x1, y1, z1)], (0, 1, 0), off),
            side([(x0, y1, z0), (x0, y0, z0), (x0, y0, z1), (x0, y1, z1)], (-1, 0, 0), off)]


def cyl(cx, cy, r, z0, z1, off=(0, 0, 0)):
    return Curved([L3(circ(cx, cy, r, z0), True, off), L3(circ(cx, cy, r, z1), False, off)])


def body(faces):
    b = type('Body', (), {})()
    b.faces = FK.Coll(faces)
    b.isSolid = True
    b.name = 'Körper1'
    return b


W, H = 400.0, 300.0
FULL = W * H
HOLE = (150.0, 150.0)


def make(kind, off=(0, 0, 0)):
    o = off
    f = []
    if kind == 'falz':                     # Falz oben links 20 × 7
        f += [plane(-1, [(rect(0, 0, W, H, 0), True)], o), plane(1, [(rect(20, 0, W, H, T), True)], o),
              plane(1, [(rect(0, 0, 20, H, 8), True)], o), side(rect(20, 0, 20, H, 8), (-1, 0, 0), o)]
        f += walls(0, 0, W, H, 0, T, o)
    elif kind == 'fase':                   # Fase 3 mm an der Oberkante
        f += [plane(-1, [(rect(0, 0, W, H, 0), True)], o), plane(1, [(rect(3, 3, W - 3, H - 3, T), True)], o)]
        f += [side([(0, 0, 12), (W, 0, 12), (W - 3, 3, T), (3, 3, T)], (0, -0.7, 0.7), o),
              side([(W, 0, 12), (W, H, 12), (W - 3, H - 3, T), (W - 3, 3, T)], (0.7, 0, 0.7), o),
              side([(W, H, 12), (0, H, 12), (3, H - 3, T), (W - 3, H - 3, T)], (0, 0.7, 0.7), o),
              side([(0, H, 12), (0, 0, 12), (3, 3, T), (3, H - 3, T)], (-0.7, 0, 0.7), o)]
        f += walls(0, 0, W, H, 0, 12, o)
    elif kind == 'ueberstand':             # Deckel 10 mm größer als der Sockel
        f += [plane(-1, [(rect(10, 10, W - 10, H - 10, 0), True)], o),
              plane(-1, [(rect(0, 0, W, H, 10), True), (rect(10, 10, W - 10, H - 10, 10), False)], o),
              plane(1, [(rect(0, 0, W, H, T), True)], o)]
        f += walls(10, 10, W - 10, H - 10, 0, 10, o) + walls(0, 0, W, H, 10, T, o)
    elif kind in ('sack_oben', 'sack_unten', 'durch', 'senkung', 'stufe'):
        cx, cy = HOLE
        bot_h = kind in ('sack_unten', 'durch', 'senkung', 'stufe')
        top_h = kind in ('sack_oben', 'durch', 'senkung', 'stufe')
        rt = 8.0 if kind in ('senkung', 'stufe') else 5.0
        f.append(plane(-1, [(rect(0, 0, W, H, 0), True)] + ([(circ(cx, cy, 5, 0), False)] if bot_h else []), o))
        f.append(plane(1, [(rect(0, 0, W, H, T), True)] + ([(circ(cx, cy, rt, T), False)] if top_h else []), o))
        if kind == 'sack_oben':
            f += [plane(1, [(circ(cx, cy, 5, 4), True)], o), cyl(cx, cy, 5, 4, T, o)]
        elif kind == 'sack_unten':
            f += [plane(-1, [(circ(cx, cy, 5, 11), True)], o), cyl(cx, cy, 5, 0, 11, o)]
        elif kind == 'durch':
            f.append(cyl(cx, cy, 5, 0, T, o))
        elif kind == 'senkung':
            f += [cyl(cx, cy, 5, 0, 12, o), Curved([L3(circ(cx, cy, 8, T), True, o), L3(circ(cx, cy, 5, 12), False, o)])]
        else:
            f += [cyl(cx, cy, 5, 0, 8, o), cyl(cx, cy, 8, 8, T, o),
                  plane(1, [(circ(cx, cy, 8, 8), True), (circ(cx, cy, 5, 8), False)], o)]
        f += walls(0, 0, W, H, 0, T, o)
    elif kind == 'nut':                    # Nut quer über die Oberseite, 20 breit, 6 tief
        f += [plane(-1, [(rect(0, 0, W, H, 0), True)], o), plane(1, [(rect(0, 0, 190, H, T), True)], o),
              plane(1, [(rect(210, 0, W, H, T), True)], o), plane(1, [(rect(190, 0, 210, H, 9), True)], o),
              side(rect(190, 0, 190, H, 9), (1, 0, 0), o), side(rect(210, 0, 210, H, 9), (-1, 0, 0), o)]
        f += walls(0, 0, W, H, 0, T, o)
    elif kind == 'falz2':                  # Falz oben links + Falz unten rechts: kein Einzelflächen-Umriss
        f += [plane(1, [(rect(20, 0, W, H, T), True)], o), plane(-1, [(rect(0, 0, W - 20, H, 0), True)], o),
              plane(1, [(rect(0, 0, 20, H, 8), True)], o), plane(-1, [(rect(W - 20, 0, W, H, 7), True)], o)]
        f += walls(0, 0, W, H, 0, T, o)
    return body(f)


EXPECT = {  # Art: (Fläche außen, Anzahl Durchbrüche, Methode außen)
    'falz': (FULL, 0, 'kante'), 'fase': (FULL, 0, 'kante'), 'ueberstand': (FULL, 0, 'kante'),
    'sack_oben': (FULL, 0, 'kante'), 'sack_unten': (FULL, 0, 'kante'), 'durch': (FULL, 1, 'kante'),
    'senkung': (FULL, 1, 'kante'), 'stufe': (FULL, 1, 'kante'), 'nut': (FULL, 0, 'kante'),
    'falz2': (FULL, 0, 'skizze')}


def geo(kind):
    occ = FK.Occ('Teil:1')
    occ.bRepBodies.append(make(kind))
    why = []
    return F.part_geometry(occ, F.Frame(None), None, None, why), why


class Synthetic(unittest.TestCase):
    def test_all_kinds(self):
        r5 = G.area([(p[0], p[1]) for p in circ(0, 0, 5, 0)])
        for kind, (ar, nh, meth) in EXPECT.items():
            with self.subTest(kind=kind):
                g, why = geo(kind)
                self.assertIsNotNone(g, why)
                self.assertAlmostEqual(abs(G.area(g['outer']['pts'])), ar, 1)
                self.assertEqual(G.bbox(g['outer']['pts']), (0.0, 0.0, W, H))
                self.assertEqual(len(g['holes']), nh, kind)
                self.assertEqual(g['outer']['method'], meth)
                for h in g['holes']:              # Durchbruch = engste Stelle (Ø 10), nie die Senkung/Stufe
                    self.assertAlmostEqual(abs(G.area(h['pts'])), r5, 1)
                    self.assertEqual(h['method'], 'kante')
                    self.assertTrue(h['edges'])
                if meth == 'kante':
                    self.assertTrue(g['outer']['edges'])
                self.assertEqual(g['side'], 'Silhouette')

    def test_blind_bore_top_is_pocket_option_only(self):
        g, _w = geo('sack_oben')
        self.assertEqual(g['holes'], [])
        self.assertEqual(len(g['pockets']), 1)      # bleibt für die Option „Taschen“ verfügbar
        self.assertAlmostEqual(g['pockets'][0]['depth'], 11.0, 6)

    def test_through_hole_uses_bottom_edges(self):
        g, _w = geo('durch')
        occ = FK.Occ('Teil:1')
        b = make('durch')
        occ.bRepBodies.append(b)
        g = F.part_geometry(occ, F.Frame(None), None, None, [])
        bottom_edges = set(id(ce.edge) for lp in b.faces[0].loops for ce in lp.coEdges)
        self.assertTrue(all(id(e) in bottom_edges for e in g['holes'][0]['edges']))
        self.assertTrue(all(id(e) in bottom_edges for e in g['outer']['edges']))

    def test_composed_runs(self):
        g, _w = geo('falz2')
        rs = g['outer']['runs']
        pts = [p for r in rs for p in r['pts'][:-1]]
        self.assertEqual(sorted(set(pts)), [(0.0, 0.0), (0.0, H), (W, 0.0), (W, H)])
        self.assertAlmostEqual(G.signed_area(g['outer']['pts']), FULL, 3)

    def test_union_primitives(self):
        sq = lambda x0, y0, x1, y1: [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
        ring = lambda p, t: (p, [t] * len(p))
        # zwei überlappende Quadrate -> ein Umriss (L-förmig), Fläche = Summe − Überlappung
        sh = S.silhouette([[ring(sq(0, 0, 10, 10), 'a')], [ring(sq(5, 5, 15, 15), 'b')]])
        self.assertEqual(len(sh), 1)
        self.assertAlmostEqual(S.signed_area(sh[0]['outer']['pts']), 175.0, 6)
        # getrennte Teile -> zwei Schalen
        sh = S.silhouette([[ring(sq(0, 0, 10, 10), 'a')], [ring(sq(20, 0, 30, 10), 'b')]])
        self.assertEqual(len(sh), 2)
        # senkrechte Fläche (Fläche 0) wird ignoriert
        self.assertIsNone(S.make_region([ring([(0, 0), (10, 0), (10, 0), (0, 0)], 'w')]))


class Pipeline(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        L.LOG_DIR = self.tmp
        L.LOG_FILE = os.path.join(self.tmp, 'lazysetup.log')
        self.sheets = TD.sheets_from(HOLES_SHEET)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def log(self):
        with open(L.LOG_FILE, encoding='utf-8-sig') as f:
            return f.read()

    def _swap(self, d, k, kind, shift=None):
        """Körper des k-ten Teils durch ein Synthetik-Teil an seiner Stelle ersetzen."""
        so = d.rootComponent.occurrences[0]
        po = so.childOccurrences[k]
        cx, cy = G.centroid(G.orient(self.sheets[0]['parts'][k]['outer']))
        x0, y0 = shift or (cx - W / 2, cy - H / 2)                       # mittig auf das Original-Teil
        base = (300.0 + x0 / 10.0, 50.0 + y0 / 10.0, 0.0)
        po.bRepBodies[:] = [make(kind, base)]
        po.boundingBox = None
        return po

    def test_sketch_chain_regenerated(self):
        d = FK.build_design(self.sheets, project=True)
        po = self._swap(d, 0, 'falz2')
        cam = FK.CAM(d)
        s = FK.linked_setup(cam, 1)
        warn = []
        sh = R.collect(d, cam, None, warn)[0]
        p0 = next(p for p in sh['parts'] if p['occ'] is po)
        self.assertEqual(p0['geo']['outer']['method'], 'skizze')
        self.assertAlmostEqual(abs(G.area(p0['outer'])), FULL, 3)          # Vorschau = Silhouette
        self.assertEqual(p0['outer'], G.clean(p0['geo']['outer']['pts']))
        self.assertTrue(any('Silhouette weicht von der LazyNest-Kontur ab' in w for w in warn), warn)
        for _run in range(2):                                               # 2. Lauf: Skizze neu, nicht doppelt
            res = R.run(FK.App(d, cam), None, d, {}, None, TOOL, '2.0.1')
            self.assertEqual(res['errors'], 0, res)
            comp = d.rootComponent.occurrences[0].component
            sks = [k for k in comp.sketches if k.name.startswith(C.SK_SIL)]
            self.assertEqual(len(sks), 1, [k.name for k in comp.sketches])
            self.assertFalse(sks[0].isVisible)
            self.assertTrue(sks[0].name.endswith(po.name.split(':')[0]) or C.SK_SIL in sks[0].name)
            curves = [ch for op in s.operations for ch in op.parameters.itemByName('contours').value.applied
                      if any(isinstance(e, FK.SketchCurve) for e in ch.inputGeometry)]
            self.assertEqual(len(curves), 1)
            self.assertTrue(all(getattr(e, 'assemblyContext', None) is not None for e in curves[0].inputGeometry))
        self.assertIn('Silhouette als Skizze', self.log())
        self.assertIn('Silhouette (Außen Skizze', self.log())

    def test_stale_sketch_removed(self):
        d = FK.build_design(self.sheets, project=True)
        self._swap(d, 0, 'falz2')
        cam = FK.CAM(d)
        FK.linked_setup(cam, 1)
        R.run(FK.App(d, cam), None, d, {}, None, TOOL, '2.0.1')
        comp = d.rootComponent.occurrences[0].component
        self.assertEqual(len([k for k in comp.sketches if k.name.startswith(C.SK_SIL)]), 1)
        self._swap(d, 0, 'durch')                       # Teil geändert -> Silhouette wieder eine B-Rep-Schleife
        R.run(FK.App(d, cam), None, d, {}, None, TOOL, '2.0.1')
        self.assertEqual([k.name for k in comp.sketches if k.name.startswith(C.SK_SIL)], [])

    def test_blind_holes_never_cut_through(self):
        d = FK.build_design(self.sheets, project=True)
        po = self._swap(d, 0, 'sack_oben')
        cam = FK.CAM(d)
        s = FK.linked_setup(cam, 1)
        R.run(FK.App(d, cam), None, d, {}, None, TOOL, '2.0.1')
        b = po.bRepBodies[0]
        blind = set(id(ce.edge) for lp in b.faces[1].loops if not lp.isOuter for ce in lp.coEdges)
        blind |= set(id(ce.edge) for f in b.faces[2:4] for lp in f.loops for ce in lp.coEdges)
        self.assertTrue(blind)
        used = [id(e) for op in s.operations for ch in op.parameters.itemByName('contours').value.applied
                for e in ch.inputGeometry]
        self.assertTrue(used)
        self.assertFalse(blind & set(used))

if __name__ == '__main__':
    unittest.main()
