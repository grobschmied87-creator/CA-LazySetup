# -*- coding: utf-8 -*-
"""Teile-Erkennung in ContourNest-Rohteilen (v1.0.1): Attribute nur an der nativen Occurrence, verschachtelte
Körper, Plattenkörper/alte Platten-Komponente, Projekt-Daten als Rückfall, CAM-Kontext, Protokoll."""
import json
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

HOLES_SHEET = os.path.join(TD.ROOT, 'cn_logs3', 'apply_20261009_102512_483.json')
TOOL = {'tool': FK.Tool(3, 8.0, 'Spiralfräser 8'), 'info': {'d_mm': 8.0}, 'label': 'T3 Ø 8'}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        L.LOG_DIR = self.tmp
        L.LOG_FILE = os.path.join(self.tmp, 'finalschnitt.log')
        self.sheets = TD.sheets_from(HOLES_SHEET)
        self.n = len(self.sheets[0]['parts'])

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def log(self):
        with open(L.LOG_FILE, encoding='utf-8-sig') as f:
            return f.read()

    def read(self, d, cam=None):
        warn = []
        sh = R.collect(d, cam, None, warn)[0]
        return sh, warn

    def run_ops(self, d):
        cam = FK.CAM(d)
        s = FK.linked_setup(cam, 1)
        res = R.run(FK.App(d, cam), None, d, {}, None, TOOL, '1.0.1')
        return s, res


class Discovery(Base):
    def test_attributes_only_native(self):
        d = FK.build_design(self.sheets, attrs_on='native')
        sh, warn = self.read(d)
        self.assertEqual(len(sh['parts']), self.n, warn)
        self.assertEqual([p['name'] for p in sh['parts']], [p['name'] for p in self.sheets[0]['parts']])
        rec = sh['diag']['parts'][0]
        self.assertIn('nativeObject', rec['attributes'])
        self.assertNotIn('occurrence', rec['attributes'])
        self.assertTrue(all(not p['geo'].get('no_edges') for p in sh['parts']))
        lg = self.log()
        self.assertIn('Baum', lg)
        self.assertIn("nativeObject", lg)

    def test_native_via_parent_component(self):
        d = FK.build_design(self.sheets, attrs_on='native')
        for po in d.rootComponent.occurrences[0].childOccurrences:
            po.nativeObject = None                          # nur über rohteil.component.occurrences lesbar
        sh, _w = self.read(d)
        self.assertIn('rohteil.component.occurrences', sh['diag']['parts'][0]['attributes'])
        self.assertTrue(sh['parts'][0]['key'].startswith(self.sheets[0]['parts'][0]['id']))

    def test_nested_bodies_platte_and_stock(self):
        d = FK.build_design(self.sheets, nested=True, platte=True)
        sh, warn = self.read(d)
        self.assertEqual(len(sh['parts']), self.n, warn)
        skipped = [r for r in sh['diag']['parts'] if r['result'].startswith('übersprungen')]
        self.assertEqual(len(skipped), 1)
        self.assertIn('Platte', skipped[0]['occurrence'])
        for p, ref in zip(sh['parts'], self.sheets[0]['parts']):
            self.assertAlmostEqual(G.area(p['outer']), G.area(ref['outer']), 3)
        s, res = self.run_ops(d)
        self.assertEqual(res['errors'], 0)
        self.assertEqual(len(s.operations), self.n + 1)

    def test_no_attributes_with_project(self):
        d = FK.build_design(self.sheets, attrs_on='none', project=True)
        sh, warn = self.read(d)
        self.assertEqual(len(sh['parts']), self.n, warn)
        for r in sh['diag']['parts']:
            self.assertEqual(r.get('project_match'), 'Hüllbox')
        ids = sorted(p['key'].split('#')[0] for p in sh['parts'])
        self.assertEqual(ids, sorted(p['id'] for p in self.sheets[0]['parts']))
        self.assertIn('Projekt-Daten: %d Platzierungen' % self.n, self.log())

    def test_no_attributes_no_bbox_matched_by_geometry(self):
        d = FK.build_design(self.sheets, attrs_on='none', project=True, with_bbox=False)
        sh, _w = self.read(d)
        self.assertTrue(all(r.get('project_match', '').startswith('Geometrie') for r in sh['diag']['parts']))

    def test_no_attributes_no_project(self):
        d = FK.build_design(self.sheets, attrs_on='none')
        sh, _w = self.read(d)
        self.assertEqual(len(sh['parts']), self.n)
        self.assertEqual(sh['parts'][0]['name'], self.sheets[0]['parts'][0]['name'])   # Komponentenname

    def test_broken_brep_project_fallback(self):
        d = FK.build_design(self.sheets, project=True, broken=('Deckel',))
        sh, warn = self.read(d)
        deckel = next(p for p in sh['parts'] if p['name'] == 'Deckel')
        self.assertTrue(deckel['geo']['no_edges'])
        ref = next(p for p in self.sheets[0]['parts'] if p['name'] == 'Deckel')
        self.assertAlmostEqual(G.area(deckel['outer']), G.area(ref['outer']), 3)
        self.assertEqual(len(deckel['holes']), len(ref['holes']))
        lg = self.log()
        self.assertIn('keine ebene Fläche mit Normale ±Z', lg)
        self.assertIn('KEINE Kanten', lg)
        s, res = self.run_ops(d)
        names = [o.name for o in s.operations]
        self.assertFalse(any('Deckel' in n for n in names))
        self.assertEqual(len([n for n in names if 'Außen' in n]), self.n - 1)
        self.assertTrue(any('keine B-Rep-Kanten für Deckel' in w for w in res['warnings']))
        inner = s.operations[0]
        self.assertEqual(len(inner.parameters.itemByName('contours').value.applied),
                         sum(len(p['holes']) for p in self.sheets[0]['parts'] if p['name'] != 'Deckel'))

    def test_everything_broken_preview_only(self):
        names = tuple(p['name'] for p in self.sheets[0]['parts'])
        d = FK.build_design(self.sheets, attrs_on='none', project=True, broken=names, with_bbox=False)
        sh, warn = self.read(d)
        self.assertEqual(len(sh['parts']), self.n)
        self.assertTrue(all(p['geo']['no_edges'] for p in sh['parts']))
        self.assertTrue(any('Projekt-Daten (nur Vorschau' in w for w in warn))
        s, res = self.run_ops(d)
        self.assertEqual(len(s.operations), 0)
        self.assertTrue(res['previews'] and os.path.getsize(res['previews'][0]) > 5000)

    def test_rejected_reason_logged(self):
        names = tuple(p['name'] for p in self.sheets[0]['parts'])
        d = FK.build_design(self.sheets, broken=names)       # ohne Projekt: nichts zu retten
        sh, warn = self.read(d)
        self.assertEqual(sh['parts'], [])
        self.assertEqual(len(warn), self.n)
        self.assertIn('abgelehnt: keine ebene Fläche mit Normale ±Z', self.log())

    def test_face_choice_by_project(self):
        # 2.0.1: Unterseite kleiner (Falz ringsum) -> immer die Silhouette (= Oberseite), mit und ohne Projekt
        sq = [(100, 100), (500, 100), (500, 400), (100, 400)]
        small = [(110, 110), (490, 110), (490, 390), (110, 390)]
        b = FK.prism_body(sq, [], 15.0, (0, 0, 0))
        nb = FK.prism_body(small, [], 15.0, (0, 0, 0))
        b.faces[0] = nb.faces[0]
        occ = FK.Occ('Teil:1')
        occ.bRepBodies.append(b)
        for exp in (sq, small, None):
            g = F.part_geometry(occ, F.Frame(None), None, exp, [])
            self.assertEqual(g['side'], 'Silhouette')
            self.assertAlmostEqual(abs(G.area(g['outer']['pts'])), G.area(sq), 6)
            self.assertEqual(g['outer']['method'], 'kante')

    def test_cam_context_edges(self):
        d = FK.build_design(self.sheets)
        d_cam = FK.build_design(self.sheets)                  # eigener Modellkontext des CAM-Produkts
        cam = FK.CAM(d)
        cam.designRootOccurrence.childOccurrences = d_cam.rootComponent.occurrences
        s = FK.linked_setup(cam, 1)
        res = R.run(FK.App(d, cam), None, d, {}, None, TOOL, '1.0.1')
        self.assertEqual(res['errors'], 0)
        cam_edges = set()
        for po in d_cam.rootComponent.occurrences[0].childOccurrences:
            for f in po.bRepBodies[0].faces:
                for lp in f.loops:
                    cam_edges.update(id(ce.edge) for ce in lp.coEdges)
        for op in s.operations:
            for ch in op.parameters.itemByName('contours').value.applied:
                self.assertTrue(all(id(e) in cam_edges for e in ch.inputGeometry))
        self.assertIn('Kanten aus cam-Kontext', self.log())


class Tools(unittest.TestCase):
    def mk(self, n, d, typ='flat end mill', src='Lokal: Holz'):
        return {'label': 'T%d Ø %g' % (n, d), 'source': src, 'info': {'type': typ, 'd_mm': d, 'number': n}}

    def test_default_tool(self):
        tools = [self.mk(1, 6), self.mk(2, 8, 'ball end mill'), self.mk(3, 8), self.mk(4, 8, src='Dokument'),
                 self.mk(5, 12)]
        self.assertEqual(C.default_tool(tools), 3)
        self.assertEqual(C.default_tool(tools, 'T5 Ø 12'), 4)
        self.assertEqual(C.default_tool(tools, 'weg'), 3)
        self.assertEqual(C.default_tool(tools, None, 12.0), 4)
        self.assertIsNone(C.default_tool([]))

    def test_unique_labels(self):
        tools = [self.mk(1, 6), self.mk(1, 6), self.mk(1, 6)]
        C.unique_labels(tools)
        self.assertEqual(len(set(t['label'] for t in tools)), 3)


class Logging(unittest.TestCase):
    def test_bom_and_ascii_json(self):
        tmp = tempfile.mkdtemp()
        try:
            L.LOG_DIR, L.LOG_FILE = tmp, os.path.join(tmp, 'finalschnitt.log')
            with open(L.LOG_FILE, 'w', encoding='utf-8') as f:
                f.write('alt ohne BOM ä\n')
            L.info('Prüfung äöü')
            with open(L.LOG_FILE, 'rb') as f:
                raw = f.read()
            self.assertTrue(raw.startswith(b'\xef\xbb\xbf'))
            self.assertEqual(raw.count(b'\xef\xbb\xbf'), 1)
            self.assertIn('Prüfung äöü', raw.decode('utf-8-sig'))
            self.assertTrue(os.path.exists(L.LOG_FILE + '.1'))
            p = L.dump_json('t', {'a': 'Außen'})
            with open(p, 'rb') as f:
                b = f.read()
            self.assertTrue(all(c < 128 for c in b))
            self.assertEqual(json.loads(b)['a'], 'Außen')
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == '__main__':
    unittest.main()
