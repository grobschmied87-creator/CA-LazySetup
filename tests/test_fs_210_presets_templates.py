# -*- coding: utf-8 -*-
"""LazySetup 2.0.11: Werkzeug-Schnittdaten-Presets + CAM-Vorlagen (Lokal/Cloud)."""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, 'tests'))

import fsfake as FK  # noqa: E402
import adsk.cam as cam  # noqa: E402
import fs_geom as G  # noqa: E402
import fs_cam as C  # noqa: E402
from ca_core import ca_i18n  # noqa: E402


class FakeParam:
    def __init__(self, name):
        self.name = name
        self.value = 0
        self.expression = ''
        self._choices = []

    def get_choices(self):
        return self._choices


class FakeParams:
    def __init__(self, names):
        self._items = {n: FakeParam(n) for n in names}

    def itemByName(self, name):
        return self._items.get(name)


class FakeOp:
    def __init__(self, names):
        self.parameters = FakeParams(names)
        self.name = 'op'
        self.tool = None
        self.toolPreset = None


class TestCutPresets(unittest.TestCase):
    def test_cut_presets_of_and_pick(self):
        tool = FK.Tool(3, 8.0, 'Spiral 8')
        tool.presets.append(FK.ToolPreset('Alu langsam'))
        tool.presets.append(FK.ToolPreset('Alu schnell'))
        got = C.cut_presets_of(tool)
        self.assertEqual([p['name'] for p in got], ['Alu langsam', 'Alu schnell'])
        self.assertEqual(C.pick_tool_preset(tool, 'Alu schnell').name, 'Alu schnell')
        self.assertEqual(C.pick_tool_preset(tool, 'fehlend').name, 'Alu langsam')
        self.assertEqual(C.pick_tool_preset(tool, None, 1).name, 'Alu schnell')
        self.assertIsNone(C.pick_tool_preset(FK.Tool(1, 6.0, 'leer'), 'x'))

    def test_tools_payload_includes_cut_presets(self):
        import LazySetup as LS
        LS._state['tools'] = [{
            'label': 'T3 Ø 8 mm – Dokument',
            'tool': None, 'source': 'Dokument',
            'info': {'d_mm': 8, 'type': 'flat end mill', 'flutes': 2, 'feed': None, 'rpm': None},
        }]
        LS._state['tool_libs'] = [{'id': 'Dokument', 'label': 'Dokument'}]
        LS._state['cfg'] = dict(G.DEFAULTS)
        pay = LS._tools_payload()
        self.assertIn('items', pay)
        self.assertEqual(pay['items'][0]['label'], 'T3 Ø 8 mm – Dokument')
        self.assertEqual(pay['items'][0]['cut_presets'], [])


class TestTemplateList(unittest.TestCase):
    def setUp(self):
        C._TEMPLATE_INDEX = {}
        self.lm = FK.LibraryManager({})
        local = FK.CAMTemplate('Kontur Holz', ('contour2d',))
        hole = FK.CAMTemplate('Bohrbild', ('drill',), hole=True)
        cloud = FK.CAMTemplate('Tasche', ('pocket2d',))
        invalid = FK.CAMTemplate('Kaputt', ('contour2d',), valid=False)
        turning = FK.CAMTemplate('Drehen', ('turning',))
        self.lm.templateLibrary = FK.TemplateLibrary({
            'tmpl/local': {'folders': ['tmpl/local/Holz'], 'templates': []},
            'tmpl/local/Holz': {'folders': [], 'templates': [local, hole, invalid, turning]},
            'tmpl/cloud': {'folders': [], 'templates': [cloud]},
        })
        cam.CAMManager._lm = self.lm

    def tearDown(self):
        cam.CAMManager._lm = None

    def test_list_filters_hole_invalid_and_skips_hub(self):
        found = C.list_templates()
        names = [e['name'] for e in found]
        self.assertIn('Kontur Holz', names)
        self.assertIn('Tasche', names)
        self.assertNotIn('Bohrbild', names)
        self.assertNotIn('Kaputt', names)
        self.assertNotIn('Drehen', names)
        loc = [e for e in found if e['name'] == 'Kontur Holz'][0]
        self.assertEqual(loc['location'], 'Lokal')
        self.assertIn('contour2d', loc['strategies'])
        self.assertTrue(loc['id'].startswith('Lokal|'))
        resolved = C.resolve_template(loc['id'])
        self.assertIsNotNone(resolved)
        self.assertEqual(resolved.name, 'Kontur Holz')

    def test_mismatch_before_create(self):
        found = {e['name']: e for e in C.list_templates()}
        rec = {}
        setup = FK.Setup(FK.CAM(), 'S')
        with self.assertRaises(RuntimeError) as ctx:
            C.new_op(setup, 'contour2d', 'FS 01 Test', None, {'kind': 'x'}, rec,
                     cfg={'cam_template_final': found['Tasche']['id']}, premill=False)
        self.assertIn('passt nicht', str(ctx.exception))
        self.assertEqual(setup.operations.count, 0)


class TestNewOpPresetAndTemplate(unittest.TestCase):
    def test_new_op_uses_named_preset_not_first(self):
        tool = FK.Tool(3, 8.0, 'Spiral 8')
        tool.presets.append(FK.ToolPreset('A'))
        tool.presets.append(FK.ToolPreset('B'))
        setup = FK.Setup(FK.CAM(), 'S')
        rec = {}
        op = C.new_op(setup, 'contour2d', 'FS 01 Außen', tool, {'kind': 'aussen'}, rec,
                      cfg={'cut_preset_final': 'B'}, premill=False)
        self.assertEqual(op.toolPreset.name, 'B')
        self.assertEqual(rec['toolPreset'], 'B')
        self.assertFalse(rec.get('from_template'))

    def test_new_op_from_template_sets_geometry_path_ready(self):
        tmpl = FK.CAMTemplate('Meine Kontur', ('contour2d',))
        lm = FK.LibraryManager({})
        lm.templateLibrary = FK.TemplateLibrary({'tmpl/local': {'templates': [tmpl]}, 'tmpl/cloud': {}})
        cam.CAMManager._lm = lm
        try:
            info = C.list_templates()[0]
            setup = FK.Setup(FK.CAM(), 'S')
            tool = FK.Tool(1, 8.0, 'X')
            tool.presets.append(FK.ToolPreset('Holz'))
            rec = {}
            op = C.new_op(setup, 'contour2d', 'FS 01 Außen – Teil', tool, {'kind': 'aussen'}, rec,
                          cfg={'cam_template_final': info['id'], 'cut_preset_final': 'Holz'}, premill=False)
            self.assertTrue(rec['from_template'])
            self.assertEqual(op.name, 'FS 01 Außen – Teil')
            self.assertEqual(op.tool, tool)
            self.assertEqual(op.toolPreset.name, 'Holz')
            self.assertEqual(len(rec['template_ops']), 1)
        finally:
            cam.CAMManager._lm = None


class TestCommonParamsTemplateWins(unittest.TestCase):
    def _names(self):
        return [
            'doLeadIn', 'leadInType', 'entry_horizontal', 'useRamp', 'rampType',
            'rampAngle', 'leadInAngle', 'rampLength', 'horizontalLeadInDistance',
            'leadInSweepDistance', 'leadInRadius', 'horizontalLeadInRadius',
            'leadInFeedrate', 'entry_feedrate', 'rampFeedrate',
            'tool_feedCutting', 'feedrate', 'cuttingFeedrate',
            'tool_spindleSpeed', 'spindleSpeed',
            'compensation', 'bottomHeight_mode', 'bottomHeight_offset',
            'doMultipleDepths', 'maximumStepdown', 'useStockToLeave',
            'stockToLeave', 'verticalStockToLeave',
        ]

    def test_no_template_sets_az_and_lead_not_feeds(self):
        op = FakeOp(self._names())
        rec = {}
        cfg = dict(G.DEFAULTS, anfahr_art_vor='rampe', az_vor=4.0, vf_vor=1111, spindle_vor=2222)
        C.common_params(op, cfg, 18.0, rec, premill=True)
        self.assertEqual(rec['anfahr']['art'], 'rampe')
        self.assertTrue(rec.get('maximumStepdown', {}).get('ok') or op.parameters.itemByName('maximumStepdown').expression
                        or op.parameters.itemByName('maximumStepdown').value)
        self.assertFalse(rec['feeds']['applied'])
        # vf darf nicht mehr geschrieben werden
        self.assertIn(op.parameters.itemByName('tool_feedCutting').value, (0, 0.0))

    def test_template_skips_lead_and_az(self):
        op = FakeOp(self._names())
        rec = {}
        cfg = dict(G.DEFAULTS, cam_template_vor='Lokal|Holz|Kontur', az_vor=4.0, anfahr_art_vor='rampe')
        C.common_params(op, cfg, 18.0, rec, premill=True)
        self.assertTrue(rec['from_template'])
        self.assertNotIn('anfahr', rec)
        self.assertEqual(op.parameters.itemByName('maximumStepdown').value, 0)


class TestCleanCfgStrings(unittest.TestCase):
    def test_string_fields(self):
        import LazySetup as LS
        cfg = LS.clean_cfg({
            'tool_label_vor': 'T3 Ø 8',
            'cut_preset_vor': 'Alu schnell',
            'cam_template_final': 'Lokal|x|Kontur',
            'az_vor': 5,
        })
        self.assertEqual(cfg['tool_label_vor'], 'T3 Ø 8')
        self.assertEqual(cfg['cut_preset_vor'], 'Alu schnell')
        self.assertEqual(cfg['cam_template_final'], 'Lokal|x|Kontur')
        self.assertEqual(cfg['az_vor'], 5)


class TestI18nAndUi(unittest.TestCase):
    def test_keys_all_langs(self):
        for lang in ('de', 'en', 'es', 'fr'):
            self.assertNotEqual(ca_i18n.t('label.preset_feeds', lang), 'field.label.preset_feeds')
            self.assertNotIn('Schnittwerte', ca_i18n.t('label.preset_feeds', lang) if lang != 'de' else 'x')
            self.assertTrue(ca_i18n.t('field.cam_template_vor', lang))
            self.assertTrue(ca_i18n.t('field.cut_preset_final', lang))
            self.assertTrue(ca_i18n.t('label.template_none', lang))
        self.assertIn('LazySetup', ca_i18n.t('label.preset_feeds', 'de'))
        self.assertIn('LazySetup', ca_i18n.t('label.preset_feeds', 'en'))

    def test_js_and_html(self):
        js = open(os.path.join(HERE, 'palette', 'main.js'), encoding='utf-8').read()
        self.assertIn('syncTemplateUi', js)
        self.assertIn('fillMachiningSelects', js)
        self.assertIn("f.kind === 's'", js)
        html = open(os.path.join(HERE, 'palette', 'index.html'), encoding='utf-8').read()
        self.assertIn('preset_feeds', html)
        self.assertIn('v2.0.12', html)
        self.assertNotIn('Vorlage Schnittwerte', html)


if __name__ == '__main__':
    unittest.main()
