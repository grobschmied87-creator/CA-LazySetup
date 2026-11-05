# -*- coding: utf-8 -*-
"""LazySetup 2.0.8: Update-Button-Policy, Doppel-Schnitt Keys, CAM-Richtung/Tabs, i18n."""
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
        self.assertEqual(LS.VERSION, '2.0.8')


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
        for k in ('richtung_vor', 'richtung_final', 'stege_vor', 'stege_final',
                  'steg_form_vor', 'steg_form_final', 'bruecken_vor', 'bruecken_final'):
            self.assertIn(k, keys)
        self.assertNotIn('richtung', keys)  # UI-Feld entfernt; DEFAULTS behalten Legacy

    def test_defaults(self):
        self.assertEqual(G.DEFAULTS['richtung_vor'], 'gleich')
        self.assertEqual(G.DEFAULTS['richtung_final'], 'gleich')
        self.assertFalse(G.DEFAULTS['stege_vor'])
        self.assertTrue(G.DEFAULTS['stege_final'])

    def test_migrate_clean_cfg(self):
        import LazySetup as LS
        cfg = LS.clean_cfg({'richtung': 'gegen', 'stege': True, 'durchstich': 0.2})
        self.assertEqual(cfg['richtung_vor'], 'gegen')
        self.assertEqual(cfg['richtung_final'], 'gegen')
        self.assertTrue(cfg['stege_final'])


class TestCamHelpers(unittest.TestCase):
    def test_richtung(self):
        import fs_cam as C
        cfg = {'richtung': 'gegen', 'richtung_vor': 'gleich', 'richtung_final': 'gegen'}
        self.assertEqual(C._richtung_key(cfg, True), 'gleich')
        self.assertEqual(C._richtung_key(cfg, False), 'gegen')
        self.assertEqual(C._richtung_key({'richtung': 'gegen'}, True), 'gegen')

    def test_tab_cfg(self):
        import fs_cam as C
        cfg = dict(G.DEFAULTS, stege_vor=True, steg_breite_vor=5.0, stege_final=False)
        tcfg, on = C._op_tab_cfg(cfg, premill=True)
        self.assertTrue(on)
        self.assertEqual(tcfg['steg_breite'], 5.0)
        tcfg2, on2 = C._op_tab_cfg(cfg, premill=False)
        self.assertFalse(on2)


class TestI18nExpanded(unittest.TestCase):
    def test_groups(self):
        self.assertEqual(ca_i18n.group_label('schnitt_vor', '', 'en'), 'Pre-mill')
        self.assertIn('Fertig', ca_i18n.group_label('schnitt_final', '', 'de'))

    def test_field_opt(self):
        self.assertIn('Gleichlauf', ca_i18n.opt_label('richtung_vor', 'gleich', '', 'de'))
        self.assertEqual(ca_i18n.opt_label('richtung_final', 'gegen', '', 'en'), 'Conventional')
        self.assertTrue(ca_i18n.t('btn.refresh_preview', 'fr'))


class TestMainJsPolicy(unittest.TestCase):
    def test_no_input_debounce_on_fields(self):
        js = open(os.path.join(HERE, 'palette', 'main.js'), encoding='utf-8').read()
        self.assertIn('btnPreviewUpdate', js)
        self.assertIn('markDirty', js)
        self.assertIn("f.kind === 'b' || f.kind === 'd'", js)

    def test_html_hosts(self):
        html = open(os.path.join(HERE, 'palette', 'index.html'), encoding='utf-8').read()
        self.assertIn('grp_schnitt_vor', html)
        self.assertIn('grp_schnitt_final', html)
        self.assertNotIn('id="grp_schnitt"', html)


if __name__ == '__main__':
    unittest.main()
