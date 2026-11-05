# -*- coding: utf-8 -*-
"""LazySetup 2.0.9: bridge_move, Vorfräs-Defaults/Params, i18n, Version."""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, 'tests'))

import fsfake  # noqa: F401 – vor fs_cam
import fs_edit as E
import fs_geom as G
from ca_core import ca_i18n


class TestVersion(unittest.TestCase):
    def test_version(self):
        import LazySetup as LS
        self.assertEqual(LS.VERSION, '2.0.9')


class TestI18n(unittest.TestCase):
    def test_langs(self):
        for lang in ('de', 'en', 'es', 'fr'):
            p = ca_i18n.payload(lang)
            self.assertEqual(p['language'], lang)
            self.assertIn('run_ops', p['strings'])
            self.assertTrue(p['strings']['run_ops'])

    def test_fallback(self):
        self.assertEqual(ca_i18n.normalize_lang('xx'), 'de')
        self.assertIn('Vorfräsen', ca_i18n.t('premill', 'de'))


class TestDefaultsVorfraes(unittest.TestCase):
    def test_keys(self):
        self.assertIn('vorfraesen', G.DEFAULTS)
        self.assertFalse(G.DEFAULTS['vorfraesen'])
        self.assertEqual(G.DEFAULTS['vorfraes_rest_mm'], 1.0)
        self.assertEqual(G.DEFAULTS['vorfraes_aufmass'], 0.5)

    def test_fields(self):
        import LazySetup as LS
        keys = [f[0] for f in LS.FIELDS]
        self.assertIn('vorfraesen', keys)
        self.assertIn('vorfraes_rest_mm', keys)
        self.assertIn('vorfraes_aufmass', keys)


class TestCommonParamsSignature(unittest.TestCase):
    def test_signature(self):
        import inspect
        import fs_cam as C
        sig = inspect.signature(C.common_params)
        self.assertIn('leave_mm', sig.parameters)
        self.assertIn('stock', sig.parameters)


class TestBridgeMove(unittest.TestCase):
    def _plan(self):
        # Minimal plan with two parts and one bridge
        def part(key, idx, pts):
            c = G.cum(pts)
            area = abs(G.signed_area(pts))
            cx = sum(p[0] for p in pts) / len(pts)
            cy = sum(p[1] for p in pts) / len(pts)
            return {
                'key': key, 'idx': idx, 'name': key, 'outer': pts, '_c': c,
                'per': c[1], 'area': area, 'centroid': (cx, cy),
                'holes': [], 'tabs': [], 'start': {'pt': pts[0], 'entry': pts[0], 's': 0.0},
            }
        A = part('a#1', 0, [(0, 0), (100, 0), (100, 40), (0, 40)])
        B = part('b#1', 1, [(108, 0), (208, 0), (208, 40), (108, 40)])  # gap 8 mm
        # bridge ends
        pa, pb = (100, 20), (108, 20)
        br = {'a': 0, 'b': 1, 'pa': pa, 'pb': pb, 'sa': 100 + 20, 'sb': 0 + 20, 'manual': False, 'gap': 8.0}
        A['tabs'] = [{'pt': pa, 's': 120, 'bridge': True, 'manual': False}]
        B['tabs'] = [{'pt': pb, 's': 20, 'bridge': True, 'manual': False}]
        return {
            'parts': [A, B], 'bridges': [br], 'order': [0, 1],
            'cfg': dict(G.DEFAULTS, tool_d=8.0, bruecke_extra=2.5, start_ecke_min=15.0),
            'overrides': E.empty(),
        }

    def test_bridge_move(self):
        plan = self._plan()
        ov, msgs, ok = E.apply_edit(plan, E.empty(), {
            'op': 'bridge_move', 'key': 'a#1', 'pt': [100, 20], 'to': [100, 30],
        })
        self.assertTrue(ok, msgs)
        self.assertTrue(ov['bridges_add'] or ov['bridges_del'], msgs)
        self.assertTrue(any('verschoben' in m for m in msgs), msgs)


if __name__ == '__main__':
    unittest.main()
