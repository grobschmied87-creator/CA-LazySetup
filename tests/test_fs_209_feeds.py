# -*- coding: utf-8 -*-
"""LazySetup 2.0.9: Anfahr/Schnittwerte, Vorlagen, Vorfräs ohne Tabs."""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, 'tests'))

import fsfake  # noqa: F401
import fs_geom as G
import fs_cam as C


class FakeParam:
    def __init__(self, name, kind='number'):
        self.name = name
        self.kind = kind
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


class TestCleanCfg209(unittest.TestCase):
    def test_header_ignored(self):
        import LazySetup as LS
        cfg = LS.clean_cfg({'hdr_anfahr_vor': 'x', 'az_vor': 7.5, 'anfahr_art_vor': 'eintauchen'})
        self.assertEqual(cfg['az_vor'], 7.5)
        self.assertEqual(cfg['anfahr_art_vor'], 'eintauchen')
        self.assertFalse(cfg['stege_vor'])

    def test_zustellung_legacy(self):
        import LazySetup as LS
        cfg = LS.clean_cfg({'zustellung': 9.0})
        self.assertEqual(cfg['az_vor'], 9.0)
        self.assertEqual(cfg['az_final'], 9.0)

    def test_fields_payload_headers(self):
        import LazySetup as LS
        keys = [f['key'] for f in LS.fields_payload('de')]
        self.assertIn('hdr_anfahr_vor', keys)
        kinds = {f['key']: f['kind'] for f in LS.fields_payload('de')}
        self.assertEqual(kinds['hdr_schnitt_final'], 'h')


class TestLeadFeeds(unittest.TestCase):
    def test_lead_and_feeds_recorded(self):
        names = [
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
        op = FakeOp(names)
        # monkeypatch set_* to be tolerant: use real functions but FakeParam may lack attrs
        cfg = dict(G.DEFAULTS, anfahr_art_vor='rampe', vf_vor=1111, spindle_vor=2222, az_vor=4.0)
        rec = {}
        # common_params needs more – call helpers directly
        C.lead_in_params(op, cfg, True, rec)
        self.assertEqual(rec['anfahr']['art'], 'rampe')
        C.feed_speed_params(op, cfg, True, rec)
        self.assertEqual(rec['feeds']['vf'], 1111)
        self.assertEqual(rec['feeds']['spindle'], 2222)

    def test_premill_tabs_forced_off_in_create_path(self):
        cfg = dict(G.DEFAULTS, stege_vor=True, stege_final=True)
        _, on = C._op_tab_cfg(cfg, premill=True)
        self.assertFalse(on)


class TestPresetRoundtrip(unittest.TestCase):
    def test_save_load_feeds(self):
        import LazySetup as LS
        import tempfile, shutil
        tmp = tempfile.mkdtemp()
        try:
            old = LS.PRESET_FILE
            LS.PRESET_FILE = os.path.join(tmp, 'user_presets.json')
            cfg = dict(G.DEFAULTS, az_vor=8.0, vf_final=2400.0, anfahr_art_final='bogen')
            self.assertTrue(LS.save_preset('HolzTest', cfg))
            got = LS.presets()['HolzTest']
            self.assertEqual(got['az_vor'], 8.0)
            self.assertEqual(got['vf_final'], 2400.0)
            LS.PRESET_FILE = old
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == '__main__':
    unittest.main()
