# -*- coding: utf-8 -*-
"""Echte Teilkonturen aus den ContourNest-Protokollen (/workspace/cn_logs*/apply_*.json) als Rohteile.
Löcher kommen aus der Projektdatei in cn_logs3 (job.parts[*].holes, gleiches Teil-Koordinatensystem)."""
import glob
import json
import math
import os

ROOT = os.environ.get('FS_CN_LOGS', '/workspace')


def place(pts, rot, flip, x, y):
    r = math.radians(rot)
    c, s = math.cos(r), math.sin(r)
    out = []
    for u, v in pts:
        if flip:
            v = -v
        out.append((c * u - s * v + x, s * u + c * v + y))
    return out


def _holes():
    res = {}
    for f in glob.glob(os.path.join(ROOT, 'cn_logs3', 'projects*')):
        try:
            with open(f, encoding='utf-8') as fh:
                d = json.load(fh)
            for p in d['job']['parts']:
                if p.get('holes'):
                    res[p['id']] = p['holes']
        except Exception:
            pass
    return res


def apply_files():
    return sorted(glob.glob(os.path.join(ROOT, 'cn_logs*', 'apply_*.json')))


def sheets_from(path, with_holes=True):
    with open(path, encoding='utf-8') as fh:
        d = json.load(fh)
    holes = _holes() if with_holes else {}
    jp = {p['id']: p for p in d['job_parts']}
    st = d['palette_result']['sheet']
    out = []
    for n, sh in enumerate(d['palette_result']['sheets']):
        parts = []
        for e in sh:
            p = jp[e['id']]
            parts.append({'key': e.get('key', e['id']), 'name': p['name'], 'id': e['id'],
                          'local_outer': p['outer'], 'local_holes': holes.get(e['id'], []),
                          'placement': {'x': e['x'], 'y': e['y'], 'rot': e['rot'], 'flip': e['flip']},
                          'outer': place(p['outer'], e['rot'], e['flip'], e['x'], e['y']),
                          'holes': [place(h, e['rot'], e['flip'], e['x'], e['y']) for h in holes.get(e['id'], [])]})
        out.append({'no': n + 1, 'name': 'Rohteil %02d' % (n + 1), 'length': float(st['length']),
                    'width': float(st['width']), 'thickness': 15.0, 'parts': parts})
    return out


def all_sheets():
    res = []
    for f in apply_files():
        for s in sheets_from(f):
            s['source'] = os.path.basename(os.path.dirname(f)) + '/' + os.path.basename(f)
            res.append(s)
    return res
