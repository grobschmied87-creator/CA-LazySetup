# -*- coding: utf-8 -*-
"""LazySetup 2.0.9: Update-Button-Policy, Doppel-Schnitt Keys, CAM-Richtung/Tabs, i18n."""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, 'tests'))

import fsfake  # noqa: F401
import fs_geom as G
from ca_core import ca_i18n


class TestVersion(unittest.TestCase):
    def test_version(self):
        import LazySetup as LS
        self.assertEqual(LS.VERSION, '2.0.11')


class TestDualSchnittFields(unittest.TestCase):
    def test_groups(self):
        import LazySetup as LS
        gids = [g[0] for g in LS.GROUPS]
        self.assertIn('schnitt_vor', gids)
        self.assertIn('schnitt_final', gids)
        self.assertNotIn('schnitt', gids)

    def test_keys(self):
        import LazySetup as LS
        keys = [f[0] for f in LS.FIELDS]
        for k in ('richtung_vor', 'richtung_final', 'stege_final', 'bruecken_final',
                  'anfahr_art_vor', 'anfahr_art_final', 'az_vor', 'az_final',
                  'tool_label_vor', 'cut_preset_vor', 'cam_template_vor',
                  'tool_label_final', 'cut_preset_final', 'cam_template_final'):
            self.assertIn(k, keys)
        for k in ('vc_vor', 'vf_vor', 'spindle_vor', 'fz_vor', 'vc_final', 'vf_final'):
            self.assertNotIn(k, keys)
        for k in ('stege_vor', 'steg_form_vor', 'bruecken_vor', 'steg_breite_vor', 'zustellung'):
            self.assertNotIn(k, keys)
        self.assertNotIn('richtung', keys)

    def test_defaults(self):
        self.assertEqual(G.DEFAULTS['richtung_vor'], 'gleich')
        self.assertEqual(G.DEFAULTS['richtung_final'], 'gleich')
        self.assertFalse(G.DEFAULTS['stege_vor'])
        self.assertTrue(G.DEFAULTS['stege_final'])
        self.assertEqual(G.DEFAULTS['anfahr_art_vor'], 'rampe')
        self.assertEqual(G.DEFAULTS['anfahr_art_final'], 'bogen')

    def test_migrate_clean_cfg(self):
        import LazySetup as LS
        cfg = LS.clean_cfg({'richtung': 'gegen', 'stege': True, 'durchstich': 0.2})
        self.assertEqual(cfg['richtung_vor'], 'gegen')
        self.assertEqual(cfg['richtung_final'], 'gegen')
        self.assertTrue(cfg['stege_final'])
        self.assertFalse(cfg['stege_vor'])


class TestCamHelpers(unittest.TestCase):
    def test_richtung(self):
        import fs_cam as C
        cfg = {'richtung': 'gegen', 'richtung_vor': 'gleich', 'richtung_final': 'gegen'}
        self.assertEqual(C._richtung_key(cfg, True), 'gleich')
        self.assertEqual(C._richtung_key(cfg, False), 'gegen')
        self.assertEqual(C._richtung_key({'richtung': 'gegen'}, True), 'gegen')

    def test_tab_cfg_premill_never(self):
        import fs_cam as C
        cfg = dict(G.DEFAULTS, stege_vor=True, steg_breite_vor=5.0, stege_final=False)
        tcfg, on = C._op_tab_cfg(cfg, premill=True)
        self.assertFalse(on)
        tcfg2, on2 = C._op_tab_cfg(cfg, premill=False)
        self.assertFalse(on2)
        cfg2 = dict(G.DEFAULTS, stege_final=True, steg_breite_final=4.0)
        tcfg3, on3 = C._op_tab_cfg(cfg2, premill=False)
        self.assertTrue(on3)
        self.assertEqual(tcfg3['steg_breite'], 4.0)


class TestI18nExpanded(unittest.TestCase):
    def test_groups(self):
        self.assertEqual(ca_i18n.group_label('schnitt_vor', '', 'en'), 'Pre-mill')
        self.assertIn('Fertig', ca_i18n.group_label('schnitt_final', '', 'de'))

    def test_field_opt(self):
        self.assertIn('Gleichlauf', ca_i18n.opt_label('richtung_vor', 'gleich', '', 'de'))
        self.assertEqual(ca_i18n.opt_label('richtung_final', 'gegen', '', 'en'), 'Conventional')
        self.assertEqual(ca_i18n.opt_label('anfahr_art_vor', 'rampe', '', 'de'), 'Rampe')
        self.assertTrue(ca_i18n.t('btn.refresh_preview', 'fr'))
        self.assertIn('az', ca_i18n.t('field.az_vor', 'de'))


class TestMainJsPolicy(unittest.TestCase):
    def test_no_input_debounce_on_fields(self):
        js = open(os.path.join(HERE, 'palette', 'main.js'), encoding='utf-8').read()
        self.assertIn('btnPreviewUpdate', js)
        self.assertIn('markDirty', js)
        self.assertIn("f.kind === 'b' || f.kind === 'd' || f.kind === 's'", js)
        self.assertIn("f.kind === 'h'", js)

    def test_html_hosts(self):
        html = open(os.path.join(HERE, 'palette', 'index.html'), encoding='utf-8').read()
        self.assertIn('grp_schnitt_vor', html)
        self.assertIn('grp_schnitt_final', html)
        self.assertIn('preset_feeds', html)
        self.assertNotIn('id="grp_schnitt"', html)


if __name__ == '__main__':
    unittest.main()
