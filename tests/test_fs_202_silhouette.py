# -*- coding: utf-8 -*-
"""LazySetup 2.0.2: Silhouette robust (Originalindizes, Rauschen 0,002–0,02 mm, tolerantes Schließen, offene
Enden gemeldet), Schnellweg für gewöhnliche Platten, nie stillschweigend verworfen (Projekt-Ersatz), Bögen über
Mittelpunkt/Winkel mit Prüfung, Auswahl zurücklesen, Diagnose, Neuberechnung nur bei geänderter Zeitachse,
Planungs-Merker, Geometrie-Cache. Screenshot-Fälle: L-Teil mit Fase + kleinem Eckradius; Teil mit 4 Langlöchern."""
import json
import math
import random
import unittest
import zlib

import fsfake as FK       # noqa: E402
import fs_geom as G       # noqa: E402
import fs_fusion as F     # noqa: E402
import fs_cam as C        # noqa: E402
import fs_run as R        # noqa: E402
import fs_silhouette as S  # noqa: E402
import test_fs_201_silhouette as T1   # noqa: E402
from adsk import core     # noqa: E402

T = 15.0


# ---------------------------------------------------------------- Bausteine mit echten Bögen
class ArcEval:
    def __init__(self, c, r, a0, a1, z, n):
        self.c, self.r, self.a0, self.a1, self.z, self.n = c, r, a0, a1, z, n

    def getParameterExtents(self):
        return True, 0.0, 1.0

    def getStrokes(self, p0, p1, tol):
        out = []
        for i in range(self.n + 1):
            t = self.a0 + (self.a1 - self.a0) * i / self.n
            out.append(core.Point3D.create((self.c[0] + self.r * math.cos(t)) / 10.0,
                                           (self.c[1] + self.r * math.sin(t)) / 10.0, self.z / 10.0))
        return True, out


class ArcEdge(FK.Edge):
    def __init__(self, c, r, a0, a1, z, n=16):
        super().__init__((0, 0, 0), (0, 0, 0))
        self.evaluator = ArcEval(c, r, a0, a1, z, n)
        self.geometry = type('Arc3D', (), {'objectType': 'adsk::core::Arc3D',
                                            'center': core.Point3D.create(c[0] / 10.0, c[1] / 10.0, z / 10.0),
                                            'radius': r / 10.0, 'normal': (0, 0, 1)})()


class LineEdge(FK.Edge):
    def __init__(self, a, b):
        super().__init__(a, b)
        self.geometry = type('Line3D', (), {'objectType': 'adsk::core::Line3D'})()


def path_loop(items, z, outer=True, n_arc=16):
    """items: ('L', (x, y)) Punkt / ('A', (cx, cy), r, a0_deg, a1_deg) Bogen (mm). Linien verbinden die Folge."""
    ces = []
    pts = []
    for it in items:
        if it[0] == 'L':
            pts.append(('p', it[1]))
        else:
            pts.append(('a', it))
    # Folge in Kanten: Punkt -> nächster Anfang
    def start(e):
        if e[0] == 'p':
            return e[1]
        _k, c, r, a0, _a1 = e[1]
        return (c[0] + r * math.cos(math.radians(a0)), c[1] + r * math.sin(math.radians(a0)))

    def end(e):
        if e[0] == 'p':
            return e[1]
        _k, c, r, _a0, a1 = e[1]
        return (c[0] + r * math.cos(math.radians(a1)), c[1] + r * math.sin(math.radians(a1)))
    n = len(pts)
    for i in range(n):
        e = pts[i]
        if e[0] == 'a':
            _k, c, r, a0, a1 = e[1]
            ces.append(FK.CoEdge(ArcEdge(c, r, math.radians(a0), math.radians(a1), z, n_arc), False))
        a, b = end(e), start(pts[(i + 1) % n])
        if math.dist(a, b) > 1e-9:
            ces.append(FK.CoEdge(LineEdge((a[0] / 10, a[1] / 10, z / 10), (b[0] / 10, b[1] / 10, z / 10)), False))
    return FK.Loop(ces, outer)


def pface(nz, loops, z):
    return FK.Face((0, 0, nz), (0, 0, z / 10.0), loops, 1.0)


def L_items(x_right=300.0, x_left=0.0, R=2.0):
    return [('L', (x_left, 0)), ('L', (x_right, 0)), ('L', (x_right, 100)),
            ('A', (100 + R, 100 + R), R, -90, -180), ('L', (100, 250)), ('L', (x_left, 250))]


L_AREA = 300 * 100 + 100 * 150 + (2.0 * 2.0 - math.pi * 2.0 * 2.0 / 4)   # Kehle R2 füllt die Innenecke


def l_part(walls_first=True):
    """Screenshot (a): L-Teil, kleine Innenecke R2, Fase unten links (3 mm), Falz oben rechts (10 mm):
    weder Ober- noch Unterseite umschließt alles -> zusammengesetzte Silhouette mit Bogen."""
    top = pface(1, [path_loop(L_items(x_right=290.0), T)], T)
    step = pface(1, [path_loop([('L', (290, 0)), ('L', (300, 0)), ('L', (300, 100)), ('L', (290, 100))], 8)], 8)
    bot = pface(-1, [path_loop(L_items(x_left=3.0), 0)], 0)
    fase = T1.side([(3, 0, 0), (3, 250, 0), (0, 250, 3), (0, 0, 3)], (-0.7, 0, -0.7))
    walls = T1.walls(0, 0, 300, 250, 3, T)                # vereinfachte senkrechte Wände (ohne Fläche)
    faces = (walls + [fase, top, step, bot]) if walls_first else [top, step, bot, fase] + walls
    return T1.body(faces)


def slot_items(cx, cy, ln=60.0, r=5.0):
    """Langloch (CW als Innenschleife): Gerade + Halbkreis + Gerade + Halbkreis."""
    h = ln / 2.0 - r
    return [('A', (cx + h, cy), r, 90, -90), ('L', (cx - h, cy - r)), ('A', (cx - h, cy), r, 270, 90),
            ('L', (cx + h, cy + r))]


SLOTS = [(80, 80), (320, 80), (80, 220), (320, 220)]


def slot_part(n_bot=16, n_top=11):
    """Screenshot (b): Platte 400 × 300 mit 4 Langlöchern; Ober- und Unterkante unterschiedlich abgetastet."""
    rect = [('L', (0, 0)), ('L', (400, 0)), ('L', (400, 300)), ('L', (0, 300))]
    bot = pface(-1, [path_loop(rect, 0)] + [path_loop(slot_items(*c), 0, False, n_bot) for c in SLOTS], 0)
    top = pface(1, [path_loop(rect, T)] + [path_loop(slot_items(*c), T, False, n_top) for c in SLOTS], T)
    curved = [T1.Curved([path_loop(slot_items(*c), 0, True, n_bot), path_loop(slot_items(*c), T, False, n_top)])
              for c in SLOTS]
    return T1.body(curved + [bot, top] + T1.walls(0, 0, 400, 300, 0, T))


SLOT_AREA = 60 * 10 - (10 * 10 - math.pi * 25)


def geo_of(b, expect=None):
    occ = FK.Occ('Teil:1')
    occ.bRepBodies.append(b)
    why = []
    return F.part_geometry(occ, F.Frame(None), None, expect, why), why


class Noise:
    """F.loop_points mit Rauschen ±amp mm (deterministisch je Aufruf)."""
    def __init__(self, amp, seed=1):
        self.amp, self.rnd = amp, random.Random(seed)

    def __enter__(self):
        self.orig = F.loop_points

        def lp(loop, frame, seg_edge=None, einfo=None):
            pts, edges, opp = self.orig(loop, frame, seg_edge, einfo)
            a = self.amp
            return [(p[0] + self.rnd.uniform(-a, a), p[1] + self.rnd.uniform(-a, a), p[2]) for p in pts], edges, opp
        F.loop_points = lp
        return self

    def __exit__(self, *a):
        F.loop_points = self.orig


# ---------------------------------------------------------------- Tests
class IndexAndNoise(unittest.TestCase):
    def test_original_region_index(self):
        sq = [(0, 0), (10, 0), (10, 10), (0, 10)]
        flat = [(0, 0), (10, 0), (10, 0), (0, 0)]          # senkrechte Fläche: keine Projektion
        sh = S.silhouette([[(flat, ['w'] * 4)], [(sq, ['a'] * 4)]])
        self.assertEqual(sh[0]['outer']['src'], (1, 0))
        self.assertEqual(set(t[0] for t in sh[0]['outer']['tags']), {1})

    def test_walls_before_chamfer_and_fillet(self):
        for wf in (True, False):
            with self.subTest(walls_first=wf):
                g, why = geo_of(l_part(wf))
                self.assertIsNotNone(g, why)
                self.assertEqual(g['path'], 'silhouette')
                self.assertAlmostEqual(abs(G.area(g['outer']['pts'])), L_AREA, 1)
                self.assertEqual(G.bbox(g['outer']['pts']), (0.0, 0.0, 300.0, 250.0))
                arcs = [r for r in g['outer'].get('runs') or [] if r['kind'] == 'arc']
                self.assertEqual(len(arcs), 1, why)
                self.assertAlmostEqual(arcs[0]['arc']['r'], 2.0, 6)
                self.assertEqual(g['sil_open'], 0)

    def test_noise_all_kinds(self):
        for amp in (0.002, 0.005, 0.01, 0.02):
            for kind, (ar, nh, _m) in T1.EXPECT.items():
                with self.subTest(amp=amp, kind=kind), Noise(amp, seed=zlib.crc32(("%s%s" % (amp, kind)).encode())):
                    g, why = T1.geo(kind)
                    self.assertIsNotNone(g, why)
                    self.assertLess(abs(abs(G.area(g['outer']['pts'])) - ar) / ar, 0.001, why)
                    self.assertEqual(len(g['holes']), nh, (kind, amp, why))
                    self.assertEqual(g['sil_open'], 0, why)
                    bb = G.bbox(g['outer']['pts'])
                    self.assertLess(max(abs(a - b) for a, b in zip(bb, (0, 0, T1.W, T1.H))), 0.05)

    def test_noise_full_silhouette_path(self):
        """Ohne Schnellweg (erzwungen): auch die volle Silhouette hält Rauschen bis 0,02 mm aus."""
        orig = S.fast_path
        S.fast_path = lambda regs, order=None, tol=0.05: {'region': None, 'why': ['Test']}
        try:
            for amp in (0.002, 0.01, 0.02):
                for kind in ('durch', 'stufe', 'senkung', 'fase', 'ueberstand'):
                    with self.subTest(amp=amp, kind=kind), Noise(amp, 7):
                        g, why = T1.geo(kind)
                        self.assertIsNotNone(g, why)
                        self.assertEqual(len(g['holes']), T1.EXPECT[kind][1], (kind, amp, why))
                        self.assertLess(abs(abs(G.area(g['outer']['pts'])) - T1.FULL) / T1.FULL, 0.001)
                        self.assertEqual(g['sil_open'], 0, why)
                with self.subTest(amp=amp, kind='slots'), Noise(amp, 3):
                    g, why = geo_of(slot_part())
                    self.assertEqual(len(g['holes']), 4, why)
                    self.assertEqual(g['sil_open'], 0, why)
        finally:
            S.fast_path = orig

    def test_open_chain_reported_not_silent(self):
        info = {'open': [], 'closed_tol': 0}
        kept = [((0, 0), (10, 0), 'a'), ((10, 0), (10, 10), 'a'), ((10, 10), (0, 10), 'a'),
                ((0, 10), (0, 0.015), 'a')]                      # Lücke 0,015 mm -> tolerant geschlossen
        loops = S._stitch(kept, info)
        self.assertEqual(len(loops), 1)
        self.assertEqual(info['closed_tol'], 1)
        info = {'open': [], 'closed_tol': 0}
        loops = S._stitch(kept[:3], info)                        # echte Lücke -> gemeldet
        self.assertEqual(loops, [])
        self.assertEqual(len(info['open']), 1)
        self.assertAlmostEqual(info['open'][0]['gap_mm'], 10.0, 3)


class ScreenshotCases(unittest.TestCase):
    def test_slots_kept_fast_path(self):
        for amp in (0.0, 0.01, 0.02):
            with self.subTest(amp=amp), Noise(amp, 11):
                g, why = geo_of(slot_part())
                self.assertIsNotNone(g, why)
                self.assertEqual(g['path'], 'schnell', why)
                self.assertEqual(len(g['holes']), 4, why)
                for h in g['holes']:
                    self.assertEqual(h['method'], 'kante')
                    self.assertAlmostEqual(abs(G.area(h['pts'])), SLOT_AREA, delta=2.0)
                self.assertEqual(g['outer']['method'], 'kante')

    def test_l_part_sketch_arc_small_and_inside(self):
        """Kein Riesenbogen: Skizzenbogen R2 über Mittelpunkt/Winkel, alle Kurven in der Teil-Hüllbox."""
        g, why = geo_of(l_part())
        sk = FK.Sketch(None, None)
        lp = dict(g['outer'])
        cs = C._draw_loop(sk, lp, 0.0)
        self.assertFalse(lp.get('warn'), lp.get('warn'))
        arcs = [c for c in cs if c.kind == 'arc']
        self.assertEqual(len(arcs), 1)
        self.assertAlmostEqual(arcs[0].radius, 0.2, 6)               # cm
        self.assertAlmostEqual(abs(arcs[0].sweep), math.pi / 2, 6)
        for c in cs:
            for sp in (c.startSketchPoint.geometry, c.endSketchPoint.geometry):
                self.assertTrue(-1e-6 <= sp.x <= 30.0 + 1e-6 and -1e-6 <= sp.y <= 25.0 + 1e-6)
        # geschlossen: Ende jeder Kurve = Anfang einer anderen
        ends = [(round(p.x, 5), round(p.y, 5)) for c in cs for p in (c.startSketchPoint.geometry,
                                                                     c.endSketchPoint.geometry)]
        self.assertTrue(all(ends.count(e) % 2 == 0 for e in ends))

    def test_bad_arc_replaced_by_polyline_with_warning(self):
        g, _w = geo_of(l_part())
        FK._Arcs.BUG['radius_factor'] = 1.5
        try:
            sk = FK.Sketch(None, None)
            lp = dict(g['outer'])
            cs = C._draw_loop(sk, lp, 0.0)
        finally:
            FK._Arcs.BUG['radius_factor'] = 1.0
        self.assertEqual([c for c in cs if c.kind == 'arc'], [])
        self.assertTrue(any('Bogen R 2.00 mm verworfen' in w for w in lp.get('warn', [])))
        self.assertEqual(len(sk.sketchCurves.sketchArcs), 0)

    def test_full_circle_hole_via_sketch(self):
        lp = {'runs': [{'kind': 'arc', 'arc': {'c': (50.0, 50.0), 'r': 5.0},
                        'pts': [(50 + 5 * math.cos(-2 * math.pi * i / 32), 50 + 5 * math.sin(-2 * math.pi * i / 32))
                                for i in range(33)]}]}
        sk = FK.Sketch(None, None)
        cs = C._draw_loop(sk, lp, 0.0)
        self.assertEqual(len(cs), 2)
        self.assertAlmostEqual(sum(c.length for c in cs), 2 * math.pi * 0.5, 6)


class Paths(unittest.TestCase):
    def test_fast_path_ordinary_and_overhang(self):
        for kind in ('durch', 'fase', 'falz', 'ueberstand', 'stufe', 'sack_oben', 'nut'):
            with self.subTest(kind=kind):
                g, why = T1.geo(kind)
                self.assertEqual(g['path'], 'schnell', why)
        g, why = T1.geo('falz2')
        self.assertEqual(g['path'], 'silhouette')

    def test_whole_edges_preferred_over_sketch(self):
        """Zusammengesetzte Schleife aus ganzen Kanten EINER Höhe -> Kanten statt Skizze."""
        # zwei Unterseiten-Flächen gleicher Höhe nebeneinander (geteilte Fläche), Oberseite kleiner (Fase)
        a = T1.plane(-1, [(T1.rect(0, 0, 200, 300, 0), True)])
        b = T1.plane(-1, [(T1.rect(200, 0, 400, 300, 0), True)])
        top = T1.plane(1, [(T1.rect(3, 3, 397, 297, T), True)])
        g, why = geo_of(T1.body([a, b, top]))
        self.assertEqual(g['path'], 'silhouette')
        self.assertEqual(g['outer']['method'], 'kante', why)
        self.assertTrue(g['outer'].get('mixed'))
        self.assertEqual(len(g['outer']['edges']), 6)
        self.assertAlmostEqual(abs(G.area(g['outer']['pts'])), 400 * 300, 3)

    def test_project_fallback_when_silhouette_fails(self):
        orig_fp, orig_s = S.fast_path, S.silhouette
        S.fast_path = lambda regs, order=None, tol=0.05: {'region': None, 'why': ['Test']}
        S.silhouette = lambda regs, info=None: (info.update(open=[{'start': [0, 0], 'end': [1, 0], 'segments': 1,
                                                                    'length_mm': 1.0, 'gap_mm': 1.0}])
                                                if info is not None else None) or []
        try:
            exp = {'outer': [(0, 0), (400, 0), (400, 300), (0, 300)], 'holes': [[(10, 10), (10, 20), (20, 20)]]}
            g, why = geo_of(T1.make('durch'), exp)
        finally:
            S.fast_path, S.silhouette = orig_fp, orig_s
        self.assertIsNotNone(g)
        self.assertEqual(g['path'], 'projekt')
        self.assertEqual(g['outer']['method'], 'skizze')
        self.assertEqual(len(g['holes']), 1)
        self.assertTrue(any('offene Kette' in w for w in why))
        self.assertTrue(any('LazyNest-Projekt-Daten' in w for w in why))

    def test_bbox_gap_from_edges_not_body_box(self):
        g, why = T1.geo('fase')
        self.assertLess(g['bbox_gap'], 1e-6)
        self.assertFalse(any('Hüllbox' in w for w in why))

    def test_diag_dump(self):
        F.DIAG.update(on=True, parts=[])
        try:
            T1.geo('falz2')
            d = F.DIAG['parts'][0]
        finally:
            F.DIAG.update(on=False, parts=[])
        txt = json.dumps(d)
        self.assertIn('fast_path', d['data'])
        self.assertEqual(d['path'], 'silhouette')
        self.assertGreater(len(d['data']['faces']), 4)
        self.assertLess(len(txt), 200000)

    def test_geometry_cache(self):
        b = T1.make('durch')
        occ = FK.Occ('Teil:1')
        occ.entityToken = 'occ-1'
        b.entityToken = 'body-1'
        occ.bRepBodies.append(b)
        F.CACHE_SIG = ('doc', 5, 5, 1)
        F.clear_cache()
        F.CACHE_STATS.update(hit=0, miss=0)
        try:
            g1 = F.part_geometry(occ, F.Frame(None), None, None, [])
            g1['outer']['curves'] = ['alt']
            g2 = F.part_geometry(occ, F.Frame(None), None, None, [])
            self.assertEqual(F.CACHE_STATS, {'hit': 1, 'miss': 1})
            self.assertNotIn('curves', g2['outer'])
            self.assertEqual(g2['outer']['pts'], g1['outer']['pts'])
            F.CACHE_SIG = ('doc', 6, 6, 1)                   # Zeitachse geändert -> neu lesen
            F.part_geometry(occ, F.Frame(None), None, None, [])
            self.assertEqual(F.CACHE_STATS['miss'], 2)
        finally:
            F.CACHE_SIG = None
            F.clear_cache()


class _TLItem:
    def __init__(self, name):
        self.name, self.isSuppressed, self.isRolledBack, self.isGroup, self.healthState = name, False, False, False, 0


class _TL:
    def __init__(self, n):
        self.items = [_TLItem('Element %d' % i) for i in range(n)]
        self.markerPosition = n

    @property
    def count(self):
        return len(self.items)

    def item(self, i):
        return self.items[i]


class Compute(unittest.TestCase):
    """2.0.3: gemeinsamer Stand CA_Tools/computed_state (ca_core.ca_compute)."""
    def setUp(self):
        import importlib.util
        import os
        import sys
        R.LAST_COMPUTE.clear()
        d = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'ca_core')
        if 'test_ca_core' not in sys.modules:
            spec = importlib.util.spec_from_file_location('test_ca_core', os.path.join(d, '__init__.py'),
                                                          submodule_search_locations=[d])
            mod = importlib.util.module_from_spec(spec)
            sys.modules['test_ca_core'] = mod
            spec.loader.exec_module(mod)
        self.CC = sys.modules['test_ca_core'].ca_compute
        R.CC = self.CC
        self.d = FK.Design()
        self.d.timeline = _TL(7)
        self.d.designType = 1
        self.res = {'errors': 0, 'lines': []}

    def tearDown(self):
        R.CC = None

    def test_skip_after_lazynest_compute(self):
        self.assertTrue(self.CC.write(self.d, 'LazyNest')[0])
        self.assertTrue(R.compute_ok(self.d, self.res))
        self.assertEqual(self.d.computed, 0)
        self.assertEqual(self.res['compute'], 'übersprungen')
        self.assertEqual(self.res['compute_by'], 'LazyNest')

    def test_old_202_marker_alone_does_not_skip(self):
        self.d.attributes.add('CA_Tools', 'compute_state', json.dumps({'sig': R.core_sig(self.d), 'by': 'LazyNest'}))
        self.assertTrue(R.compute_ok(self.d, self.res))
        self.assertEqual(self.d.computed, 1)

    def test_compute_when_timeline_changed_and_record(self):
        self.CC.write(self.d, 'LazyNest')
        self.d.timeline.items.append(_TLItem('Skizze neu'))
        self.d.timeline.markerPosition = 8
        self.assertTrue(R.compute_ok(self.d, self.res))
        self.assertEqual(self.d.computed, 1)
        st = self.CC.read(self.d)
        self.assertEqual(st['by'], 'LazySetup')
        self.assertEqual(st['fp']['count'], 8)

    def test_compute_when_item_suppressed_or_renamed(self):
        self.CC.write(self.d, 'LazyNest')
        self.d.timeline.items[3].isSuppressed = True          # gleiche Anzahl/Marker – trotzdem geändert
        self.assertTrue(R.compute_ok(self.d, self.res))
        self.assertEqual(self.d.computed, 1)

    def test_rollback_marker(self):
        self.CC.write(self.d, 'LazyNest')
        self.d.timeline.markerPosition = 5
        self.assertTrue(R.compute_ok(self.d, self.res))
        self.assertEqual(self.d.computed, 1)

    def test_fingerprint_not_available_keeps_compute(self):
        self.CC.write(self.d, 'LazyNest')
        self.d.timeline = type('TL', (), {'count': 7, 'markerPosition': 7})()    # item() fehlt
        self.assertTrue(R.compute_ok(self.d, self.res))
        self.assertEqual(self.d.computed, 1)

    def test_doc_version_suffix_ignored(self):
        doc = type('Doc', (), {'name': 'defender v41', 'dataFile': None})()
        self.d.parentDocument = doc
        self.CC.write(self.d, 'LazyNest')
        doc.name = 'defender v42'                              # gespeichert -> gleiche Geometrie
        self.assertTrue(R.compute_ok(self.d, self.res))
        self.assertEqual(self.d.computed, 0)

    def test_mode_always_and_never(self):
        self.CC.write(self.d, 'LazyNest')
        self.assertTrue(R.compute_ok(self.d, self.res, 'immer'))
        self.assertEqual(self.d.computed, 1)
        self.d.timeline.items.append(_TLItem('x'))
        R.LAST_COMPUTE.clear()
        self.assertTrue(R.compute_ok(self.d, self.res, 'nie'))
        self.assertEqual(self.d.computed, 1)


class Timing(unittest.TestCase):
    def test_phases(self):
        import fs_timing as TM
        TM.reset()
        with TM.phase('A'):
            pass
        with TM.phase('A'):
            pass
        TM.count('x', 2)
        d = TM.data()
        self.assertEqual(d['calls']['A'], 2)
        self.assertIn('A ', TM.report())
        self.assertIn('x: 2', TM.report())


if __name__ == '__main__':
    unittest.main()


class Pipeline202(unittest.TestCase):
    setUp, tearDown, log, _swap = T1.Pipeline.setUp, T1.Pipeline.tearDown, T1.Pipeline.log, T1.Pipeline._swap
    def test_readback_timing_and_compute_skip(self):
        d = FK.build_design(self.sheets, project=True)
        Compute.setUp(self)                    # 2.0.3: R.CC = ca_core.ca_compute
        self.addCleanup(setattr, R, 'CC', None)
        d.timeline = _TL(3)
        d.designType = 1
        self._swap(d, 0, 'falz2')
        cam = FK.CAM(d)
        FK.linked_setup(cam, 1)
        R.LAST_COMPUTE.clear()
        res = R.run(FK.App(d, cam), None, d, {}, None, T1.TOOL, '2.0.2')
        self.assertEqual(res['errors'], 0, res)
        self.assertEqual(d.computed, 1)
        recs = [r for p in res['plans'] for r in p.get('operations') or []]
        rb = [r['contours']['readback'] for r in recs if (r.get('contours') or {}).get('ok')]
        self.assertTrue(rb)
        for r in recs:
            c = r.get('contours') or {}
            if c.get('ok'):
                self.assertEqual(c['readback']['n'], c['chains'])
                self.assertEqual(c['readback']['curves'], c['curves'])
        self.assertIn('Operationen anlegen', res['timing']['phases_ms'])
        self.assertIn('Einlesen', res['timing']['phases_ms'])
        self.assertIn('Zeiten (ms):', self.log())
        self.assertIn('Konturauswahl übernommen', self.log())
        # zweiter Lauf: Zeitachse unverändert -> kein computeAll (Stand im Design-Attribut)
        R.LAST_COMPUTE.clear()
        res = R.run(FK.App(d, cam), None, d, {}, None, T1.TOOL, '2.0.2')
        self.assertEqual(res['errors'], 0, res)
        self.assertEqual(d.computed, 1)
        self.assertEqual(res['compute'], 'übersprungen')

    def test_plan_memo(self):
        import fs_palette as P
        d = FK.build_design(self.sheets, project=True)
        sh = R.collect(d, None, None, [])
        ed = P.Editor()
        ed.setup(sh, R.plan_cfg({}), None)
        n = [0]
        orig = R.make_plan

        def mp(*a, **k):
            n[0] += 1
            return orig(*a, **k)
        R.make_plan = mp
        try:
            p1 = ed.plan()
            p2 = ed.plan()
            self.assertIs(p1, p2)
            self.assertEqual(n[0], 1)
            ed.cfg = dict(ed.cfg, steg_breite=ed.cfg['steg_breite'] + 1)
            ed.plan()
            self.assertEqual(n[0], 2)
        finally:
            R.make_plan = orig


import test_fs_200_lazysetup as T0   # noqa: E402


class SilDiagAction(T0.Base):
    def test_sil_diag_writes_json_read_only(self):
        T0.LS._read_design('t')
        n_sk = sum(len(o.component.sketches) for o in self.design.rootComponent.occurrences)
        r = T0.LS.handle('silDiag', {})
        self.assertTrue(r.get('ok'), r)
        self.assertGreater(r['parts'], 0)
        with open(r['file'], encoding='utf-8-sig') as f:
            d = json.load(f)
        self.assertEqual(d['version'], '2.0.12')
        self.assertIn('faces', d['parts'][0]['data'])
        self.assertFalse(F.DIAG['on'])
        self.assertEqual(sum(len(o.component.sketches) for o in self.design.rootComponent.occurrences), n_sk)
        self.assertEqual(self.design.computed, 0)

    def test_neuberechnen_field(self):
        s = T0.LS.handle('ready', {})
        self.assertIn('neuberechnen', [f[0] if isinstance(f, (list, tuple)) else f.get('key') for f in s['fields']])
        self.assertEqual(s['cfg']['neuberechnen'], 'auto')
