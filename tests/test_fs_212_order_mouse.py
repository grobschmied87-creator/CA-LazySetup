# -*- coding: utf-8 -*-
"""LazySetup 2.0.12: Reihenfolge per Rechtsklick/Maus + sicheres stop()."""
import os
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
import sys
sys.path[:0] = [os.path.join(HERE, 'tests', 'fsstubs'), HERE, os.path.join(HERE, 'tests')]

import fs_edit as E          # noqa: E402
import fs_geom as G          # noqa: E402
from ca_core import ca_i18n  # noqa: E402


def rect(x0, y0, x1, y1):
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


def sheet(parts):
    out = []
    for i, (outer, holes) in enumerate(parts):
        out.append({'name': 'p%d' % i, 'key': 'p%d#1' % i, 'outer': outer, 'holes': holes,
                    'geo': {'z_bottom': 0.0, 'z_top': 18.0}})
    return {'name': 'S', 'length': 1000.0, 'width': 500.0, 'parts': out}


class Version(unittest.TestCase):
    def test_version_2012(self):
        with open(os.path.join(HERE, 'LazySetup.py'), encoding='utf-8') as f: src = f.read()
        self.assertIn("VERSION = '2.0.12'", src)
        with open(os.path.join(HERE, 'VERSION'), encoding='utf-8') as f:
            self.assertEqual(f.read().strip(), '2.0.12')


class OrderMouseI18n(unittest.TestCase):
    KEYS = ('ctx.order_mouse', 'ctx.order_auto', 'status.order_pick', 'status.order_done',
            'status.order_cancel', 'status.order_need_parts', 'order_by_hand')

    def test_all_langs(self):
        for lang in ('de', 'en', 'es', 'fr'):
            cat = ca_i18n.catalog(lang)
            for k in self.KEYS:
                self.assertTrue(cat.get(k), '%s/%s' % (lang, k))
            s = ca_i18n.t('status.order_pick', lang, n=2, total=5)
            self.assertIn('2', s)
            self.assertIn('5', s)
            self.assertNotIn('{n}', s)


class OrderSetPartial(unittest.TestCase):
    def test_partial_order_appends_auto_rest(self):
        sh = sheet([(rect(100, 100, 200, 200), []), (rect(400, 100, 500, 400), []),
                    (rect(700, 100, 800, 180), [])])
        ov = E.empty()
        ov['order'] = ['p2#1']
        pl = G.plan_sheet(sh, {}, ov)
        keys = [pl['parts'][i]['key'] for i in pl['order']]
        self.assertEqual(keys[0], 'p2#1')
        self.assertEqual(set(keys), {'p0#1', 'p1#1', 'p2#1'})
        self.assertTrue(pl['overrides']['order_manual'])
        ov2, msgs, ok = E.apply_edit(pl, E.empty(), {'op': 'order_set', 'order': ['p1#1', 'p0#1', 'p2#1']})
        self.assertTrue(ok)
        self.assertEqual(ov2['order'], ['p1#1', 'p0#1', 'p2#1'])


class DeadOccurrenceGuards(unittest.TestCase):
    class Dead:
        isValid = False

        @property
        def entityToken(self):
            raise AssertionError('entityToken must not be read on invalid occ')

        @property
        def attributes(self):
            raise AssertionError('attributes must not be read on invalid occ')

    def test_key_and_save_skip_dead(self):
        sh = {'name': 'Rohteil 01:1', 'occ': self.Dead()}
        self.assertEqual(E._key(sh), 'Rohteil 01:1|')
        self.assertFalse(E.save(sh, E.empty()))
        n = E.persist_all([sh])
        self.assertEqual(n, 0)


class StopAndUiSource(unittest.TestCase):
    def test_stop_guards(self):
        with open(os.path.join(HERE, 'LazySetup.py'), encoding='utf-8') as f: src = f.read()
        self.assertIn("_state['stopping'] = True", src)
        self.assertIn('def _design_alive', src)
        self.assertIn('def _obj_valid', src)
        self.assertIn('stop(): persist übersprungen', src)
        self.assertIn("if _state.get('stopping')", src)
        stop = src[src.index('def stop(context):'):]
        self.assertNotIn('messageBox', stop)

    def test_editor_context_menu(self):
        with open(os.path.join(HERE, 'palette', 'editor.js'), encoding='utf-8') as f: js = f.read()
        self.assertIn("addEventListener('contextmenu'", js)
        self.assertIn('ev.preventDefault()', js)
        self.assertIn('startOrderPick', js)
        self.assertIn("op: 'order_set'", js)
        self.assertIn("'Escape'", js)
        self.assertIn('clickOrderPick', js)


if __name__ == '__main__':
    unittest.main()
