# -*- coding: utf-8 -*-
"""Finalschnitt (ab 1.3.0) – Rohteil-Definition aus ContourNest (ab 1.10.0): Ausrichtung längs/quer,
Abschnitt/Standard, Nullpunkt je Rohteil. Reine Python-Logik (ohne Fusion testbar).

Koordinatensysteme
  Material  = Rohteil-Komponente (Fusion), Länge entlang X_mat – darin plant Finalschnitt (Kanten, Skizzen).
  Maschine  = Tisch: X/Y der Welt, Ursprung vordere linke Plattenecke. Quer liegende Rohteile sind in Fusion
              um 90° gedreht: Maschine (x, y) = (Breite − v, u), Material (u, v) = (y, Breite − x).
Der Nullpunkt (WCS) steht als Maschinen-Schlüssel ('lu_unten' … 'mitte_oben') im Projekt bzw. im Attribut
ContourNest/sheet und bleibt beim Drehen an derselben Tischecke (wie in ContourNest cn_geom)."""
import math

ZERO_CORNER_TXT = {'lu': 'unten links', 'ru': 'unten rechts', 'lh': 'oben links', 'rh': 'oben rechts',
                   'mitte': 'Mitte'}
ZERO_SIDE_TXT = {'unten': 'Unterseite', 'oben': 'Oberseite'}
ZERO_KEYS = ('lu_unten', 'ru_unten', 'lh_unten', 'rh_unten', 'mitte_unten',
             'lu_oben', 'ru_oben', 'lh_oben', 'rh_oben', 'mitte_oben')
_BOX_NO = {'lu': '1', 'ru': '2', 'lh': '3', 'rh': '4', 'mitte': 'center'}


def valid_zero(z):
    return z if z in ZERO_KEYS else None


def zero_box_point(key):
    """Fusion-Setup-Parameter wcs_origin_boxPoint ('bottom 1' … 'top center')."""
    c, s = (valid_zero(key) or 'lu_unten').split('_')
    return '%s %s' % ('top' if s == 'oben' else 'bottom', _BOX_NO[c])


def zero_text(key):
    c, s = (valid_zero(key) or 'lu_unten').split('_')
    return '%s, %s' % (ZERO_CORNER_TXT[c], ZERO_SIDE_TXT[s])


def de_num(x):
    """wie ContourNest: höchstens eine Nachkommastelle, Komma, halbe aufwärts."""
    r = math.floor(float(x) * 10.0 + 0.5) / 10.0
    a = abs(r)
    ip = int(math.floor(a + 1e-9))
    fr = int(round((a - ip) * 10))
    return ('-' if r < 0 else '') + str(ip) + (',%d' % fr if fr else '')


def _num(v):
    try:
        f = float(v)
        return f if math.isfinite(f) else None
    except (TypeError, ValueError):
        return None


def project_sheet_rec(project, sheet_no):
    """Rohteil-Eintrag (project['sheets'][…], ContourNest ≥ 1.10.0) oder {}."""
    for s in (project or {}).get('sheets') or []:
        try:
            if int(s.get('index', 0)) == int(sheet_no):
                return s
        except (TypeError, ValueError):
            continue
    return {}


def sheet_info(attr, prec=None, default_zero=None, no=None):
    """Aufgelöste Rohteil-Definition. attr = Attribut ContourNest/sheet (Ist-Geometrie in Fusion),
    prec = Projekt-Eintrag des Rohteils (Vorrang für Ausrichtung/Nullpunkt/Art). Ältere Daten: längs,
    Standard, Nullpunkt = default_zero bzw. unten links/Unterseite."""
    a, p = attr or {}, prec or {}
    length = _num(a.get('length_mm')) or _num(p.get('length')) or 0.0
    width = _num(a.get('width_mm')) or _num(p.get('width')) or 0.0
    thick = _num(a.get('thickness_mm')) or _num(p.get('thickness')) or 0.0
    orient = p.get('orient') or a.get('orient') or 'laengs'
    orient = 'quer' if orient == 'quer' else 'laengs'
    zero = valid_zero(p.get('zero')) or valid_zero(a.get('zero')) or valid_zero(default_zero) or 'lu_unten'
    kind = 'abschnitt' if (p.get('kind') or a.get('kind')) == 'abschnitt' else 'standard'
    grain = 'Y' if (p.get('grain') or a.get('grain')) == 'Y' else 'X'
    quer = orient == 'quer'
    W, H = (width, length) if quer else (length, width)
    g_axis = 'Y' if ((grain == 'Y') != quer) else 'X'
    c, s = zero.split('_')
    x = W if c in ('ru', 'rh') else (W / 2.0 if c == 'mitte' else 0.0)
    y = H if c in ('lh', 'rh') else (H / 2.0 if c == 'mitte' else 0.0)
    u, v = (y, width - x) if quer else (x, y)
    r = {'orient': orient, 'kind': kind, 'zero': zero, 'box_point': zero_box_point(zero), 'grain': grain,
         'grain_axis': g_axis, 'length': length, 'width': width, 'thickness': thick, 'W': W, 'H': H,
         'zero_x': x, 'zero_y': y, 'zero_z': thick if s == 'oben' else 0.0, 'zero_u': u, 'zero_v': v,
         'zero_side': s, 'zero_corner': c, 'zero_text': zero_text(zero),
         'source': 'Projekt' if p.get('orient') or p.get('zero') else ('Attribut' if a.get('orient') or a.get('zero')
                                                                       else 'Standard (ältere Daten)')}
    no = no if no is not None else (a.get('index') or p.get('index') or 0)
    # nur ausdrücklich gewählte Nullpunkte (ContourNest ≥ 1.10.0) dürfen ein vorhandenes Setup ändern
    r['zero_explicit'] = bool(valid_zero(p.get('zero')) or valid_zero(a.get('zero')))
    r['label'] = label(r, no)
    return r


def label(r, no):
    """Gleiche Beschriftung wie in ContourNest (Maß im Maschinensystem)."""
    return 'Rohteil %02d: %s × %s × %s mm, %s, Faser %s, %s | Nullpunkt: %s' % (
        int(no or 0), de_num(r['W']), de_num(r['H']), de_num(r['thickness']),
        'quer' if r['orient'] == 'quer' else 'längs', r['grain_axis'],
        'Abschnitt' if r['kind'] == 'abschnitt' else 'Standard', r['zero_text'])


def to_machine(pt, r):
    """Materialpunkt (u, v) -> Maschine (x, y)."""
    if r.get('orient') != 'quer':
        return (pt[0], pt[1])
    return (r['width'] - pt[1], pt[0])


def to_material(pt, r):
    """Maschinenpunkt (x, y) -> Material (u, v)."""
    if r.get('orient') != 'quer':
        return (pt[0], pt[1])
    return (pt[1], r['width'] - pt[0])


def dir_to_machine(d, r):
    if r.get('orient') != 'quer':
        return (d[0], d[1])
    return (-d[1], d[0])


def project_coords_machine(project):
    """Platzierungen im Projekt im Maschinensystem (ContourNest ≥ 1.10.0)?"""
    return (project or {}).get('coords') == 'maschine'
