# -*- coding: utf-8 -*-
"""LazySetup 2.0.4: gelöschtes Nesting (ungültige Rohteile) und Bearbeitungs-Speicher je Occurrence."""
import unittest

import fs_edit as E                       # noqa: E402
import LazySetup as LS                    # noqa: E402
from test_fs_200_lazysetup import Base    # noqa: E402


class Deleted(Base):
    def test_stale_sheets_are_reread(self):
        LS.handle('ready', {})
        old = LS._state['sheets']
        self.assertTrue(old)
        old[0]['occ'].isValid = False          # Nesting in LazyNest gelöscht
        r = LS.handle('run', {})
        self.assertIn('error', r)
        self.assertIsNot(LS._state['sheets'], old)
        self.assertEqual(self.app.fired, [], 'nichts ausgeführt')

    def test_ready_rereads_when_stale(self):
        LS.handle('ready', {})
        old = LS._state['sheets']
        old[0]['occ'].isValid = False
        LS.handle('ready', {})
        self.assertIsNot(LS._state['sheets'], old)


class Tok:
    def __init__(self, t):
        self.entityToken = t
        self.attributes = None


class MemKey(unittest.TestCase):
    def test_new_sheet_same_name_inherits_nothing(self):
        E.clear_mem()
        a = {'name': 'Rohteil 01:1', 'occ': Tok('alt')}
        b = {'name': 'Rohteil 01:1', 'occ': Tok('neu')}
        ov = E.empty()
        try:
            E.save(a, dict(ov, **{'x': 1}))
        except Exception:
            pass
        self.assertIn(E._key(a), E._mem)
        self.assertNotIn(E._key(b), E._mem)
        self.assertTrue(E.is_empty(E.load(b)) if b['occ'].attributes is not None else True)
        E.clear_mem()


if __name__ == '__main__':
    unittest.main()
