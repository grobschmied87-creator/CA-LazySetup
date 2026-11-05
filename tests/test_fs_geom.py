# -*- coding: utf-8 -*-
"""Reine Geometrie-Tests mit echten ContourNest-Konturen (cn_logs*/apply_*.json)."""
import math
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.dirname(HERE), HERE]

import fs_geom as G      # noqa: E402
import fs_testdata as TD  # noqa: E402

HOLES_SHEET = os.path.join(TD.ROOT, 'cn_logs3', 'apply_20261009_102512_483.json')


def inside(q, poly):
    x, y = q
    c = False
    for i in range(len(poly)):
        (x0, y0), (x1, y1) = poly[i], poly[i - 1]
        if (y0 > y) != (y1 > y) and x < x0 + (y - y0) * (x1 - x0) / (y1 - y0):
            c = not c
    return c


def rect(x0, y0, w, h):
    return [(x0, y0), (x0 + w, y0), (x0 + w, y0 + h), (x0, y0 + h)]


def sheet(parts, L=2500.0, W=1250.0):
    return {'no': 1, 'name': 'Test', 'length': L, 'width': W, 'thickness': 15.0,
            'parts': [{'name': n, 'key': n, 'outer': o, 'holes': h} for n, o, h in parts]}


class RealData(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sheets = TD.all_sheets()
        cls.plans = [G.plan_sheet(s) for s in cls.sheets]

    def test_data_present(self):
        self.assertGreaterEqual(len(self.sheets), 8)
        self.assertTrue(any(p['holes'] for s in self.sheets for p in s['parts']), 'Löcher aus Projektdatei')

    def test_order_by_key(self):
        for s in self.sheets:                     # alte Regel „gewichtung“ weiterhin wählbar
            pl = G.plan_sheet(s, {'reihenfolge': 'gewichtung'})
            keys = [pl['parts'][i]['sort_key'] for i in pl['order']]
            smalls = [pl['parts'][i]['small'] for i in pl['order']]
            self.assertEqual(smalls, sorted(smalls, reverse=True))
            big = [k for k, s in zip(keys, smalls) if not s]
            self.assertEqual(big, sorted(big))
            self.assertEqual(sorted(pl['order']), list(range(len(pl['parts']))))

    def test_small_edge_first_large_central_last(self):
        checked = 0
        for pl in self.plans:
            ps = pl['parts']
            first, last = ps[pl['order'][0]], ps[pl['order'][-1]]
            self.assertLessEqual(first['area'], last['area'] + 1e-6)
            # Stirnwand-Nestings: kleinstes Teil zuerst (andere Jobs haben andere Kleinteile)
            if any(p.get('name') == 'Stirnwand' for p in ps):
                self.assertEqual(first['name'], 'Stirnwand')
                checked += 1
        self.assertGreaterEqual(checked, 1)

    def test_weight_extremes(self):
        s = TD.sheets_from(HOLES_SHEET)[0]
        pa = G.plan_sheet(s, {'w_flaeche': 100, 'kleinteile_zuerst': False, 'reihenfolge': 'gewichtung'})
        areas = [pa['parts'][i]['area'] for i in pa['order']]
        self.assertEqual(areas, sorted(areas))
        pd = G.plan_sheet(s, {'w_flaeche': 0, 'kleinteile_zuerst': False, 'reihenfolge': 'gewichtung'})
        dists = [pd['parts'][i]['dist_center'] for i in pd['order']]
        self.assertEqual(dists, sorted(dists, reverse=True))

    def test_start_on_contour_and_near_centre(self):
        for pl in self.plans:
            for p in pl['parts']:
                c = p['target']                   # ab 1.1.0: Richtung größte Restfläche
                st = p['start']
                self.assertLess(G.dist_point_poly(st['pt'], p['outer']), 1e-6)
                best = G.closest_on_poly(p['outer'], c)['d']
                self.assertLessEqual(math.dist(st['pt'], c), best + pl['cfg']['vertex_suche'] + 1e-6)
                self.assertFalse(inside(st['entry'], p['outer']), 'Einstich im Abfall')
                self.assertAlmostEqual(G.dist_point_poly(st['entry'], p['outer']), pl['cfg']['tool_d'] / 2 + 2, 1)

    def test_tabs_rules(self):
        n_bridge = 0
        for pl in self.plans:
            cfg = pl['cfg']
            for p in pl['parts']:
                n, why = G.tab_count(p, cfg)
                self.assertGreaterEqual(len(p['tabs']), min(n, 1) if n else 0)
                for t in p['tabs']:
                    self.assertLess(G.dist_point_poly(t['pt'], p['outer']), 1e-6)
                    d = G.cyc_dist(t['s'], p['start']['s'], p['per'])
                    self.assertGreaterEqual(d, cfg['start_abstand_min'], '%s: Steg zu nah am Start' % p['name'])
                    if t.get('bridge'):
                        n_bridge += 1
                    else:
                        self.assertGreaterEqual(t['web'], cfg['steg_rest_min'], 'Steg ohne Restmaterial')
                    for _i, sc, _t in G.corners(p['outer'], 45.0):
                        if not t.get('bridge'):
                            self.assertGreaterEqual(G.cyc_dist(t['s'], sc, p['per']), 25.0 - 1e-6)
                ss = sorted(t['s'] for t in p['tabs'])
                for a, b in zip(ss, ss[1:]):
                    self.assertGreaterEqual(b - a, 2 * cfg['steg_breite'] - 1e-6)
        self.assertGreater(n_bridge, 0)

    def test_bridges_cn_logs3(self):
        s = TD.sheets_from(HOLES_SHEET)[0]
        pl = G.plan_sheet(s)
        self.assertGreaterEqual(len(pl['bridges']), 3)
        for b in pl['bridges']:
            self.assertLessEqual(b['gap'], 8.0 + 2.5 + 0.06)
            self.assertAlmostEqual(math.dist(b['pa'], b['pb']), b['gap'], 3)
            pa = [t for t in pl['parts'][b['a']]['tabs'] if t.get('bridge') and t['pt'] == b['pa']]
            pb = [t for t in pl['parts'][b['b']]['tabs'] if t.get('bridge') and t['pt'] == b['pb']]
            self.assertTrue(pa and pb, 'Brückensteg auf beiden Teilen')
        self.assertEqual(G.plan_sheet(s, {'bruecke_extra': 2.0})['bridges'], [])
        self.assertEqual(G.plan_sheet(s, {'bruecken': False})['bridges'], [])

    def test_holes_inner_first(self):
        s = TD.sheets_from(HOLES_SHEET)[0]
        pl = G.plan_sheet(s)
        self.assertEqual(len(pl['inner']), sum(len(p['holes']) for p in pl['parts']))
        cs = [G.centroid(it['poly']) for it in pl['inner']]       # Kette „nächster Nachbar“ ab Nullpunkt
        cur = (0.0, 0.0)
        for k, c in enumerate(cs):
            self.assertLessEqual(math.dist(cur, c), min(math.dist(cur, q) for q in cs[k:]) + 1e-9)
            cur = c
        for it in pl['inner']:
            self.assertLess(G.signed_area(it['poly']), 0)


class Synthetic(unittest.TestCase):
    def test_tab_count_classes(self):
        s = sheet([('klein', rect(100, 100, 80, 80), []), ('mittel', rect(400, 100, 500, 300), []),
                   ('gross', rect(1000, 100, 700, 700), [])])
        pl = G.plan_sheet(s)
        by = {p['name']: p for p in pl['parts']}
        self.assertTrue(by['klein']['small'])
        self.assertEqual(G.tab_count(by['klein'], pl['cfg'])[0], 3)
        self.assertEqual(G.tab_count(by['mittel'], pl['cfg'])[0], max(2, math.ceil(1600 / 500)))
        # ab 1.1.0 auch große Teile nach Umfang (mind. „stege_gross“ = 4)
        self.assertEqual(G.tab_count(by['gross'], pl['cfg'])[0], max(4, math.ceil(2800 / 500)))
        self.assertGreaterEqual(len(by['gross']['tabs']), 4)
        self.assertEqual(G.tab_count(by['gross'], dict(pl['cfg'], stege_gross=0))[0], math.ceil(2800 / 500))
        self.assertEqual(pl['order'][0], 0)
        off = G.plan_sheet(s, {'stege': False})
        byo = {p['name']: p for p in off['parts']}
        self.assertEqual(len(byo['mittel']['tabs']), 0)
        # 80×80-Kleinteil: 3 Stege passen mit Mindestabstand nicht neben Start/Ecken -> 2 + Warnung (statt
        # zwei Stege direkt nebeneinander wie bis 1.0.6)
        self.assertGreaterEqual(len(byo['klein']['tabs']), 2, 'Kleinteil immer mit Stegen')
        self.assertTrue(any('nur 2 von 3 Stegen' in w for w in off['warnings']), off['warnings'])
        self.assertTrue(off['warnings'])

    def test_vertex_preference(self):
        # Zentrum (1250, 625); Teil rechts oberhalb: nächster Punkt 10 mm neben der Ecke -> Ecke gewählt
        s = sheet([('a', rect(1240, 700, 300, 200), [])])
        pl = G.plan_sheet(s, {'reihenfolge': 'gewichtung'})       # Richtung Plattenmitte
        st = pl['parts'][0]['start']
        self.assertTrue(st['vertex'])
        self.assertEqual(st['pt'], (1240.0, 700.0))
        s2 = sheet([('b', rect(1100, 700, 400, 200), [])])
        st2 = G.plan_sheet(s2, {'reihenfolge': 'gewichtung'})['parts'][0]['start']
        self.assertFalse(st2['vertex'])
        self.assertAlmostEqual(st2['pt'][0], 1250.0, 6)
        self.assertAlmostEqual(st2['pt'][1], 700.0, 6)

    def test_tabs_face_scrap_not_neighbour(self):
        # zwei Teile 20 mm Abstand (Werkzeug 8: Rest 4 mm, keine Brücke); Steg nicht auf der Nachbarseite,
        # wenn dort zu wenig Material bleibt (20-8-8 = 4 >= 3 -> erlaubt) – bei 14 mm Abstand verboten
        s = sheet([('a', rect(100, 100, 600, 400), []), ('b', rect(714, 100, 600, 400), [])])
        pl = G.plan_sheet(s, {'bruecken': False})
        a = pl['parts'][0]
        for t in a['tabs']:
            self.assertFalse(abs(t['pt'][0] - 700) < 1e-6, 'Steg zur nahen Nachbarkante ohne Restmaterial')

    def test_tight_radius_excluded(self):
        # Teil mit Halbkreis-Ende r = 6 mm (< 1,5 × 8): keine Stege auf dem Bogen
        pts = [(300, 300), (700, 300)]
        for k in range(1, 24):
            a = -math.pi / 2 + math.pi * k / 24
            pts.append((700 + 6 * math.cos(a), 306 + 6 * math.sin(a)))
        pts += [(700, 312), (300, 312)]
        s = sheet([('stab', pts, [])])
        pl = G.plan_sheet(s, {'vak_min_cm2': 1.0, 'steg_min': 2})
        for t in pl['parts'][0]['tabs']:
            self.assertLess(t['pt'][0], 700 - 1e-6)

    def test_manual_points(self):
        s = sheet([('a', rect(100, 100, 600, 400), []), ('b', rect(1000, 100, 300, 300), [])])
        pl = G.plan_sheet(s)
        r = G.apply_manual(pl, [(705, 300)], [(400, 95), (400, 505), (2000, 1000)])
        self.assertEqual({k: r[k] for k in ('start', 'tabs', 'ignored', 'bridges')},
                         {'start': 1, 'tabs': 2, 'ignored': 1, 'bridges': 0})
        self.assertEqual(r['ignored_pts'], [(2000, 1000)])
        self.assertEqual(r['parts_without'], ['b'])
        a = pl['parts'][0]
        self.assertEqual(a['start']['pt'], (700.0, 300.0))
        self.assertTrue(a['start']['manual'])
        self.assertEqual(sorted(t['pt'] for t in a['tabs']), [(400.0, 100.0), (400.0, 500.0)])

    def test_corners_rounded(self):
        r = 4.5
        pts = []
        for cx, cy, a0 in ((100 - r, 100 - r, 0), (r, 100 - r, 90), (r, r, 180), (100 - r, r, 270)):
            for k in range(5):
                a = math.radians(a0 + 90 * k / 4)
                pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
        c = G.corners(G.orient(pts), 30)
        self.assertEqual(len(c), 4)
        self.assertTrue(all(abs(t - 90) < 1 for _i, _s, t in c))

    def test_preview_png(self):
        s = TD.sheets_from(HOLES_SHEET)[0]
        pl = G.plan_sheet(s)
        out = os.path.join('/tmp', 'fs_test_preview.png')
        G.render_preview(pl, out)
        with open(out, 'rb') as f:
            head = f.read(24)
        self.assertEqual(head[:8], b'\x89PNG\r\n\x1a\n')
        import struct
        w, h = struct.unpack('>II', head[16:24])
        self.assertEqual(w, 900)
        self.assertAlmostEqual(h, 1250 * (900 - 24) / 2500 + 24, delta=2)


if __name__ == '__main__':
    unittest.main()
