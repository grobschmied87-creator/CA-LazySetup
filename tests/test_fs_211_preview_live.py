# -*- coding: utf-8 -*-
"""LazySetup 2.0.11: Vorschau aus Live-Silhouette, nicht aus veraltetem Nest-Projekt-JSON."""
import inspect
import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [os.path.join(HERE, 'tests', 'fsstubs'), HERE, os.path.join(HERE, 'tests')]

import fsfake as FK       # noqa: E402
import fs_testdata as TD  # noqa: E402
import fs_log as L        # noqa: E402
import fs_geom as G       # noqa: E402
import fs_fusion as F     # noqa: E402
import fs_run as R        # noqa: E402
from ca_core import ca_compute  # noqa: E402

HOLES_SHEET = os.path.join(TD.ROOT, 'cn_logs3', 'apply_20261009_102512_483.json')


def shift_project_placements(design, dx, dy):
    a = design.attributes.itemByName('ContourNest', 'project_P1')
    proj = json.loads(a.value)
    for pl in proj['placements']:
        pl['x'] = float(pl['x']) + dx
        pl['y'] = float(pl['y']) + dy
    design.attributes.add('ContourNest', 'project_P1', json.dumps(proj))
    return proj


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


class PreviewLive(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        L.LOG_DIR = self.tmp
        L.LOG_FILE = os.path.join(self.tmp, 'lazysetup.log')
        self.sheets = TD.sheets_from(HOLES_SHEET)
        F.clear_cache()
        F.LAST_NEST_SIG = None
        F.CACHE_SIG = None
        F.CACHE_STATS.update(hit=0, miss=0)

    def tearDown(self):
        F.clear_cache()
        F.LAST_NEST_SIG = None
        F.CACHE_SIG = None
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_stale_project_json_does_not_replace_live(self):
        d = FK.build_design(self.sheets, project=True)
        shift_project_placements(d, 800.0, 400.0)
        warn = []
        sh = R.collect(d, None, None, warn)[0]
        self.assertEqual(len(sh['parts']), len(self.sheets[0]['parts']))
        for got, ref in zip(sh['parts'], self.sheets[0]['parts']):
            for a, b in zip(G.bbox(got['outer']), G.bbox(ref['outer'])):
                self.assertAlmostEqual(a, b, 5, msg=got['name'])
        recs = [r for r in sh['diag']['parts'] if r.get('result') == 'ok']
        self.assertTrue(recs)
        self.assertTrue(all('Projekt-Daten' not in r.get('geometry', '') for r in recs),
                        [r.get('geometry') for r in recs])
        self.assertTrue(any('Vorschau aus dem Modell' in w for w in warn), warn)
        self.assertTrue(any('Überdeckung' in w for w in warn), warn)
        self.assertFalse(any('Vorschau aus Projekt-Daten' in w for w in warn), warn)
        pp = F.project_parts(F.load_project(d, 'P1'), sh['project_sheet'], sh['sheet_info'])
        p0 = sh['parts'][0]
        pid = str(p0['key']).split('#')[0]
        q = next(x for x in pp if str(x['id']) == pid)
        self.assertLess(F._bbox_overlap(G.bbox(p0['outer']), G.bbox(q['outer'])), 0.5)

    def test_broken_brep_still_uses_json_when_no_silhouette(self):
        d = FK.build_design(self.sheets, project=True, broken=('Deckel',))
        warn = []
        sh = R.collect(d, None, None, warn)[0]
        deckel = next(p for p in sh['parts'] if p['name'] == 'Deckel')
        self.assertTrue(deckel['geo']['no_edges'])
        ref = next(p for p in self.sheets[0]['parts'] if p['name'] == 'Deckel')
        self.assertAlmostEqual(G.area(deckel['outer']), G.area(ref['outer']), 3)

    def test_empty_sheet_json_fallback(self):
        names = tuple(p['name'] for p in self.sheets[0]['parts'])
        d = FK.build_design(self.sheets, attrs_on='none', project=True, broken=names, with_bbox=False)
        warn = []
        sh = R.collect(d, None, None, warn)[0]
        self.assertEqual(len(sh['parts']), len(names))
        self.assertTrue(all(p['geo']['no_edges'] for p in sh['parts']))
        self.assertTrue(any('Projekt-Daten (nur Vorschau' in w for w in warn))

    def test_cache_key_changes_with_transform(self):
        b = FK.prism_body([(0, 0), (100, 0), (100, 50), (0, 50)], [], 15.0, (0, 0, 0))
        occ = FK.Occ('Teil:1')
        occ.entityToken = 'occ-pose-1'
        b.entityToken = 'body-pose-1'
        occ.bRepBodies.append(b)
        F.CACHE_SIG = ('doc', 5, 5, 1)
        k1 = F._cache_key(occ, F.Frame(None), [b])
        self.assertEqual(k1, F._cache_key(occ, F.Frame(None), [b]))
        occ.transform2 = FK.Transform(10, 0, 0)
        self.assertNotEqual(k1, F._cache_key(occ, F.Frame(None), [b]))
        F.part_geometry(occ, F.Frame(None), None, None, [])
        F.CACHE_STATS.update(hit=0, miss=0)
        F.part_geometry(occ, F.Frame(None), None, None, [])
        self.assertEqual(F.CACHE_STATS['hit'], 1)
        occ.transform2 = FK.Transform(20, 5, 0)
        F.part_geometry(occ, F.Frame(None), None, None, [])
        self.assertEqual(F.CACHE_STATS['miss'], 1)

    def test_collect_clears_cache_on_nest_move(self):
        d = FK.build_design(self.sheets, project=True)
        F.GEO_CACHE['stale'] = ({'marker': 1}, [])
        F.LAST_NEST_SIG = ('alt',)
        R.collect(d)
        self.assertNotIn('stale', F.GEO_CACHE)
        self.assertEqual(F.LAST_NEST_SIG, F.nest_layout_sig(d))
        F.GEO_CACHE['keep'] = ({'marker': 2}, [])
        R.collect(d)
        self.assertIn('keep', F.GEO_CACHE)
        po = d.rootComponent.occurrences[0].childOccurrences[0]
        po.transform2 = FK.Transform(12, 0, 0)
        po.attributes.add('ContourNest', 'pos_x_mm', '120')
        F.GEO_CACHE['keep'] = ({'marker': 2}, [])
        R.collect(d)
        self.assertNotIn('keep', F.GEO_CACHE)

    def test_nest_layout_sig_detects_child_move(self):
        d = FK.build_design(self.sheets, project=True)
        a = F.nest_layout_sig(d)
        po = d.rootComponent.occurrences[0].childOccurrences[0]
        po.transform2 = FK.Transform(3, 4, 0)
        self.assertNotEqual(a, F.nest_layout_sig(d))

    def test_compute_fingerprint_ignores_nest_pose(self):
        d = FK.build_design(self.sheets, project=True)
        d.timeline = _TL(4)
        d.designType = 1
        fp1 = ca_compute.fingerprint(d)
        po = d.rootComponent.occurrences[0].childOccurrences[0]
        po.transform2 = FK.Transform(9, 2, 0)
        po.attributes.add('ContourNest', 'pos_x_mm', '99')
        fp2 = ca_compute.fingerprint(d)
        self.assertIsNotNone(fp1)
        self.assertEqual(fp1, fp2)
        self.assertEqual(ca_compute.KEYS, ('doc', 'type', 'count', 'marker', 'items'))

    def test_read_design_skips_computeall(self):
        import LazySetup as LS
        src = inspect.getsource(LS._read_design)
        self.assertNotIn('computeAll', src)
        self.assertNotIn('compute_ok', src)


if __name__ == '__main__':
    unittest.main()
