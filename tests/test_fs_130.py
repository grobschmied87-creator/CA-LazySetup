# -*- coding: utf-8 -*-
"""1.3.0: Rohteil-Definition aus ContourNest ≥ 1.10.0 – Ausrichtung längs/quer, Abschnitt, Nullpunkt (WCS)
je Rohteil, Projekt-Lagen im Maschinensystem, Vorschau wie auf dem Maschinentisch mit Nullpunkt."""
import json
import os
import shutil
import subprocess
import sys
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
import fs_edit as E       # noqa: E402
import fs_sheet as S      # noqa: E402

HOLES_SHEET = os.path.join(TD.ROOT, 'cn_logs3', 'apply_20261009_102512_483.json')
TOOL = {'tool': FK.Tool(3, 8.0, 'Spiralfräser 8'), 'info': {'d_mm': 8.0}, 'label': 'T3 Ø 8'}
CN_DIR = '/workspace/ContourNest'


def quer_project(design, sheets, zero='rh_oben', kind='abschnitt', sheet_no=1):
    """Projekt wie ContourNest 1.10.0: Rohteil sheet_no quer, Platzierungen im Maschinensystem."""
    a = design.attributes.itemByName('ContourNest', 'project_P1')
    proj = json.loads(a.value)
    width = sheets[sheet_no - 1]['width']
    for pl in proj['placements']:
        if pl['sheet'] == sheet_no:          # Material (x, y, rot) -> Maschine (Breite − y, x, rot + 90)
            pl['x'], pl['y'], pl['rot'] = width - pl['y'], pl['x'], (pl['rot'] + 90.0) % 360.0
    proj['coords'] = 'maschine'
    proj['sheets'] = [{'index': n + 1, 'orient': 'quer' if n + 1 == sheet_no else 'laengs',
                       'zero': zero if n + 1 == sheet_no else 'lu_unten',
                       'kind': kind if n + 1 == sheet_no else 'standard', 'grain': 'X'} for n in range(len(sheets))]
    design.attributes.add('ContourNest', 'project_P1', json.dumps(proj))
    return proj


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        L.LOG_DIR = self.tmp
        L.LOG_FILE = os.path.join(self.tmp, 'finalschnitt.log')
        self.sheets = TD.sheets_from(HOLES_SHEET)
        self.design = FK.build_design(self.sheets, project=True, attrs_on='none')
        self.cam = FK.CAM(self.design)
        self.app = FK.App(self.design, self.cam)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


class SheetInfo(unittest.TestCase):
    def test_old_data_defaults(self):
        r = S.sheet_info({'index': 2, 'length_mm': 2800, 'width_mm': 2070, 'thickness_mm': 19})
        self.assertEqual((r['orient'], r['zero'], r['box_point'], r['W'], r['H']), ('laengs', 'lu_unten', 'bottom 1', 2800, 2070))
        self.assertFalse(r['zero_explicit'])
        self.assertEqual(r['label'], 'Rohteil 02: 2800 × 2070 × 19 mm, längs, Faser X, Standard | Nullpunkt: unten links, Unterseite')
        self.assertEqual(S.sheet_info({}, None, 'mitte_oben')['box_point'], 'top center')

    def test_project_overrides_attribute(self):
        a = {'index': 1, 'length_mm': 1400, 'width_mm': 900, 'thickness_mm': 18, 'orient': 'laengs', 'zero': 'lu_unten'}
        r = S.sheet_info(a, {'index': 1, 'orient': 'quer', 'zero': 'rh_oben', 'kind': 'abschnitt', 'grain': 'Y'})
        self.assertEqual((r['W'], r['H'], r['grain_axis'], r['box_point']), (900, 1400, 'X', 'top 4'))
        self.assertEqual((r['zero_x'], r['zero_y'], r['zero_z'], r['zero_u'], r['zero_v']), (900, 1400, 18, 1400, 0))
        self.assertTrue(r['zero_explicit'])
        self.assertEqual(r['label'], 'Rohteil 01: 900 × 1400 × 18 mm, quer, Faser X, Abschnitt | Nullpunkt: oben rechts, Oberseite')

    def test_zero_mapping_all_keys_after_rotation(self):
        """Nullpunkt bleibt an der Tischecke: Maschinenlage aus dem Schlüssel, Material per Umkehrung."""
        for z in S.ZERO_KEYS:
            for o in ('laengs', 'quer'):
                r = S.sheet_info({'length_mm': 2500, 'width_mm': 1250, 'thickness_mm': 15}, {'orient': o, 'zero': z})
                m = S.to_machine((r['zero_u'], r['zero_v']), r)
                self.assertAlmostEqual(m[0], r['zero_x'], 9)
                self.assertAlmostEqual(m[1], r['zero_y'], 9)
                c = z.split('_')[0]
                self.assertEqual(r['zero_x'], {'lu': 0, 'lh': 0, 'ru': r['W'], 'rh': r['W'], 'mitte': r['W'] / 2}[c])
                self.assertEqual(r['zero_y'], {'lu': 0, 'ru': 0, 'lh': r['H'], 'rh': r['H'], 'mitte': r['H'] / 2}[c])
                self.assertEqual(r['box_point'].split()[0], 'top' if z.endswith('oben') else 'bottom')
                b = S.to_material(m, r)
                self.assertAlmostEqual(b[0], r['zero_u'], 9)
                self.assertAlmostEqual(b[1], r['zero_v'], 9)

    @unittest.skipUnless(os.path.isdir(CN_DIR), 'ContourNest-Quelle nicht vorhanden')
    def test_same_label_and_zero_as_contournest(self):
        sys.path.insert(0, '/workspace')
        import ContourNest.cn_geom as CG
        std = {'length': 2800, 'width': 2070, 'thickness': 19, 'frame': 10, 'grain': 'X'}
        for o in ('laengs', 'quer'):
            for z in S.ZERO_KEYS:
                for kind in ('standard', 'abschnitt'):
                    d = {'kind': kind, 'orient': o, 'zero': z, 'length': 1234.5, 'width': 987, 'grain': 'Y', 'thickness': 18.25}
                    gm = CG.resolve_sheet(d, std, 'MDF')
                    attr = {'index': 3, 'length_mm': gm['length'], 'width_mm': gm['width'], 'thickness_mm': gm['thickness'],
                            'orient': gm['orient'], 'zero': gm['zero'], 'kind': gm['kind'], 'grain': gm['grain']}
                    r = S.sheet_info(attr)
                    self.assertEqual(r['label'], CG.sheet_label(gm, 3))
                    zp = CG.zero_point(gm)
                    self.assertEqual((r['zero_x'], r['zero_y'], r['zero_u'], r['zero_v']), (zp['x'], zp['y'], zp['u'], zp['v']))
                    self.assertEqual(r['box_point'], CG.zero_box_point(gm['zero']))


class ReadQuer(Base):
    def test_project_parts_converted_to_material(self):
        quer_project(self.design, self.sheets)
        sh = R.collect(self.design, self.cam)[0]
        self.assertEqual((sh['orient'], sh['zero'], sh['box_point'], sh['W'], sh['H']), ('quer', 'rh_oben', 'top 4', 1250.0, 2500.0))
        self.assertTrue(sh['label'].startswith('Rohteil 01: 1250 × 2500 × 15 mm, quer, Faser Y, Abschnitt | Nullpunkt: oben rechts'))
        self.assertEqual(len(sh['parts']), len(self.sheets[0]['parts']))
        recs = sh['diag']['parts']
        self.assertTrue(all(r.get('project_match') for r in recs if r.get('result') == 'ok'), recs)
        self.assertTrue(all('Silhouette' in r.get('geometry', '') and 'Projekt-Daten' not in r.get('geometry', '') for r in recs if r.get('result') == 'ok'),
                        [r.get('geometry') for r in recs])
        for got, ref in zip(sh['parts'], self.sheets[0]['parts']):
            for a, b in zip(G.bbox(got['outer']), G.bbox(ref['outer'])):
                self.assertAlmostEqual(a, b, 6)
        pp = F.project_parts(F.load_project(self.design, 'P1'), 1, sh['sheet_info'])
        for q in pp:                                         # Projekt -> Material == Testdaten
            ref = next(p for p in self.sheets[0]['parts'] if p['id'] == q['id'] and p['_copy'] == q['copy'])
            for a, b in zip(G.bbox(q['outer']), G.bbox(ref['outer'])):
                self.assertAlmostEqual(a, b, 6)

    def test_old_project_unchanged(self):
        sh = R.collect(self.design, self.cam)[0]
        self.assertEqual((sh['orient'], sh['box_point'], sh['zero_explicit']), ('laengs', 'bottom 1', False))
        self.assertTrue(all('Silhouette' in r.get('geometry', '') and 'Projekt-Daten' not in r.get('geometry', '') for r in sh['diag']['parts'] if r.get('result') == 'ok'))


class CamWcs(Base):
    def run_fs(self, ask):
        return R.run(self.app, None, self.design, {}, None, TOOL, '1.3.0', ask)

    def test_new_setup_uses_sheet_zero_and_machine_box(self):
        quer_project(self.design, self.sheets)
        res = self.run_fs(lambda sh: True)
        self.assertEqual(res['errors'], 0, res)
        s1 = [s for s in self.cam.setups if s.name == 'ContourNest Rohteil 01'][0]
        self.assertEqual(s1.parameters.itemByName('wcs_origin_boxPoint').value.value, 'top 4')
        sh = dict(R.collect(self.design, self.cam)[0])
        self.assertEqual(C.machine_dims(sh), (1250.0, 2500.0, 15.0))

    def test_existing_setup_adjusted_only_with_explicit_zero(self):
        res = self.run_fs(lambda sh: True)                   # alte Daten: bottom 1
        s1 = [s for s in self.cam.setups if s.name == 'ContourNest Rohteil 01'][0]
        p = s1.parameters.itemByName('wcs_origin_boxPoint')
        p.value.value = 'top center'                         # Anwender hat im Setup umgestellt
        res = self.run_fs(lambda sh: self.fail('nicht neu anlegen'))
        self.assertEqual(p.value.value, 'top center', 'ältere Daten: vorhandenes Setup bleibt unangetastet')
        quer_project(self.design, self.sheets, zero='lu_oben')
        res = self.run_fs(lambda sh: self.fail('nicht neu anlegen'))
        self.assertEqual(p.value.value, 'top 1')
        self.assertTrue(any('Setup angepasst: Nullpunkt top center → top 1' in ln for ln in res['lines']), res['lines'])
        res = self.run_fs(lambda sh: self.fail('nicht neu anlegen'))
        self.assertFalse(any('Setup angepasst' in ln for ln in res['lines']), 'zweiter Lauf: nichts mehr zu ändern')

    def test_fixed_box_stock_machine_dims(self):
        quer_project(self.design, self.sheets)
        sh = R.collect(self.design, self.cam)[0]
        for o in sh['cam_occ'].bRepBodies:                   # ohne Körper „Rohteil“ -> feste Box
            o.name = 'Anderes'
        setup = C.create_simple_setup(self.cam, sh, '1.3.0')
        self.assertEqual([setup.parameters.itemByName('job_stockFixed%s' % a).expression for a in 'XYZ'],
                         ['1250 mm', '2500 mm', '15 mm'])
        self.assertEqual(setup.parameters.itemByName('wcs_origin_boxPoint').value.value, 'top 4')


class Preview(Base):
    def test_png_machine_orientation_with_zero(self):
        quer_project(self.design, self.sheets, zero='lu_unten')
        sh = R.collect(self.design, self.cam)[0]
        plan = R.make_plan(sh, R.plan_cfg({}, TOOL))
        self.assertEqual((plan['sheet']['orient'], plan['sheet']['W'], plan['sheet']['zero_x']), ('quer', 1250.0, 0.0))
        h = G._plan_height(plan, 900)
        self.assertGreater(h, 900 * 1.8, 'quer: Bild hochkant (Länge entlang Y)')
        cv = G.Canvas(900, h)
        G._draw_plan(cv, plan, 0, 0, 900)
        # Nullpunkt unten links: rotes X-Achsenstück rechts vom Ursprung (12 px Rand)
        x0, y0 = 12, h - 12
        red = [cv.px[3 * ((y0) * cv.w + x)] for x in range(x0 + 12, x0 + 30)]
        grn = [cv.px[3 * ((y - 0) * cv.w + x0) + 1] for y in range(y0 - 30, y0 - 12)]
        self.assertTrue(any(v >= 200 for v in red), 'X-Pfeil rot am Nullpunkt')
        self.assertTrue(any(v >= 130 for v in grn), 'Y-Pfeil grün am Nullpunkt')
        path = G.render_preview(plan, os.path.join(self.tmp, 'q.png'))
        self.assertTrue(os.path.getsize(path) > 1000)
        # Teile liegen im Bild innerhalb der gedrehten Platte
        Lm, Wm, mach, _ = G.machine_view(plan['sheet'])
        for p in plan['parts']:
            for q in p['outer']:
                m = mach(q)
                self.assertTrue(-1e-6 <= m[0] <= Lm + 1e-6 and -1e-6 <= m[1] <= Wm + 1e-6)

    def test_palette_payload_has_orientation_and_zero(self):
        quer_project(self.design, self.sheets, zero='mitte_oben')
        sh = R.collect(self.design, self.cam)[0]
        j = E.plan_json(R.make_plan(sh, R.plan_cfg({}, TOOL)), [sh['name']])
        self.assertEqual((j['sheet']['orient'], j['sheet']['zero_x'], j['sheet']['zero_y'], j['sheet']['zero_side']),
                         ('quer', 625.0, 1250.0, 'oben'))
        self.assertIn('Nullpunkt: Mitte, Oberseite', j['sheet']['label'])

    def test_palette_js(self):
        out = subprocess.run(['node', os.path.join(HERE, 'js', 'test_fs_logic.js')], capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn('JS OK', out.stdout)


if __name__ == '__main__':
    unittest.main()
