# -*- coding: utf-8 -*-
"""Alle Finalschnitt-Tests ausführen: python3 tests/run_all.py"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.join(HERE, 'fsstubs'), os.path.dirname(HERE), HERE]

if __name__ == '__main__':
    suite = unittest.defaultTestLoader.discover(HERE, pattern='test_fs_*.py')
    r = unittest.TextTestRunner(verbosity=1).run(suite)
    sys.exit(0 if r.wasSuccessful() else 1)
