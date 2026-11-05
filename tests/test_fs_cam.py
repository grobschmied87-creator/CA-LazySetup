# -*- coding: utf-8 -*-
"""CAM-Ablauf mit Fakes (adsk.cam-Stub + tests/fsfake.py) und echten Konturen."""
import glob
import json
import os
import shutil
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
import fsfake as FK       # noqa: E402  (setzt sys.path auf Stubs)
import fs_testdata as TD  # noqa: E402
import fs_log as L        # noqa: E402
import fs_geom as G       # noqa: E402
import fs_fusion as F     # noqa: E402
import fs_cam as C        # noqa: E402
import fs_run as R        # noqa: E402

HOLES_SHEET = os.path.join(TD.ROOT, 'cn_logs3', 'apply_20261009_102512_483.json')
TOOL = {'tool': FK.Tool(3, 8.0, 'Spiralfräser 8'), 'info': {'d_mm': 8.0}, 'label': 'T3 Ø 8'}


def P(op, name):
    return op.parameters.itemByName(name)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        L.LOG_DIR = self.tmp
        L.LOG_FILE = os.path.join(self.tmp, 'finalschnitt.log')
        self.sheets = TD.sheets_from(HOLES_SHEET)
        self.design = FK.build_design(self.sheets)
        self.cam = FK.CAM(self.design)
        self.app = FK.App(self.design, self.cam)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_fs(self, cfg=None, tool=TOOL, ask=None, names=None):
        return R.run(self.app, None, self.design, cfg or {}, names, tool, '1.0.0', ask)


class ReadDesign(Base):
    def test_read_sheet_matches_testdata(self):
        sh = R.collect(self.design, self.cam)[0]
        self.assertEqual(sh['context'], 'cam')
        self.assertEqual((sh['length'], sh['width'], sh['thickness']), (2500.0, 1250.0, 15.0))
        self.assertEqual(len(sh['parts']), len(self.sheets[0]['parts']))
        for got, ref in zip(sh['parts'], self.sheets[0]['parts']):
            self.assertEqual(got['name'], ref['name'])
            self.assertAlmostEqual(G.area(got['outer']), G.area(ref['outer']), 3)
            self.assertEqual(len(got['holes']), len(ref['holes']))
            bb, rb = G.bbox(got['outer']), G.bbox(ref['outer'])
            for a, b in zip(bb, rb):
                self.assertAlmostEqual(a, b, 6)                       # Welt -> Rohteil-Koordinaten
            self.assertAlmostEqual(got['geo']['z_bottom'], 0.0, 9)
        plan_d = G.plan_sheet(sh)
        plan_t = G.plan_sheet(self.sheets[0])
        self.assertEqual([plan_d['parts'][i]['name'] for i in plan_d['order']],
                         [plan_t['parts'][i]['name'] for i in plan_t['order']])

    def test_chain_reverted(self):
        sq = [(0, 0), (10, 0), (10, 10), (0, 10)]          # CCW
        self.assertTrue(F.chain_reverted(sq, False, want_cw=True))
        self.assertFalse(F.chain_reverted(sq, True, want_cw=True))
        self.assertFalse(F.chain_reverted(sq[::-1], False, want_cw=True))
        self.assertFalse(F.chain_reverted(sq, False, want_cw=False))

    def test_pockets_read(self):
        pk = {'Deckel': [([(200, 900), (300, 900), (300, 950), (200, 950)], 5.0)]}
        d = FK.build_design(self.sheets, pockets=pk)
        sh = R.collect(d)[0]
        deckel = next(p for p in sh['parts'] if p['name'] == 'Deckel')
        self.assertEqual(len(deckel['pockets']), 1)
        self.assertAlmostEqual(deckel['geo']['pockets'][0]['depth'], 5.0, 6)


class Operations(Base):
    def test_full_run(self):
        s = FK.linked_setup(self.cam, 1)
        s.operations.add(FK.OpInput('contour2d'))                 # fremde Operation bleibt
        s.operations[-1].name = 'Planfräsen'
        old = s.operations.add(FK.OpInput('contour2d'))
        old.name = 'FS 09 alt'
        res = self.run_fs({'berechnen': True})
        self.assertEqual(res['errors'], 0, res)
        names = [o.name for o in s.operations]
        self.assertEqual(names[0], 'Planfräsen')
        self.assertNotIn('FS 09 alt', names)
        self.assertEqual(names[1], 'FS 01 Innen')
        plan = G.plan_sheet(self.sheets[0])
        exp = ['FS %02d Außen – %s' % (k + 2, plan['parts'][i]['name']) for k, i in enumerate(plan['order'])]
        self.assertEqual(names[2:], exp)
        self.assertIn('1 alte FS-Operationen ersetzt', res['lines'][0])
        self.assertEqual(len(self.cam.generated), 1)
        self.assertEqual(len(self.cam.generated[0]), len(exp) + 1)
        inner = s.operations[1]
        self.assertEqual(len(P(inner, 'contours').value.applied), 9)
        self.assertTrue(P(inner, 'preserveOrder').value.value)
        self.assertFalse(P(inner, 'group_tabs').value.value)
        for op in s.operations[2:]:
            self.assertIs(op.tool, TOOL['tool'])
            self.assertEqual(P(op, 'compensation').value.value, 'left')
            self.assertEqual(P(op, 'bottomHeight_mode').value.value, 'from stock bottom')
            self.assertAlmostEqual(P(op, 'bottomHeight_offset').value.value, -0.03)
            self.assertTrue(P(op, 'doMultipleDepths').value.value)
            self.assertAlmostEqual(P(op, 'maximumStepdown').value.value, 0.3)  # az_final default 3 mm
            self.assertFalse(P(op, 'useStockToLeave').value.value)
            self.assertEqual(len(P(op, 'entryPositions').value.value), 1)
            ch = P(op, 'contours').value.applied
            self.assertEqual(len(ch), 1)
            meta = json.loads(op.attributes.itemByName('Finalschnitt', 'op').value)
            self.assertEqual(meta['kind'], 'aussen')
        # Werkzeugseite: Außenkontur im Uhrzeigersinn, erste Kante der Unterseite (Fake) gegenläufig
        sh = R.collect(self.design, self.cam)[0]
        p0 = sh['parts'][0]['geo']['outer']
        ccw_edge = (G.signed_area(p0['pts']) > 0) != p0['first_opposed']
        op0 = next(o for o in s.operations if o.name.endswith(sh['parts'][0]['name']))
        self.assertEqual(P(op0, 'contours').value.applied[0].isReverted, ccw_edge)
        # Stege = Skizzenpunkte, Anzahl wie geplant
        tabs_total = sum(len(P(o, 'tabPositions').value.value) for o in s.operations[2:])
        self.assertEqual(tabs_total, sum(len(p['tabs']) for p in plan['parts']))
        comp = sh['occ'].component
        sk = {k.name: k for k in comp.sketches}
        # 1.1.0: berechnete Punkte NUR in „… (berechnet)“; Anwender-Skizzen werden nicht angelegt
        self.assertIn(C.SK_START_OUT, sk)
        self.assertIn(C.SK_TABS_OUT, sk)
        self.assertNotIn(C.SK_START, sk)
        self.assertNotIn(C.SK_TABS, sk)
        self.assertEqual(len(sk[C.SK_TABS_OUT].sketchPoints) - 1, tabs_total)
        n_starts = len(plan['order']) + sum(len(p.get('hole_starts') or []) for p in plan['parts'])
        # 2.0.5: Außen-Starts + Innenkanten-Starts in derselben Skizze
        self.assertEqual(len(sk[C.SK_START_OUT].sketchPoints) - 1, n_starts)
        ep = P(s.operations[2], 'entryPositions').value.value[0]
        self.assertIs(ep.context, sh['cam_occ'])
        # Parameterliste + Plan + Vorschau im Protokoll
        dumps = glob.glob(os.path.join(self.tmp, 'params_contour2d_*.json'))
        self.assertEqual(len(dumps), 1)
        with open(dumps[0], encoding='utf-8') as f:
            d = json.load(f)
        self.assertEqual(d['count'], len(FK.CONTOUR2D))
        self.assertIn('choices', next(p for p in d['parameters'] if p['name'] == 'tabShape'))
        self.assertTrue(glob.glob(os.path.join(self.tmp, 'plan_*.json')))
        self.assertTrue(glob.glob(os.path.join(self.tmp, 'preview_*.png')))

    def test_rerun_replaces(self):
        s = FK.linked_setup(self.cam, 1)
        self.run_fs()
        n = len(s.operations)
        self.run_fs()
        self.assertEqual(len(s.operations), n)
        comp = R.collect(self.design)[0]['occ'].component
        self.assertEqual(sum(1 for k in comp.sketches if k.name == C.SK_TABS_OUT), 1)
        self.run_fs({'ersetzen': False})
        self.assertEqual(len(s.operations), 2 * n)

    def test_options(self):
        s = FK.linked_setup(self.cam, 1)
        self.run_fs({'schlichtgang': True, 'schlicht_zugabe': 0.5, 'richtung': 'gegen', 'zustellung': 20,
                     'steg_form': 'dreieckig', 'berechnen': False})
        names = [o.name for o in s.operations]
        self.assertTrue(names[1].startswith('FS 02 Außen'))
        self.assertTrue(names[2].startswith('FS 03 Schlicht'))
        self.assertEqual(names[1].split('– ')[1], names[2].split('– ')[1])
        r, f = s.operations[1], s.operations[2]
        self.assertEqual(len(P(f, 'tabPositions').value.value), len(P(r, 'tabPositions').value.value))
        self.assertTrue(P(r, 'useStockToLeave').value.value)
        self.assertAlmostEqual(P(r, 'stockToLeave').value.value, 0.05)
        self.assertFalse(P(f, 'useStockToLeave').value.value)
        self.assertFalse(P(r, 'doMultipleDepths').value.value)      # 20 mm > 15,3 mm
        self.assertEqual(P(r, 'compensation').value.value, 'right')
        self.assertEqual(P(r, 'tabShape').value.value, 'triangular')
        self.assertEqual(self.cam.generated, [])

    def test_inner_per_part_and_single_op(self):
        s = FK.linked_setup(self.cam, 1)
        self.run_fs({'innen_zuerst': False})
        names = [o.name for o in s.operations]
        self.assertNotIn('FS 01 Innen', names)
        k = next(i for i, n in enumerate(names) if n.startswith('FS') and 'Innen –' in n)
        self.assertIn('Außen', names[k + 1])
        self.assertEqual(names[k].split('– ')[1], names[k + 1].split('– ')[1])
        s2 = FK.linked_setup(FK.CAM(self.design), 1)
        cam2 = s2.cam
        app2 = FK.App(self.design, cam2)
        R.run(app2, None, self.design, {'gruppierung': 'eine'}, None, TOOL, '1.0.0')
        names2 = [o.name for o in s2.operations]
        self.assertEqual(names2, ['FS 01 Innen', 'FS 02 Außen – alle Teile'])
        op = s2.operations[1]
        self.assertEqual(len(P(op, 'contours').value.applied), 6)
        self.assertTrue(P(op, 'preserveOrder').value.value)
        self.assertEqual(len(P(op, 'entryPositions').value.value), 6)

    def test_tab_fallback_and_missing_params(self):
        s = FK.linked_setup(self.cam, 1)
        self.cam.missing = {'tabPositions', 'preserveOrder'}
        res = self.run_fs()
        op = s.operations[2]
        self.assertEqual(P(op, 'tabPositioning').value.value, 'distance')
        self.assertGreater(P(op, 'tabDistance').value.value, 0)
        self.assertTrue(any('tabPositions' in w for w in res['warnings']))
        with open(L.LOG_FILE, encoding='utf-8') as f:
            self.assertIn('Rückfall auf Stegabstand', f.read())

    def test_errors_do_not_stop(self):
        s = FK.linked_setup(self.cam, 1)
        self.cam.fail_add = 'Deckel'
        self.cam.failing = {'maximumStepdown'}
        res = self.run_fs()
        names = [o.name for o in s.operations]
        self.assertFalse(any('Deckel' in n for n in names))
        self.assertEqual(len(names), 6)                          # Innen + 5 von 6 Außen
        self.assertEqual(res['errors'], 1)
        self.assertTrue(any('Deckel' in w for w in res['warnings']))
        self.assertTrue(any('maximumStepdown' in w for w in res['warnings']))

    def test_missing_setup(self):
        res = self.run_fs(ask=lambda sh: False)
        self.assertEqual(res['ops'], 0)
        self.assertTrue(any('kein CAM-Setup' in w for w in res['warnings']))
        asked = []
        res = self.run_fs(ask=lambda sh: asked.append(sh['name']) or True)
        self.assertEqual(asked, ['Rohteil 01:1'])
        s = self.cam.setups[0]
        self.assertEqual(s.name, 'ContourNest Rohteil 01')
        self.assertEqual(s.stockMode, 6)
        self.assertEqual(s.parameters.itemByName('wcs_origin_boxPoint').value.value, 'bottom 1')
        self.assertEqual(json.loads(s.attributes.itemByName('ContourNest', 'cam_link').value)['project_sheet'], 1)
        self.assertGreater(res['ops'], 0)
        res = self.run_fs(ask=lambda sh: self.fail('nicht erneut fragen'))
        self.assertGreater(res['ops'], 0)

    def test_no_cam_never_raises(self):
        app = FK.App(self.design, None)
        app.activeDocument.products.cam = None
        res = R.run(app, None, self.design, {}, None, TOOL, '1.0.0')
        self.assertIn('Kein CAM-Produkt', res['lines'][0])
        res = R.run(self.app, None, FK.Design(), {}, None, TOOL, '1.0.0')
        self.assertIn('Keine ContourNest-Rohteile', res['lines'][0])
        res = R.run(self.app, None, None, {}, None, TOOL, '1.0.0')
        self.assertEqual(res['ops'], 0)

    def test_manual_sketch_points(self):
        s = FK.linked_setup(self.cam, 1)
        self.run_fs()
        sh = R.collect(self.design)[0]
        comp = sh['occ'].component
        tabs_sk = comp.sketches.add(comp.xYConstructionPlane)     # Anwender legt Skizze selbst an
        tabs_sk.name = C.SK_TABS
        deckel = next(p for p in sh['parts'] if p['name'] == 'Deckel')
        bb = G.bbox(deckel['outer'])
        mx = (bb[0] + bb[2]) / 2
        import adsk.core as core
        tabs_sk.sketchPoints.add(core.Point3D.create(mx / 10, bb[1] / 10, 0))
        res = self.run_fs({'skizze_stege': True})
        op = next(o for o in s.operations if o.name.endswith('Deckel'))
        self.assertEqual(len(P(op, 'tabPositions').value.value), 1)
        self.assertEqual(len(tabs_sk.sketchPoints), 2, 'Anwender-Skizze unverändert')
        self.assertFalse(any(k.name == C.SK_TABS + ' (intern)' for k in comp.sketches))
        self.assertEqual(res['errors'], 0)
        self.assertTrue(any('Steg-Einstellungen wirkungslos' in w for w in res['warnings']), res['warnings'])

    def test_sketch_feedback_loop(self):
        """1.0.6-Fehler: berechnete Stege landeten in der Skizze, die „Stege aus Skizze“ liest -> eingefroren.
        Ab 1.1.0 wird die berechnete Skizze nie gelesen: mit „aus Skizze“ ohne Anwender-Skizze -> berechnet,
        und Steg-Einstellungen wirken weiterhin."""
        FK.linked_setup(self.cam, 1)
        self.run_fs({'steg_abstand_mittel': 500.0})
        sh = R.collect(self.design)[0]
        comp = sh['occ'].component
        out1 = len(next(k for k in comp.sketches if k.name == C.SK_TABS_OUT).sketchPoints)
        self.assertEqual(R.sketch_inputs(sh, dict(G.DEFAULTS, skizze_stege=True))['tabs'], [])
        res = self.run_fs({'skizze_stege': True, 'steg_abstand_mittel': 250.0})
        self.assertTrue(any('keine Stegpunkte in Skizze' in w for w in res['warnings']))
        out2 = len(next(k for k in comp.sketches if k.name == C.SK_TABS_OUT).sketchPoints)
        self.assertGreater(out2, out1, 'mehr Stege bei kleinerem Abstand – Einstellung wirkt')
        self.assertFalse(any(k.name == C.SK_TABS for k in comp.sketches))

    def test_pocket_op(self):
        pk = {'Deckel': [([(200, 900), (300, 900), (300, 950), (200, 950)], 5.0)]}
        d = FK.build_design(self.sheets, pockets=pk)
        cam = FK.CAM(d)
        s = FK.linked_setup(cam, 1)
        R.run(FK.App(d, cam), None, d, {'taschen': True}, None, TOOL, '1.0.0')
        self.assertEqual(s.operations[0].name, 'FS 01 Taschen')
        self.assertEqual(s.operations[0].strategy, 'pocket2d')
        self.assertEqual(len(P(s.operations[0], 'pockets').value.applied[0].inputGeometry), 1)


class Tools(Base):
    def test_list_tools(self):
        self.cam.documentToolLibrary = FK.Coll([FK.Tool(1, 6.0, 'Dok 6'), FK.Tool(9, 10.0, 'Bohrer', 'drill')])
        FK_lib = {'local/Holz': [FK.Tool(3, 8.0, 'Spirale 8'), FK.Tool(4, 12.0, 'Spirale 12')],
                  'local/Ordner/Alu': [FK.Tool(5, 4.0, 'Alu 4')]}
        import adsk.cam
        adsk.cam.CAMManager._lm = FK.LibraryManager(FK_lib)
        tools = C.list_tools(self.cam)
        labels = [t['label'] for t in tools]
        self.assertEqual(len(tools), 4, labels)                      # Bohrer gefiltert
        self.assertTrue(labels[0].startswith('T1 Ø 6 mm Dok 6 – Dokument'))
        self.assertTrue(any('Lokal: Holz' in lb for lb in labels))
        self.assertTrue(any('Lokal: Alu' in lb for lb in labels))
        self.assertEqual(C.tool_by_number(tools, 4)['info']['d_mm'], 12.0)
        self.assertIsNone(C.tool_by_number(tools, 77))
        adsk.cam.CAMManager._lm = None
        self.assertEqual(len(C.list_tools(self.cam)), 1)              # Bibliotheken kaputt -> nur Dokument

    def test_tool_diameter_used_for_plan(self):
        FK.linked_setup(self.cam, 1)
        t12 = {'tool': FK.Tool(4, 12.0, 'x'), 'info': {'d_mm': 12.0}, 'label': 'T4'}
        self.run_fs(tool=t12)
        files = sorted(glob.glob(os.path.join(self.tmp, 'plan_*.json')))
        with open(files[-1], encoding='utf-8') as f:
            self.assertEqual(json.load(f)['cfg']['tool_d'], 12.0)


if __name__ == '__main__':
    unittest.main()
