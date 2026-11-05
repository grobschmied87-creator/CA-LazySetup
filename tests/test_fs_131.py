# -*- coding: utf-8 -*-
"""1.3.1: Konturauswahl leer (ADALAP 10.10., „InternalValidationError : edge“) – computeAll macht vorher
gelesene Kanten ungültig. Neu berechnen VOR dem Einlesen, Kanten vor set_chains frisch lesen, Fehler melden."""
import math
import os
import shutil
import tempfile
import unittest

import fsfake as FK       # noqa: E402  (setzt sys.path auf Stubs)
import fs_testdata as TD  # noqa: E402
import fs_log as L        # noqa: E402
import fs_cam as C        # noqa: E402
import fs_fusion as F     # noqa: E402
import fs_run as R        # noqa: E402
import fs_geom as G       # noqa: E402

HOLES_SHEET = os.path.join(TD.ROOT, 'cn_logs3', 'apply_20261009_102512_483.json')
TOOL = {'tool': FK.Tool(3, 8.0, 'Spiralfräser 8'), 'info': {'d_mm': 8.0}, 'label': 'T3 Ø 8'}


def contour_ops(setup):
    return [o for o in setup.operations if o.name.startswith('FS ') and o.parameters.itemByName('contours')]


class StaleEdges(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        L.LOG_DIR = self.tmp
        L.LOG_FILE = os.path.join(self.tmp, 'finalschnitt.log')
        self.sheets = TD.sheets_from(HOLES_SHEET)
        self.design = FK.build_design(self.sheets)
        self.cam = FK.CAM(self.design)
        self.app = FK.App(self.design, self.cam)
        self.setup = FK.linked_setup(self.cam, 1)
        del FK.EVENTS[:]

    def tearDown(self):
        FK.INVALIDATE.clear()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_fs(self, cfg=None):
        return R.run(self.app, None, self.design, cfg or {}, None, TOOL, '1.3.1', None)

    def log(self):
        with open(L.LOG_FILE, encoding='utf-8-sig') as f:
            return f.read()

    def check_all_selected(self, res, valid_at_end=True):
        self.assertEqual(res['errors'], 0, res['warnings'])
        ops = contour_ops(self.setup)
        self.assertTrue(ops)
        n_holes = sum(len(p['holes']) for p in self.sheets[0]['parts'])
        n_outer = len(self.sheets[0]['parts'])
        seen_holes = seen_outer = 0
        for op in ops:
            applied = op.parameters.itemByName('contours').value.applied
            self.assertTrue(applied, op.name)                       # nie leere Konturauswahl
            for ch in applied:
                self.assertTrue(ch.inputGeometry)
                if valid_at_end:
                    self.assertTrue(all(e.isValid for e in ch.inputGeometry), op.name)
            if 'Innen' in op.name:
                seen_holes += len(applied)
            elif 'Außen' in op.name:
                seen_outer += len(applied)
        self.assertEqual(seen_holes, n_holes)
        self.assertEqual(seen_outer, n_outer)
        self.assertFalse(any('fehlgeschlagen' in ln for ln in res['lines']), res['lines'])

    def test_fake_reproduces_bug_with_old_edges(self):
        # Gegenprobe: alte Kanten-Objekte nach computeAll -> Fusion lehnt ab (wie ADALAP)
        sh = R.collect(self.design, self.cam, None, [])[0]
        edges = sh['parts'][0]['geo']['outer']['edges']
        FK.INVALIDATE.add('compute')
        self.design.computeAll()
        self.assertFalse(F.edges_valid(edges))
        ch = FK.ChainSelection()
        with self.assertRaises(RuntimeError):
            ch.inputGeometry = list(edges)

    def test_compute_all_invalidates_prior_edges(self):
        FK.INVALIDATE.add('compute')
        res = self.run_fs()
        kinds = [e[0] for e in FK.EVENTS]
        self.assertEqual(kinds[0], 'compute')
        self.assertEqual(kinds.count('compute'), 1)                 # nur einmal, VOR dem Einlesen
        self.check_all_selected(res)
        # zweiter Lauf (Ersetzen) ebenso
        res = self.run_fs()
        self.check_all_selected(res)

    def test_invalidated_after_reading_retries(self):
        # Kanten werden ungültig, nachdem sie frisch gelesen wurden (z. B. Skizze/Operation dazwischen)
        FK.INVALIDATE.add('compute')
        orig = C.new_op

        def new_op(*a, **k):
            FK.invalidate_all()
            return orig(*a, **k)
        C.new_op = new_op
        try:
            res = self.run_fs({'taschen': False})
        finally:
            C.new_op = orig
        self.check_all_selected(res, valid_at_end=False)     # spätere Ops machen frühere Objekte im Fake ungültig
        recs = [r for p in res['plans'] for r in p.get('operations', [])]
        self.assertTrue(any(r.get('contours_reread') for r in recs))
        self.assertIn('frisch aus der B-Rep lesen', self.log())

    def test_failure_reported_no_success_line(self):
        FK.INVALIDATE.add('sketch')                                  # Skizzen anlegen -> alte Kanten ungültig
        orig = F.reread_geometry
        F.reread_geometry = lambda sheet, part, why=None: False     # Neu-Lesen klappt nicht
        try:
            res = self.run_fs()
        finally:
            F.reread_geometry = orig
        self.assertGreater(res['errors'], 0)
        bad = [ln for ln in res['lines'] if 'Konturauswahl fehlgeschlagen' in ln]
        self.assertEqual(len(bad), 1, res['lines'])
        self.assertIn('ohne Geometrie', bad[0])
        self.assertTrue(res['warnings'][0].startswith(bad[0]))
        self.assertFalse(any(ln.endswith('Stege') and 'Operation(en),' in ln for ln in res['lines']))
        self.assertIn('Kettenauswahl', self.log())

    def test_set_chains_validity_check(self):
        sh = R.collect(self.design, self.cam, None, [])[0]
        g = sh['parts'][0]['geo']['outer']
        FK.invalidate_all()
        calls = []

        def refetch():
            calls.append(1)
            F.reread_geometry(sh, sh['parts'][0])
            return [(sh['parts'][0]['geo']['outer']['edges'], False)]

        op = FK.Operation(self.setup, FK.OpInput('contour2d'), self.cam)
        rec = {}
        self.assertTrue(C.set_chains(op, [(g['edges'], False)], rec, refetch=refetch))
        self.assertEqual(calls, [1])
        self.assertEqual(rec['contours_reread'], 1)

    def test_reread_matches_holes_by_position(self):
        sh = R.collect(self.design, self.cam, None, [])[0]
        p = max(sh['parts'], key=lambda q: len(q['geo']['holes']))
        before = [h['pts'] for h in p['geo']['holes']]
        FK.invalidate_all()
        self.assertTrue(F.reread_geometry(sh, p))
        self.assertTrue(F.edges_valid(p['geo']['outer']['edges']))
        self.assertEqual(len(p['geo']['holes']), len(before))
        for b, h in zip(before, p['geo']['holes']):
            self.assertTrue(h['edges'])
            self.assertTrue(F.edges_valid(h['edges']))
            self.assertLess(math.dist(G.centroid(G.orient(b, True)), G.centroid(G.orient(h['pts'], True))), 0.5)


if __name__ == '__main__':
    unittest.main()
