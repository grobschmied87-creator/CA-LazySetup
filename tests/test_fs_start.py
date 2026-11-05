# -*- coding: utf-8 -*-
"""1.0.4: „Startpunkt-Lage“ – Ecke nahe Plattenmitte / Kantenmitte zur Plattenmitte / nächster Punkt."""
import math
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.dirname(HERE), HERE]

import fs_geom as G       # noqa: E402
import fs_testdata as TD  # noqa: E402


def rect(x, y, w, h):
    return [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]


def sheet(parts, L=2800.0, W=1300.0):
    return {'no': 1, 'name': 'T', 'length': L, 'width': W, 'thickness': 15.0,
            'parts': [{'name': 'P%d' % k, 'id': 'p%d' % k, 'outer': o, 'holes': []} for k, o in enumerate(parts)]}


def corner_dist(p):
    """Kleinster Abstand des Startpunkts zu einer Ecke (entlang der Kontur)."""
    cs = G.corners(p['outer'], 30.0, p['_c'])
    return min(G.cyc_dist(p['start']['s'], s, p['per']) for _i, s, _t in cs) if cs else 1e9


class StartModes(unittest.TestCase):
    def test_kante_rectangle_mid_of_facing_edge(self):
        # Teil links unten: Kante zur Mitte = rechte (Normale +x, 600 mm lang) bzw. obere Kante (400 mm)
        pl = G.plan_sheet(sheet([rect(100, 100, 400, 600)]), {'start_modus': 'kante'})
        p = pl['parts'][0]
        self.assertEqual(p['start']['mode'], 'kante')
        self.assertFalse(p['start']['vertex'])
        x, y = p['start']['pt']
        # rechte Kante: 600 × Ausrichtung schlägt obere Kante 400 × Ausrichtung
        self.assertAlmostEqual(x, 500.0, 6)
        self.assertAlmostEqual(y, 400.0, 6)
        self.assertGreaterEqual(corner_dist(p), 15.0)
        # Einstich außerhalb (im Abfall)
        self.assertGreater(p['start']['entry'][0], 500.0)

    def test_ecke_default_unchanged(self):
        sh = sheet([rect(100, 100, 400, 400)])          # nächster Punkt = Ecke (500, 500)
        a = G.plan_sheet(sh)
        b = G.plan_sheet(sh, {'start_modus': 'ecke'})
        self.assertEqual(a['parts'][0]['start']['pt'], b['parts'][0]['start']['pt'])
        self.assertTrue(a['parts'][0]['start']['vertex'])
        self.assertEqual(a['parts'][0]['start']['pt'], (500, 500))
        k = G.plan_sheet(sh, {'start_modus': 'kante'})['parts'][0]
        self.assertEqual(k['start']['pt'], (500.0, 300.0))

    def test_naechster_no_corner_preference(self):
        sh = sheet([rect(100, 100, 400, 600)])
        p = G.plan_sheet(sh, {'start_modus': 'naechster'})['parts'][0]
        near = G.closest_on_poly(p['outer'], p['target'], p['_c'])   # Richtung größte Restfläche
        self.assertEqual(p['start']['pt'], near['pt'])
        self.assertFalse(p['start']['vertex'])
        self.assertEqual(p['start']['mode'], 'naechster')

    def test_kante_real_parts_away_from_corners(self):
        """Echte ContourNest-Konturen: im Modus Kantenmitte liegt jeder Start ≥ X mm von jeder Ecke entfernt
        (sofern eine passende Kante existiert), und Stege halten den Mindestabstand zum Start."""
        n_kante = n_all = 0
        for sh in TD.all_sheets():
            for X in (15.0, 40.0):
                cfg = {'start_modus': 'kante', 'start_ecke_min': X}
                pl = G.plan_sheet(sh, cfg)
                c = pl['cfg']
                min_start = max(float(c['start_abstand_min']), 3 * c['tool_d']) + c['steg_breite'] / 2
                for p in pl['parts']:
                    n_all += 1
                    if p['start']['mode'] == 'kante':
                        n_kante += 1
                        self.assertGreaterEqual(corner_dist(p) + 1e-6, max(X, c['tool_d']), p['name'])
                        for t in p['tabs']:
                            if not t.get('bridge'):
                                self.assertGreaterEqual(G.cyc_dist(t['s'], p['start']['s'], p['per']) + 1e-6,
                                                        min_start, p['name'])
                    else:
                        self.assertEqual(p['start']['mode'], 'naechster')
        self.assertGreater(n_kante, 0.8 * n_all)

    def test_kante_fallback_arc(self):
        circ = [(700 + 150 * math.cos(2 * math.pi * k / 72), 400 + 150 * math.sin(2 * math.pi * k / 72))
                for k in range(72)]
        p = G.plan_sheet(sheet([circ]), {'start_modus': 'kante'})['parts'][0]
        self.assertEqual(p['start']['mode'], 'naechster')
        near = G.closest_on_poly(p['outer'], p['target'], p['_c'])   # Richtung größte Restfläche
        self.assertEqual(p['start']['pt'], near['pt'])

    def test_kante_short_edges_fallback(self):
        # Teil, dessen Kanten alle kürzer als 2 × Mindestabstand sind -> Rückfall
        p = G.plan_sheet(sheet([rect(100, 100, 20, 25)]), {'start_modus': 'kante', 'start_ecke_min': 15.0,
                                                          'tool_d': 6.0})['parts'][0]
        self.assertEqual(p['start']['mode'], 'naechster')

    def test_kleinteile_immer_kante(self):
        sh = sheet([rect(100, 100, 80, 90), rect(600, 100, 600, 500)])
        pl = G.plan_sheet(sh, {'start_modus': 'ecke', 'kleinteile_kante': True, 'vak_min_cm2': 100.0})
        small, big = pl['parts']
        self.assertTrue(small['small'])
        self.assertEqual(small['start']['mode'], 'kante')
        self.assertEqual(big['start']['mode'], 'ecke')
        self.assertGreaterEqual(corner_dist(small), 15.0)
        sm = G.plan_summary(pl)
        self.assertEqual({o['name']: o['start_mode'] for o in sm['order']}, {'P0': 'kante', 'P1': 'ecke'})

    def test_preview_differs(self):
        import tempfile
        sh = TD.all_sheets()[0]
        d = tempfile.mkdtemp()

        def png(mode):
            with open(G.render_preview(G.plan_sheet(sh, {'start_modus': mode}), os.path.join(d, mode + '.png')),
                      'rb') as f:
                return f.read()
        a, b = png('ecke'), png('kante')
        self.assertNotEqual(a, b)


if __name__ == '__main__':
    unittest.main()
