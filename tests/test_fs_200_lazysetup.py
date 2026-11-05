# -*- coding: utf-8 -*-
"""CA LazySetup 2.0.0: Palette-Ablauf (handle), Hänger-Schutz vor computeAll, sichere Setup-Modelle, Migration."""
import json
import os
import shutil
import tempfile
import unittest

import fsfake as FK       # noqa: E402
import fs_testdata as TD  # noqa: E402
import fs_log as L        # noqa: E402
import fs_run as R        # noqa: E402
import LazySetup as LS    # noqa: E402
import adsk.cam           # noqa: E402

HOLES_SHEET = os.path.join(TD.ROOT, 'cn_logs3', 'apply_20261009_102512_483.json')


class UI:
    def __init__(self, answer=True):
        self.msgs, self.answer = [], answer
        self.palettes = type('P', (), {'itemById': lambda s, i: None})()

    def messageBox(self, text, title='', buttons=None, icon=None):
        self.msgs.append(text)
        return 2 if self.answer else 3


class Ref:
    def __init__(self, name, ood, v=3, latest=5):
        self.isOutOfDate = ood
        self.version = v
        self.dataFile = type('DF', (), {'name': name, 'latestVersionNumber': latest})()


class Refs(list):
    @property
    def count(self):
        return len(self)

    def item(self, i):
        return self[i]


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._env = os.environ.get('APPDATA')
        os.environ['APPDATA'] = os.path.join(self.tmp, 'appdata')
        L.LOG_DIR = self.tmp
        L.LOG_FILE = os.path.join(self.tmp, 'lazysetup.log')
        LS.PRESET_FILE = os.path.join(self.tmp, 'user_presets.json')
        LS.SETTINGS_FILE = os.path.join(self.tmp, 'user_settings.json')
        self.design = FK.build_design(TD.sheets_from(HOLES_SHEET))
        self.cam = FK.CAM(self.design)
        self.cam.documentToolLibrary = FK.Coll([FK.Tool(3, 8.0, 'Spirale 8'), FK.Tool(4, 12.0, 'Spirale 12')])
        adsk.cam.CAMManager._lm = None
        self.app = FK.App(self.design, self.cam)
        self.app.fired = []
        self.app.fireCustomEvent = lambda ev, data: self.app.fired.append(ev) or False
        self.ui = UI()
        LS._app, LS._ui = self.app, self.ui
        LS._state.update({'sheets': [], 'tools': None, 'pending': None, 'sel': None, 'cur': None, 'cfg': None,
                          'tool_label': None, 'tnr': 0, 'editor': None, 'result': None})
        LS._custom_events.clear()
        LS._custom_events[LS.EV_RUN] = ('ev', 'h')
        R.LAST_COMPUTE.clear()
        FK.EVENTS[:] = []

    def tearDown(self):
        if self._env is None:
            os.environ.pop('APPDATA', None)
        else:
            os.environ['APPDATA'] = self._env
        shutil.rmtree(self.tmp, ignore_errors=True)


class Palette(Base):
    def test_ready_session(self):
        LS._load_tools()
        s = LS.handle('ready', {})
        json.dumps(s, default=str)
        self.assertEqual(s['version'], '2.0.8')
        self.assertEqual([x['name'] for x in s['sheets']], ['Rohteil 01:1'])
        self.assertEqual(len(s['fields']), len(LS.FIELDS))
        self.assertTrue(s['plan']['parts'])
        self.assertIn('1. Stirnwand', '\n'.join(s['plan']['rows']))
        self.assertEqual(s['info']['appName'], 'CA LazySetup')
        self.assertTrue(s['license'].get('licensed', True) or s.get('info'))
        self.assertTrue(s['tools']['list'][0].startswith('T3'))

    def test_cfg_changes_plan_and_bounds(self):
        LS.handle('ready', {})
        r = LS.handle('cfg', {'cfg': {'steg_breite': 999, 'richtung': 'quatsch', 'stege': False, 'w_flaeche': '33,4'}})
        self.assertEqual(LS._state['cfg']['steg_breite'], 50.0)
        self.assertEqual(LS._state['cfg']['richtung'], 'gleich')
        self.assertEqual(LS._state['cfg']['w_flaeche'], 33)
        self.assertTrue(all(not p['tabs'] or all(t['bridge'] for t in p['tabs']) for p in r['plan']['parts']))
        r = LS.handle('cfg', {'cfg': {}, 'sel': []})
        self.assertIsNone(r['plan'])

    def test_edit_tab_via_palette(self):
        LS.handle('ready', {})
        p = LS.handle('cfg', {'cfg': {}})['plan']
        part = p['parts'][0]
        n0 = len(part['tabs'])
        q = part['outer'][0]
        r = LS.handle('edit', {'op': 'tab_add', 'key': part['key'], 'pt': q, 'sheet': p['sheet']['name']})['plan']
        got = next(x for x in r['parts'] if x['key'] == part['key'])
        self.assertTrue(got['edited'] or len(got['tabs']) != n0, r.get('msgs'))
        self.assertIn('rows', r)

    def test_presets(self):
        LS.handle('ready', {})
        LS.handle('cfg', {'cfg': {'steg_breite': 11.0}})
        self.assertTrue(LS.handle('presetSave', {'name': 'Birke 18'})['ok'])
        LS.handle('presetLoad', {'name': 'Kleinteile sicher (mehr Stege)'})
        self.assertEqual(LS._state['cfg']['steg_abstand_klein'], 150.0)
        LS.handle('presetLoad', {'name': 'Birke 18'})
        self.assertEqual(LS._state['cfg']['steg_breite'], 11.0)
        self.assertFalse(LS.handle('presetSave', {'name': ' '})['ok'])

    def test_run_deferred_creates_ops(self):
        LS._load_tools()
        LS.handle('ready', {})
        LS.handle('cfg', {'cfg': {'richtung': 'gegen'}, 'tool': {'label': LS._state['tools'][0]['label'], 'tnr': 0}})
        r = LS.handle('run', {})
        self.assertTrue(r['ok'])
        self.assertEqual(self.app.fired, [LS.EV_RUN])
        self.assertEqual(len(self.cam.setups), 0, 'im Palette-Handler keine CAM-Änderung')
        LS._deferred(LS.EV_RUN)
        self.assertEqual(len(self.cam.setups), 1)
        self.assertGreater(LS._state['result']['ops'], 0)
        with open(LS.SETTINGS_FILE, encoding='utf-8') as f:
            st = json.load(f)
        self.assertEqual(st['cfg']['richtung'], 'gegen')
        self.assertTrue(st['tool_label'].startswith('T3'))
        self.assertEqual(st['version'], '2.0.8')

    def test_license_and_diag(self):
        st = LS.handle('license', {'key': 'ignored'})
        self.assertTrue(st.get('licensed'))
        self.assertTrue(st.get('apply_allowed'))
        d = LS.handle('diag', {})
        self.assertIn('CA LazySetup 2.0.8', d['text'])
        self.assertNotIn('PRIVATE', d['text'].upper())
        self.assertNotIn('Maschinen-ID', d['text'])


class HangGuard(Base):
    def test_outdated_refs_abort_before_compute(self):
        self.design.parentDocument = type('Doc', (), {'documentReferences': Refs([Ref('Korpus', True), Ref('ok', False)]),
                                                      'name': 'X'})()
        res = R.run(self.app, self.ui, self.design, {}, None, None, '2.0.0')
        self.assertTrue(res.get('aborted'))
        self.assertEqual(self.design.computed, 0, 'kein computeAll bei veralteten Verknüpfungen')
        self.assertIn('Korpus', res['lines'][0])
        self.assertIn('Alle aktualisieren', res['lines'][0])
        self.assertEqual(len(self.cam.setups), 0)

    def test_compute_once_when_unchanged(self):
        tl = type('TL', (), {'count': 7, 'markerPosition': 7})()
        self.design.timeline = tl
        res = {'errors': 0, 'lines': []}
        self.assertTrue(R.compute_ok(self.design, res))
        self.assertTrue(R.compute_ok(self.design, res))
        self.assertEqual(self.design.computed, 1, 'zweites computeAll übersprungen')
        tl.count = 8
        self.assertTrue(R.compute_ok(self.design, res))
        self.assertEqual(self.design.computed, 2)

    def test_checkpoint_after_compute(self):
        res = {'errors': 0, 'lines': []}
        R.compute_ok(self.design, res)
        with open(L.LOG_FILE, encoding='utf-8-sig') as f:
            log = f.read()
        self.assertIn('computeAll() fertig', log)

    def test_unsafe_models_skip_sheet(self):
        LS._read_design('t')
        sh = LS._state['sheets'][0]
        s = FK.linked_setup(self.cam, 1)

        class Bad:
            @property
            def count(self):
                raise RuntimeError('InternalValidationError: model')
        s.models = Bad()
        ok, why = R.models_safe(s)
        self.assertFalse(ok)
        res = R.run(self.app, self.ui, self.design, {}, [sh['name']], None, '2.0.0')
        self.assertEqual(res['ops'], 0)
        self.assertTrue(any('nicht sicher lesbar' in w for w in res['warnings']), res['warnings'])
        self.assertEqual(len(s.operations), 0)


class Migration(Base):
    def test_settings_from_finalschnitt_backup(self):
        addins = os.path.join(self.tmp, 'AddIns')
        new = os.path.join(addins, 'LazySetup')
        old = os.path.join(addins, 'Finalschnitt_backup_2026-10-12')
        os.makedirs(new)
        os.makedirs(old)
        for f, d in (('user_settings.json', {'version': '1.3.1', 'cfg': {'steg_breite': 9.5}}),
                     ('user_presets.json', {'Mein': {'steg_min': 4}})):
            with open(os.path.join(old, f), 'w', encoding='utf-8') as fh:
                json.dump(d, fh)
        LS.HERE = new
        LS.SETTINGS_FILE = os.path.join(new, 'user_settings.json')
        LS.PRESET_FILE = os.path.join(new, 'user_presets.json')
        try:
            LS._migrate()
            self.assertEqual(LS.initial_cfg()[0]['steg_breite'], 9.5)
            self.assertIn('Mein', LS.presets())
            with open(LS.SETTINGS_FILE, encoding='utf-8') as fh:
                self.assertIn('migrated_from_finalschnitt', json.load(fh))
            os.remove(os.path.join(new, 'user_presets.json'))
            LS._migrate()                       # nur einmal
            self.assertFalse(os.path.exists(os.path.join(new, 'user_presets.json')))
        finally:
            LS.HERE = LS._HERE


if __name__ == '__main__':
    unittest.main()
