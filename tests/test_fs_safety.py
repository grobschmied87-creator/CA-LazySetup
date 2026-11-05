# -*- coding: utf-8 -*-
"""1.0.2: Lehren aus dem ContourNest-Absturz (Fusion 2705) + Auswahlwerte mit Hochkommas."""
import os
import shutil
import tempfile
import unittest

import fsfake as FK       # noqa: E402  (setzt sys.path auf Stubs)
import fs_testdata as TD  # noqa: E402
import fs_log as L        # noqa: E402
import fs_cam as C        # noqa: E402
import fs_run as R        # noqa: E402

HOLES_SHEET = os.path.join(TD.ROOT, 'cn_logs3', 'apply_20261009_102512_483.json')
TOOL = {'tool': FK.Tool(3, 8.0, 'Spiralfräser 8'), 'info': {'d_mm': 8.0}, 'label': 'T3 Ø 8'}


class QuotedValue:
    """Fusion 2705: getChoices() liefert Werte MIT Hochkommas; value.value ohne."""
    def __init__(self, choices, v):
        self.choices, self.value = choices, v

    def getChoices(self):
        q = ["'%s'" % c for c in self.choices]
        return True, q, q


class QuotedParam:
    def __init__(self, choices, v):
        self.value = QuotedValue(choices, v)
        self.sets = 0

    @property
    def expression(self):
        return "'%s'" % self.value.value

    @expression.setter
    def expression(self, e):
        self.sets += 1
        v = e[1:-1] if e[:1] == e[-1:] == "'" else e
        if v not in self.value.choices:
            raise RuntimeError('3 : Invalid enumeration value.')
        self.value.value = v


class Params:
    def __init__(self, **d):
        self.d = d

    def itemByName(self, n):
        return self.d.get(n)


class Choices(unittest.TestCase):
    def test_quoted_choices(self):
        p = QuotedParam(['modelOrigin', 'stockPoint', 'modelPoint'], 'modelOrigin')
        rec = {}
        v = C.set_choice(Params(wcs_origin_mode=p), 'wcs_origin_mode', 'stockPoint', ('stock',), rec)
        self.assertEqual(v, 'stockPoint')
        self.assertTrue(rec['wcs_origin_mode']['ok'])
        self.assertNotIn('expr_error', rec['wcs_origin_mode'])
        self.assertEqual(rec['wcs_origin_mode']['choices'], ['modelOrigin', 'stockPoint', 'modelPoint'])

    def test_quoted_want_and_keys(self):
        p = QuotedParam(['center', 'offset from left'], 'center')
        rec = {}
        self.assertEqual(C.set_choice(Params(x=p), 'x', "'offset from left'", (), rec), 'offset from left')
        p2 = QuotedParam(['modelOrientation', 'axesXY'], 'axesXY')
        self.assertEqual(C.set_choice(Params(y=p2), 'y', 'orientation_model', ('model',), rec), 'modelOrientation')

    def test_unchanged_not_set_again(self):
        p = QuotedParam(['a', 'b'], 'b')
        rec = {}
        self.assertEqual(C.set_choice(Params(z=p), 'z', 'b', (), rec), 'b')
        self.assertEqual(p.sets, 0)
        self.assertTrue(rec['z']['unchanged'])

    def test_unq(self):
        self.assertEqual(C.unq("'x y'"), 'x y')
        self.assertEqual(C.unq('"x"'), 'x')
        self.assertEqual(C.unq("x"), 'x')
        self.assertEqual(C.unq(3), 3)


class Safety(unittest.TestCase):
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
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_fs(self, cfg=None):
        return R.run(self.app, None, self.design, cfg or {}, None, TOOL, '1.0.2', None)

    def log(self):
        with open(L.LOG_FILE, encoding='utf-8-sig') as f:
            return f.read()

    def test_no_toolpath_by_default(self):
        res = self.run_fs()
        self.assertGreater(res['ops'], 0)
        self.assertEqual(self.cam.generated, [])
        self.assertTrue(any('nicht berechnet' in ln for ln in res['lines']))
        res = self.run_fs({'berechnen': True})
        self.assertEqual(len(self.cam.generated), 1)
        self.assertIn('CP    cam.generateToolpath', self.log())

    def test_compute_failure_no_cam_change(self):
        self.run_fs()
        n = len(self.setup.operations)
        names = [o.name for o in self.setup.operations]
        del FK.EVENTS[:]
        self.design.fail_compute = True
        res = self.run_fs()
        self.assertEqual([o.name for o in self.setup.operations], names)
        self.assertEqual(len(self.setup.operations), n)
        self.assertEqual([e[0] for e in FK.EVENTS], ['compute'])
        self.assertTrue(res['lines'][0].startswith('Abbruch vor jeder CAM-Änderung'))

    def test_replace_deletes_ops_before_geometry(self):
        self.run_fs()
        n_fs = sum(1 for o in self.setup.operations if o.name.startswith('FS '))
        del FK.EVENTS[:]
        res = self.run_fs()
        self.assertEqual(res['errors'], 0, res)
        kinds = [e[0] for e in FK.EVENTS]
        self.assertEqual(kinds[0], 'compute')
        last_op = max(i for i, k in enumerate(kinds) if k == 'op_delete')
        first_sk = min(i for i, k in enumerate(kinds) if k == 'sketch_delete')
        self.assertEqual(kinds.count('op_delete'), n_fs)
        self.assertLess(last_op, first_sk, 'alte FS-Operationen VOR den Skizzen gelöscht')
        txt = self.log()
        i_op = txt.index('CP    FS-Operation löschen')
        i_sk = txt.index('CP    Skizze', i_op)
        i_new = txt.index('CP    Operation anlegen', i_sk)
        self.assertTrue(i_op < i_sk < i_new)
        self.assertIn('CP    design.computeAll() vor CAM-Änderungen', txt)
        self.assertIn('Konturauswahl contours', txt)

    def test_fs_ops_of_sheet_in_other_setup_deleted(self):
        self.run_fs()
        other = FK.linked_setup(self.cam, 9)
        moved = self.setup.operations[0]
        self.setup.operations.remove(moved)
        moved.setup = other
        other.operations.append(moved)
        foreign = other.operations.add(FK.OpInput('contour2d'))
        foreign.name = 'FS 77 fremd'          # FS-Name, aber anderes Rohteil laut Attribut -> bleibt
        foreign.attributes.add('Finalschnitt', 'op', '{"sheet": "anderes"}')
        self.run_fs()
        self.assertNotIn(moved, other.operations)
        self.assertIn(foreign, other.operations)

    def test_checkpoint_is_flushed_line(self):
        L.checkpoint('Test %d', 1)
        import re
        self.assertRegex(self.log().rstrip().splitlines()[-1], r'CP    Test 1( \[\+\d+ ms\])?$')   # 2.0.2: [+N ms]


if __name__ == '__main__':
    unittest.main()
