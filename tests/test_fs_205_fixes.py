# -*- coding: utf-8 -*-
"""LazySetup 2.0.5: Fixes 1–6 (ohne Fusion)."""
import math
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.dirname(HERE), HERE]

import fsfake as FK  # noqa: F401 – adsk-Stubs
import fs_geom as G
import fs_edit as E
import fs_cam as C


def rect(x, y, w, h):
    return [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]


def sheet(parts, L=2800.0, W=1300.0):
    return {'no': 1, 'name': 'T', 'length': L, 'width': W, 'thickness': 15.0,
            'zero_side': 'oben',
            'parts': [{'name': 'P%d' % k, 'id': 'p%d' % k, 'key': 'p%d#1' % k,
                       'outer': o, 'holes': hs,
                       'geo': {'z_bottom': 0.0, 'z_top': 18.0}}
                      for k, (o, hs) in enumerate(parts)]}


class HoleStarts(unittest.TestCase):
    def test_hole_start_inside_opening(self):
        outer = rect(100, 100, 400, 300)
        hole = rect(150, 150, 100, 80)
        pl = G.plan_sheet(sheet([(outer, [hole])]))
        p = pl['parts'][0]
        self.assertEqual(len(p['hole_starts']), 1)
        hs = p['hole_starts'][0]
        self.assertEqual(hs['mode'], 'loch')
        # Einstich Richtung Lochmitte
        cen = G.centroid(hole)
        self.assertLess(math.dist(hs['entry'], cen), math.dist(hs['pt'], cen))

    def test_hole_start_override(self):
        outer = rect(100, 100, 400, 300)
        hole = rect(150, 150, 100, 80)
        sh = sheet([(outer, [hole])])
        pl0 = G.plan_sheet(sh)
        ov = E.empty()
        ok = None
        ov, msgs, ok = E.apply_edit(pl0, ov, {'op': 'start_set', 'key': 'p0#1', 'hole': 0,
                                              'pt': (150, 190), 'to': (150, 190)})
        self.assertTrue(ok)
        pl = G.plan_sheet(sh, {}, ov)
        self.assertTrue(pl['parts'][0]['hole_starts'][0]['manual'])


class EvenTabs(unittest.TestCase):
    def test_even_distribution(self):
        pl = G.plan_sheet(sheet([(rect(100, 100, 800, 400), [])]),
                          {'stege': True, 'steg_min': 4, 'bruecken': False, 'steg_abstand_mittel': 500})
        p = pl['parts'][0]
        ss = sorted(t['s'] for t in p['tabs'] if not t.get('bridge'))
        self.assertGreaterEqual(len(ss), 4)
        gaps = [G.cyc_dist(ss[i], ss[(i + 1) % len(ss)], p['per']) for i in range(len(ss))]
        # Abweichung der Lücken < 35 % vom Mittel (früher oft Cluster)
        mean = sum(gaps) / len(gaps)
        self.assertTrue(all(abs(g - mean) / mean < 0.35 for g in gaps), gaps)


class OrderOverride(unittest.TestCase):
    def test_manual_order(self):
        sh = sheet([(rect(100, 100, 200, 200), []), (rect(400, 100, 500, 400), [])])
        ov = E.empty()
        ov['order'] = ['p1#1', 'p0#1']
        pl = G.plan_sheet(sh, {}, ov)
        self.assertEqual([pl['parts'][i]['key'] for i in pl['order']], ['p1#1', 'p0#1'])
        self.assertTrue(pl['overrides']['order_manual'])
        ov2, msgs, ok = E.apply_edit(pl, E.empty(), {'op': 'order_set', 'order': ['p0#1', 'p1#1']})
        self.assertTrue(ok)
        self.assertEqual(ov2['order'], ['p0#1', 'p1#1'])


class SketchZ(unittest.TestCase):
    def test_oben_uses_top(self):
        sh = {'zero_side': 'oben', 'parts': [
            {'geo': {'z_bottom': 0.0, 'z_top': 18.0}},
            {'geo': {'z_bottom': 1.0, 'z_top': 19.0}}]}
        self.assertEqual(C.sketch_z_mm(sh), 19.0)
        sh['zero_side'] = 'unten'
        self.assertEqual(C.sketch_z_mm(sh), 0.0)


class PlanJsonHoles(unittest.TestCase):
    def test_payload_has_hole_starts_and_order(self):
        pl = G.plan_sheet(sheet([(rect(0, 0, 300, 200), [rect(40, 40, 60, 50)])]))
        j = E.plan_json(pl)
        self.assertEqual(len(j['parts'][0]['hole_starts']), 1)
        self.assertIn('order_keys', j)


class ListToolsFilter(unittest.TestCase):
    def test_library_id_filter_signature(self):
        # reine Signatur / Default ohne CAM
        import inspect
        sig = inspect.signature(C.list_tools)
        self.assertIn('library_id', sig.parameters)


if __name__ == '__main__':
    unittest.main()
