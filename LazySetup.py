# -*- coding: utf-8 -*-
"""CA LazySetup 2.0.12 (vormals Finalschnitt 1.3.1) – Fertigschnitt (2D-Kontur) für CA-LazyNest-/ContourNest-Rohteile.

EIN Fenster (Palette, wie CA LazyNest): Kopf mit Logo, Register Rohteile / Werkzeug / Bearbeitung / Stege / Vorschau /
Ergebnis, Infobox (Lizenz, Diagnose), hell/dunkel nach Fusion-Farbschema. In der Vorschau werden Halte-/Brückenstege
und Startpunkte per Klick bearbeitet (wie „Stege bearbeiten“ in 1.2–1.3). „Operationen erstellen“ läuft verzögert in
einem eigenen CustomEvent (nie im Palette-Handler). Liest weiterhin die ContourNest-Attribute (LazyNest schreibt sie
unverändert) und Bearbeitungen/Operationen von Finalschnitt (Attributgruppe „Finalschnitt“ bleibt).
2.0.1: ALLE Kontur-Operationen schneiden die SILHOUETTE des Teils (fs_silhouette: Draufsicht aller Flächen) –
Außenkontur = äußerster Umriss (Fase/Falz/Überstand), Durchbrüche nur, wo man ganz durchsieht; Sacklöcher, Taschen
und Nuten werden nie durchgeschnitten. Zusammengesetzte Umrisse -> ausgeblendete Skizze „LazySetup Silhouette – Teil“.
2.0.2: Silhouette rauschfest (Verschweißen, tolerantes Schließen, offene Enden gemeldet), Schnellweg für gewöhnliche
Platten, Ersatz LazyNest-Kontur, Bögen über Mittelpunkt/Winkel mit Prüfung, Diagnose-Silhouette; computeAll nur bei
geänderter Zeitachse (CA_Tools/compute_state), Geometrie-Cache, Zeiten je Phase.
Protokoll: logs/lazysetup.log."""
import json
import os
import sys

import adsk.core
import adsk.fusion

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
import fs_log as L          # noqa: E402
import fs_geom as G
import fs_fusion as F       # noqa: E402
import fs_cam as C          # noqa: E402
import fs_run as R          # noqa: E402
import fs_edit as E         # noqa: E402
import fs_palette as P      # noqa: E402
import fs_catools as T      # noqa: E402


def _load_core(alias):
    """Gemeinsamen Kern (ca_core, identisch in LazyNest/LazySetup) unter EIGENEM Modulnamen laden."""
    import importlib.util
    if alias in sys.modules:
        return sys.modules[alias]
    d = os.path.join(_HERE, 'ca_core')
    spec = importlib.util.spec_from_file_location(alias, os.path.join(d, '__init__.py'), submodule_search_locations=[d])
    mod = importlib.util.module_from_spec(spec)
    sys.modules[alias] = mod
    spec.loader.exec_module(mod)
    return mod


CORE = _load_core('lazysetup_ca_core')
ca_i18n = CORE.ca_i18n
TH = CORE.ca_theme
REFS = CORE.ca_refs
DIAG = CORE.ca_diag
PRODUCT = 'lazysetup'

VERSION = '2.0.12'               # EINZIGE Versionsquelle (Manifest-Text, Tooltip, Protokoll, Operations-Attribut)
BUILD_DATE = '2026-11-06'
APP_NAME = 'CA LazySetup'
L.VERSION = VERSION
R.REFS = REFS                   # Prüfung veralteter Verknüpfungen vor computeAll (fs_run.compute_ok)
R.CC = CORE.ca_compute          # 2.0.3: gemeinsamer computeAll-Stand (CA_Tools/computed_state)

HERE = _HERE
RES = os.path.join(HERE, 'resources')
PRESET_FILE = os.path.join(HERE, 'user_presets.json')
SETTINGS_FILE = os.path.join(HERE, 'user_settings.json')
CMD_ID = 'LazySetup_Open'
EV_RUN = 'LazySetup_RunEvent'
EV_PERSIST = 'LazySetup_PersistEdits'
PALETTE_ID = 'LazySetup_Palette'
PAL_W, PAL_H = 1000, 800
PANELS = (('FusionSolidEnvironment', 'SolidScriptsAddinsPanel'),
          ('CAMEnvironment', 'CAMScriptsAddinsPanel'))
CA_WHERE = {'CAMEnvironment': 'cam'}          # FERTIGUNG > FRÄSEN > „CA Tools“ (großes Symbol)
TITLE = APP_NAME

_app = None
_ui = None
handlers = []
_custom_events = {}
_state = {'sheets': [], 'tools': None, 'pending': None, 'sel': None, 'cur': None, 'cfg': None, 'tool_label': None,
          'tnr': 0, 'fusion_bib': False, 'result': None, 'pal_hooked': False, 'editor': None, 'migration': None}

RICHTUNG = (('gleich', 'Gleichlauf (climb)'), ('gegen', 'Gegenlauf (konventionell)'))
GRUPPIERUNG = (('je_teil', 'Je Teil eine Operation (Reihenfolge garantiert)'),
               ('eine', 'Eine Operation, Reihenfolge beibehalten'))
STARTLAGE = (('ecke', 'Ecke nahe Plattenmitte'), ('kante', 'Kantenmitte zur Plattenmitte'),
             ('naechster', 'Nächster Punkt zur Mitte (ohne Eckbevorzugung)'))
REIHENFOLGE = (('rest', 'Größte zusammenhängende Restfläche (Vakuum)'),
               ('gewichtung', 'Gewichtung Fläche/Randnähe (alt, bis 1.0.6)'))
ANFAHR = (("rampe", "Rampe"), ("eintauchen", "Eintauchen"), ("bogen", "Bogen anfahren"))
STEGFORM = (('rechteckig', 'Rechteckig'), ('dreieckig', 'Dreieckig (Rampe)'))
NEUBERECHNEN = (('auto', 'Automatisch (nur wenn die Zeitachse geändert wurde)'), ('immer', 'Immer (langsam, sicher)'),
                ('nie', 'Nie (eigene Verantwortung)'))
BUILTIN_PRESETS = {
    'Standard': {},
    'Kleinteile sicher (mehr Stege)': {'steg_abstand_klein': 150.0, 'steg_abstand_mittel': 350.0, 'steg_min': 3,
                                       'steg_min_klein': 4, 'gross_ab_cm2': 4000.0, 'stege_gross': 2},
    'Starkes Vakuum (wenig Stege)': {'steg_abstand_mittel': 900.0, 'gross_ab_cm2': 1500.0, 'stege_gross': 0,
                                     'steg_min': 0, 'bruecken': False},
}

# (Schlüssel, Art, Beschriftung, Gruppe, Zusatz) – Art: f=Kommazahl, i=Ganzzahl, b=Ja/Nein, d=Auswahl
FIELDS = (
    # Vorfräsen – ein Durchgang, keine Stege/Brücken
    ('vorfraesen', 'b', 'Vorfräsen aktiv', 'schnitt_vor', None),
    ('richtung_vor', 'd', 'Fräsrichtung', 'schnitt_vor', RICHTUNG),
    ('vorfraes_rest_mm', 'f', 'Bodentiefe / Rest zum Fertig (mm)', 'schnitt_vor', (0.1, 20.0, 0.1)),
    ('vorfraes_aufmass', 'f', 'Seitliches Aufmaß (mm)', 'schnitt_vor', (0.0, 5.0, 0.1)),
    ('tool_label_vor', 's', 'Werkzeug', 'schnitt_vor', 'tool'),
    ('cut_preset_vor', 's', 'Schnittdaten', 'schnitt_vor', 'cut_preset'),
    ('cam_template_vor', 's', 'CAM-Vorlage', 'schnitt_vor', 'cam_template'),
    ('hdr_anfahr_vor', 'h', 'Anfahren / Einfahren', 'schnitt_vor', None),
    ('anfahr_art_vor', 'd', 'Anfahrart', 'schnitt_vor', ANFAHR),
    ('rampenwinkel_vor', 'f', 'Rampenwinkel (°)', 'schnitt_vor', (0.5, 45.0, 0.5)),
    ('rampenlaenge_vor', 'f', 'Rampenlänge / Abstand (mm)', 'schnitt_vor', (0.5, 200.0, 1.0)),
    ('bogenradius_vor', 'f', 'Bogenradius (mm)', 'schnitt_vor', (0.5, 100.0, 0.5)),
    ('einfahrt_pct_vor', 'f', 'Einfahrvorschub (%)', 'schnitt_vor', (5.0, 100.0, 5.0)),
    ('hdr_schnitt_vor', 'h', 'Zustellung', 'schnitt_vor', None),
    ('az_vor', 'f', 'Zustellung az (mm)', 'schnitt_vor', (0.1, 60.0, 0.5)),
    ('durchstich', 'f', 'Durchstich (mm)', 'schnitt_vor', (0.0, 5.0, 0.1)),
    ('innen_zuerst', 'b', 'Innenkonturen zuerst', 'schnitt_vor', None),
    ('taschen', 'b', 'Taschen einbeziehen (2D-Tasche)', 'schnitt_vor', None),
    ('gruppierung', 'd', 'Außenkonturen', 'schnitt_vor', GRUPPIERUNG),
    ('seite_umkehren', 'b', 'Werkzeugseite umkehren (falls Fusion innen fräst)', 'schnitt_vor', None),
    # Fertigfräsen
    ('richtung_final', 'd', 'Fräsrichtung', 'schnitt_final', RICHTUNG),
    ('schlicht_zugabe', 'f', 'Schlichtzugabe radial (mm)', 'schnitt_final', (0.0, 3.0, 0.1)),
    ('schlichtgang', 'b', 'Schlichtgang (2. Umlauf ohne Aufmaß)', 'schnitt_final', None),
    ('tool_label_final', 's', 'Werkzeug', 'schnitt_final', 'tool'),
    ('cut_preset_final', 's', 'Schnittdaten', 'schnitt_final', 'cut_preset'),
    ('cam_template_final', 's', 'CAM-Vorlage', 'schnitt_final', 'cam_template'),
    ('hdr_anfahr_final', 'h', 'Anfahren / Einfahren', 'schnitt_final', None),
    ('anfahr_art_final', 'd', 'Anfahrart', 'schnitt_final', ANFAHR),
    ('rampenwinkel_final', 'f', 'Rampenwinkel (°)', 'schnitt_final', (0.5, 45.0, 0.5)),
    ('rampenlaenge_final', 'f', 'Rampenlänge / Abstand (mm)', 'schnitt_final', (0.5, 200.0, 1.0)),
    ('bogenradius_final', 'f', 'Bogenradius (mm)', 'schnitt_final', (0.5, 100.0, 0.5)),
    ('einfahrt_pct_final', 'f', 'Einfahrvorschub (%)', 'schnitt_final', (5.0, 100.0, 5.0)),
    ('hdr_schnitt_final', 'h', 'Zustellung', 'schnitt_final', None),
    ('az_final', 'f', 'Zustellung az (mm)', 'schnitt_final', (0.1, 60.0, 0.5)),
    ('hdr_stege_final', 'h', 'Stege', 'schnitt_final', None),
    ('stege_final', 'b', 'Haltestege', 'schnitt_final', None),
    ('bruecken_final', 'b', 'Brückenstege', 'schnitt_final', None),
    ('steg_breite_final', 'f', 'Stegbreite (mm)', 'schnitt_final', (1.0, 50.0, 0.5)),
    ('steg_hoehe_final', 'f', 'Steghöhe (mm)', 'schnitt_final', (0.5, 20.0, 0.5)),
    ('steg_form_final', 'd', 'Stegform', 'schnitt_final', STEGFORM),
    ('reihenfolge', 'd', 'Reihenfolge-Regel', 'reihe', REIHENFOLGE),
    ('w_flaeche', 'i', 'Gewichtung Fläche % (nur Regel „alt“)', 'reihe', (0, 100, 5)),
    ('kleinteile_zuerst', 'b', 'Kleinteile (unter Mindestfläche) immer zuerst', 'reihe', None),
    ('start_modus', 'd', 'Startpunkt-Lage', 'reihe', STARTLAGE),
    ('kleinteile_kante', 'b', 'Kleinteile immer Kantenmitte', 'reihe', None),
    ('start_ecke_min', 'f', 'Kantenmitte: Mindestabstand zur Ecke (mm)', 'reihe', (0.0, 200.0, 1.0)),
    ('skizze_start', 'b', 'Startpunkte aus Skizze „Finalschnitt Startpunkte“', 'reihe', None),
    ('stege', 'b', 'Haltestege (Planung)', 'stege', None),
    ('steg_form', 'd', 'Stegform (Planung)', 'stege', STEGFORM),
    ('steg_breite', 'f', 'Stegbreite (mm, Planung)', 'stege', (1.0, 50.0, 0.5)),
    ('steg_hoehe', 'f', 'Steghöhe (mm, Planung)', 'stege', (0.5, 20.0, 0.5)),
    ('vak_min_cm2', 'f', 'Mindestfläche Vakuum (cm²)', 'stege', (0.0, 10000.0, 10.0)),
    ('steg_abstand_klein', 'f', 'Stegabstand Kleinteile (mm)', 'stege', (50.0, 2000.0, 10.0)),
    ('steg_abstand_mittel', 'f', 'Stegabstand mittlere Teile (mm)', 'stege', (50.0, 5000.0, 10.0)),
    ('gross_ab_cm2', 'f', 'Grenze große Teile (cm²)', 'stege', (0.0, 100000.0, 100.0)),
    ('stege_gross_an', 'b', 'Stege an großen Teilen (aus: nur Brücken zu kleinen/mittleren Teilen)', 'stege', None),
    ('stege_gross', 'i', 'Min. Stege bei großen Teilen (sonst nach Umfang)', 'stege', (0, 20, 1)),
    ('steg_abstand_min', 'f', 'Min. Stegabstand (mm)', 'stege', (10.0, 2000.0, 5.0)),
    ('steg_min', 'i', 'Min. Stege je Teil', 'stege', (0, 20, 1)),
    ('steg_min_klein', 'i', 'Min. Stege Kleinteile', 'stege', (0, 20, 1)),
    ('steg_max', 'i', 'Max. Stege je Teil', 'stege', (0, 50, 1)),
    ('start_abstand_min', 'f', 'Mindestabstand zum Startpunkt (mm)', 'stege', (0.0, 500.0, 5.0)),
    ('radius_min_faktor', 'f', 'Keine Stege bei Radius < Faktor × Werkzeug-Ø', 'stege', (0.0, 10.0, 0.1)),
    ('bruecken', 'b', 'Brückenstege (Planung)', 'stege', None),
    ('bruecke_extra', 'f', 'Brücke, wenn Abstand ≤ Werkzeug-Ø + (mm)', 'stege', (0.0, 20.0, 0.5)),
    ('bruecke_min_mm', 'f', 'Brücke: Mindest-Überlappung der Kanten (mm)', 'stege', (10.0, 2000.0, 5.0)),
    ('bruecke_je_mm', 'f', 'Brückenabstand auf langen Kanten (mm)', 'stege', (30.0, 5000.0, 10.0)),
    ('skizze_stege', 'b', 'Stege aus Skizze „Finalschnitt Stege“', 'stege', None),
    ('ersetzen', 'b', 'Vorhandene LazySetup-/Finalschnitt-Operationen ersetzen', 'ausgabe', None),
    ('berechnen', 'b', 'Werkzeugwege berechnen', 'ausgabe', None),
    ('neuberechnen', 'd', 'Konstruktion vor CAM neu berechnen (computeAll)', 'ausgabe', NEUBERECHNEN),
)
GROUPS = (('schnitt_vor', 'Vorfräsen'), ('schnitt_final', 'Fertigfräsen'),
          ('reihe', 'Reihenfolge und Start'), ('stege', 'Stege-Planung'), ('ausgabe', 'Ausgabe'))
TABS = (('Rohteile', ()), ('Werkzeug', ()), ('Bearbeitung', ('schnitt_vor', 'schnitt_final', 'reihe', 'ausgabe')), ('Stege', ('stege',)),
        ('Vorschau', ()), ('Ergebnis', ()))



# ---------------------------------------------------------------- Hilfen
def _msg(text):
    if _ui:
        _ui.messageBox(text, TITLE)


def _ask(text):
    try:
        r = _ui.messageBox(text, TITLE, adsk.core.MessageBoxButtonTypes.YesNoButtonType,
                           adsk.core.MessageBoxIconTypes.QuestionIconType)
        return r == adsk.core.DialogResults.DialogYes
    except Exception:
        L.exc('Rückfrage')
        return False


def _err(prefix):
    tb = L.exc(prefix)
    _msg('%s:\n%s\n\nProtokoll: %s' % (prefix, tb.strip().splitlines()[-1] if tb else '', L.LOG_FILE))


def _design():
    d = adsk.fusion.Design.cast(_app.activeProduct)
    if d is None:
        p = F._safe(lambda: _app.activeDocument.products.itemByProductType('DesignProductType'))
        d = adsk.fusion.Design.cast(p) if p is not None else None
    return d


def _load_json(path, default):
    try:
        with open(path, encoding='utf-8') as f:
            d = json.load(f)
        return d if isinstance(d, type(default)) else default
    except Exception:
        return default


def _save_json(path, data):
    try:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
        return True
    except Exception:
        L.exc('Speichern %s' % path)
        return False


def presets():
    p = {k: dict(G.DEFAULTS, **v) for k, v in BUILTIN_PRESETS.items()}
    for k, v in _load_json(PRESET_FILE, {}).items():
        if isinstance(v, dict):
            p[k] = dict(G.DEFAULTS, **{kk: vv for kk, vv in v.items() if kk in G.DEFAULTS})
    return p


def save_preset(name, cfg):
    name = (name or '').strip()
    if not name:
        return False
    d = _load_json(PRESET_FILE, {})
    d[name] = {k: cfg[k] for k in G.DEFAULTS if k in cfg}
    return _save_json(PRESET_FILE, d)


def initial_cfg():
    s = _load_json(SETTINGS_FILE, {})
    c = {k: v for k, v in s.get('cfg', {}).items() if k in G.DEFAULTS}
    if not s.get('version'):           # gespeichert vor Finalschnitt 1.0.2: „berechnen“ war nur Vorgabe
        c.pop('berechnen', None)
    return dict(G.DEFAULTS, **c), s


def clean_cfg(raw, base=None):
    """Werte aus der Palette prüfen/umwandeln (Typ, Grenzen, Auswahl) – nie blind übernehmen."""
    cfg = dict(base or G.DEFAULTS)
    raw = raw or {}
    for key, kind, _l, _g, extra in FIELDS:
        if kind == 'h' or key not in raw:
            continue
        v = raw[key]
        try:
            if kind == 'b':
                cfg[key] = bool(v)
            elif kind in ('f', 'i'):
                lo, hi, _st = extra
                x = float(str(v).replace(',', '.'))
                x = min(max(x, lo), hi)
                cfg[key] = int(round(x)) if kind == 'i' else x
            elif kind == 'd' and extra and v in [a for a, _b in extra]:
                cfg[key] = v
            elif kind == 's':
                cfg[key] = '' if v is None else str(v).strip()
        except (TypeError, ValueError):
            L.warn('Eingabe %s: %r ungültig – %r bleibt', key, v, cfg.get(key))
    if 'tool_d' in raw:
        try:
            cfg['tool_d'] = min(max(float(str(raw['tool_d']).replace(',', '.')), 1.0), 40.0)
        except (TypeError, ValueError):
            pass
    # 2.0.7: Legacy richtung/stege → vor/final (nur gültige Werte)
    _richt_ok = {a for a, _ in RICHTUNG}
    if 'richtung' in raw and 'richtung_vor' not in raw and 'richtung_final' not in raw:
        rv = raw.get('richtung')
        if rv in _richt_ok:
            cfg['richtung_vor'] = cfg['richtung_final'] = rv
    for rk in ('richtung_vor', 'richtung_final', 'richtung'):
        if rk in cfg and cfg[rk] not in _richt_ok:
            cfg[rk] = 'gleich'
    if 'richtung_vor' in cfg or 'richtung_final' in cfg:
        cfg['richtung'] = cfg.get('richtung_final', cfg.get('richtung_vor', cfg.get('richtung', 'gleich')))
    # 2.0.9: Vorfräs ohne Stege; Legacy zustellung → az_*; Final-Stege ↔ Planung
    cfg['stege_vor'] = False
    cfg['bruecken_vor'] = False
    if 'zustellung' in raw and 'az_vor' not in raw and 'az_final' not in raw:
        try:
            z = float(str(raw['zustellung']).replace(',', '.'))
            cfg['az_vor'] = cfg['az_final'] = z
            cfg['zustellung'] = z
        except (TypeError, ValueError):
            pass
    if 'az_vor' in cfg or 'az_final' in cfg:
        cfg['zustellung'] = float(cfg.get('az_vor') or cfg.get('az_final') or cfg.get('zustellung') or 6.0)
    for src, dsts in (
        ('stege', ('stege_final',)),
        ('steg_form', ('steg_form_final',)),
        ('steg_breite', ('steg_breite_final',)),
        ('steg_hoehe', ('steg_hoehe_final',)),
        ('bruecken', ('bruecken_final',)),
    ):
        if src in raw:
            for dkey in dsts:
                if dkey not in raw:
                    cfg[dkey] = cfg.get(src) if src in cfg else raw[src]
    touched = set(raw)
    if 'steg_form_final' in touched or 'steg_form' in touched:
        cfg['steg_form'] = cfg.get('steg_form_final', cfg.get('steg_form'))
    if 'steg_breite_final' in touched or 'steg_breite' in touched:
        cfg['steg_breite'] = cfg.get('steg_breite_final', cfg.get('steg_breite'))
    if 'steg_hoehe_final' in touched or 'steg_hoehe' in touched:
        cfg['steg_hoehe'] = cfg.get('steg_hoehe_final', cfg.get('steg_hoehe'))
    if 'stege_final' in touched or 'stege' in touched:
        cfg['stege'] = bool(cfg.get('stege_final', cfg.get('stege', True)))
    if 'bruecken_final' in touched or 'bruecken' in touched:
        cfg['bruecken'] = bool(cfg.get('bruecken_final', cfg.get('bruecken', True)))
    return cfg


def fields_payload(lang=None):
    lang = lang or (_state.get('language') if _state else None) or 'de'
    out = []
    for key, kind, label, grp, extra in FIELDS:
        lab = ca_i18n.field_label(key, lang)
        if lab == 'field.' + key:
            lab = label
        f = {'key': key, 'kind': kind, 'label': lab, 'group': grp}
        if kind == 'h':
            out.append(f)
            continue
        if kind in ('f', 'i'):
            f['min'], f['max'], f['step'] = extra
        elif kind == 'd':
            f['options'] = [[a, ca_i18n.opt_label(key, a, b, lang)] for a, b in extra]
        elif kind == 's':
            f['widget'] = extra
        out.append(f)
    return out


def groups_payload(lang=None):
    lang = lang or (_state.get('language') if _state else None) or 'de'
    return [[gid, ca_i18n.group_label(gid, title, lang)] for gid, title in GROUPS]


# ---------------------------------------------------------------- Werkzeug
def _load_tools(include_fusion=False, library_id=None):
    cam = C.get_cam(_app, _ui, create=False)
    if cam is None:
        _state['tools'] = None          # später erneut versuchen (FERTIGUNG noch nie geöffnet)
        _state['tool_libs'] = []
        return []
    lib = library_id if library_id is not None else _state.get('tool_library') or 'Dokument'
    _state['tool_library'] = lib
    _state['tool_libs'] = C.list_libraries(cam, include_fusion)
    _state['tools'] = C.list_tools(cam, include_fusion, library_id=lib)
    return _state['tools']


def _tool_text(entry, cfg):
    if entry is None:
        return ('Kein Werkzeug gewählt – Planung mit Ø %g mm; Werkzeug in Fusion nachtragen.' % cfg['tool_d'])
    i = entry['info']
    s = 'Ø %s mm, %s, %s Schneiden' % (('%g' % i['d_mm']) if i['d_mm'] else '?', i['type'] or '?', i['flutes'] or '?')
    if i.get('feed') or i.get('rpm'):
        s += '; Vorschub %s, Drehzahl %s (aus Werkzeug)' % (i.get('feed') or '?', i.get('rpm') or '?')
    else:
        s += '; Schnittdaten aus dem Werkzeug'
    return s


def tool_entry(tools, label, tnr, tool_d):
    """Gewähltes Werkzeug: Name des Eintrags, sonst Werkzeugnummer, sonst automatisch (wie 1.3.1)."""
    tools = tools or []
    hit = next((t for t in tools if t['label'] == label), None) if label else None
    if hit is None and tnr and int(tnr) > 0:
        hit = C.tool_by_number(tools, int(tnr))
    if hit is None and not (tnr and int(tnr) > 0) and not label:
        k = C.default_tool(tools, None, tool_d)
        hit = tools[k] if k is not None else None
    return hit


def _current_tool():
    cfg = _state['cfg'] or initial_cfg()[0]
    return tool_entry(_state.get('tools'), _state.get('tool_label'), _state.get('tnr'), float(cfg['tool_d']))


def _plan_cfg():
    return R.plan_cfg(_state['cfg'] or initial_cfg()[0], _current_tool())


# ---------------------------------------------------------------- Vorschau-Text
START_TEXT = {'ecke': 'Ecke', 'kante': 'Kantenmitte', 'naechster': 'nächster Punkt', 'manuell': 'aus Skizze'}


def _start_text(o, cfg):
    m = o.get('start_mode') or ''
    want = cfg.get('start_modus', 'ecke')
    if o.get('small') and cfg.get('kleinteile_kante'):
        want = 'kante'
    if not m or m == want or (want == 'ecke' and m == 'naechster'):
        return ''
    return ', Start: %s' % START_TEXT.get(m, m)


def info_rows(sh, cfg, plan):
    """Zeilen unter der Vorschau: Reihenfolge, Stege, Restfläche, Brücken, Warnungen (wie 1.3.1)."""
    rows = []
    if cfg.get('skizze_stege'):
        rows.append('⚠ Stege kommen aus Skizze „%s“ – Steg-Einstellungen wirkungslos' % C.SK_TABS)
    if cfg.get('skizze_start'):
        rows.append('⚠ Startpunkte kommen aus Skizze „%s“ – Startpunkt-Lage wirkungslos' % C.SK_START)
    sm = G.plan_summary(plan)
    man = bool((plan.get('overrides') or {}).get('order_manual'))
    rule = ('von Hand' if man else
            ('größte Restfläche' if sm['order_rule'] == 'rest' else 'Gewichtung (alt)'))
    rows.append('%s: Reihenfolge nach %s (Tiefe %s)%s' % (
        sh['name'], rule, C.depth_text(cfg, sh['thickness']),
        ' – ▲▼ unten zum Ändern' if not man else ' – ▲▼ / „Auto“ zum Zurücksetzen'))
    rest = {e['nr']: e for e in sm['order_info']}
    order_ui = []
    for o in sm['order']:
        e = rest.get(o['nr'])
        rows.append('%d. %s – %.0f cm²%s, %d Stege%s%s%s' % (
            o['nr'], o['name'], o['area_cm2'], ' (Kleinteil)' if o['small'] else '', len(o['tabs']),
            ', %d Durchbrüche' % o['holes'] if o['holes'] else '', _start_text(o, cfg),
            (', danach Rest %.0f %%%s' % (e['rest_pct'], ' (%d Bereiche)' % e['bereiche']
                                          if e['bereiche'] > 1 else '')) if e else ''))
        order_ui.append({'nr': o['nr'], 'name': o['name'], 'key': o.get('key')})
    # order_ui wird in _plan_payload angehängt
    if sm['bridges']:
        rows.append('Brückenstege: ' + ', '.join('%s–%s' % (b['a'], b['b']) for b in sm['bridges']))
    rows += ['⚠ ' + w for w in sm['warnings'] if 'wirkungslos' not in w]
    info_rows.last_order_ui = order_ui
    return rows


def sketch_hints(sheets, cfg):
    hints = []
    for key, sk, lbl in (('skizze_start', C.SK_START, 'Startpunkte aus Skizze'),
                         ('skizze_stege', C.SK_TABS, 'Stege aus Skizze')):
        on = bool(cfg.get(key))
        for s in sheets:
            try:
                n = len(C.read_sketch_points(s, sk))
            except Exception:
                L.exc('Skizze lesen %s' % sk)
                continue
            if n and not on:
                hints.append('%s: Skizze „%s“ hat %d Punkt(e) – „%s“ anhaken, um sie zu verwenden'
                             % (s['name'], sk, n, lbl))
    return hints


# ---------------------------------------------------------------- Palette
def _editor():
    ed_ = _state.get('editor')
    if ed_ is None:
        ed_ = P.Editor(on_change=_edited, on_close=None)
        _state['editor'] = ed_
    return ed_


def _sel_sheets():
    sel = _state.get('sel')
    return [s for s in _state['sheets'] if sel is None or s['name'] in sel]


def _editor_setup():
    _editor().setup(_sel_sheets(), _plan_cfg(), _state.get('cur'))
    _state['cur'] = _editor().current


def _plan_payload(msgs=None):
    """Plan des gezeigten Rohteils (für die Vorschau-Ansicht) + Textzeilen."""
    _editor_setup()
    ed_ = _editor()
    d = json.loads(ed_.payload(msgs))
    sh = ed_.sheet()
    if sh is not None:
        try:
            pln = ed_.plan(sh)
            d['rows'] = info_rows(sh, ed_.cfg, pln)
            d['order_ui'] = getattr(info_rows, 'last_order_ui', None) or []
            d['order_manual'] = bool((pln.get('overrides') or {}).get('order_manual'))
            d['order_keys'] = [x.get('key') for x in d['order_ui']]
        except Exception:
            L.exc('Vorschau-Text')
            d['rows'] = []
            d['order_ui'] = []
        if any(not E.is_empty(E.load(s)) for s in _state['sheets'] if s['parts']):
            d['rows'].append('ℹ Bearbeitungen von Hand aktiv („↺ Alle zurücksetzen“ verwirft sie)')
    d['hints'] = _state.get('hints') or []
    return d


def _edited(sheet_name):
    L.info('Bearbeitung in %s gespeichert', sheet_name)


def _sheets_payload():
    sel = _state.get('sel')
    return [{'name': s['name'], 'parts': len(s['parts']), 'label': s.get('label') or '',
             'source': (s.get('diag') or {}).get('source') or '', 'checked': sel is None or s['name'] in sel,
             'edited': not E.is_empty(F._safe(lambda: E.load(s), E.empty()) or E.empty())}
            for s in _state['sheets']]


def _tools_payload():
    tools = _state.get('tools') or []
    te = _current_tool()
    libs = _state.get('tool_libs') or [{'id': 'Dokument', 'label': 'Dokument (aktuelles Setup)'}]
    lib_ids = ['Dokument'] + [x['id'] for x in libs if x['id'] != 'Dokument']
    # unique preserve order
    seen, lib_ids_u = set(), []
    for i in lib_ids:
        if i not in seen:
            seen.add(i); lib_ids_u.append(i)
    items = []
    for t in tools:
        items.append({'label': t['label'], 'cut_presets': C.cut_presets_of(t.get('tool'))})
    return {'list': [t['label'] for t in tools], 'items': items,
            'selected': te['label'] if te else '',
            'label': _state.get('tool_label') or '', 'tnr': int(_state.get('tnr') or 0),
            'fusionBib': bool(_state.get('fusion_bib')), 'text': _tool_text(te, _plan_cfg()),
            'available': _state.get('tools') is not None,
            'libraries': [{'id': x if isinstance(x, str) else x['id'],
                           'label': x if isinstance(x, str) else x.get('label') or x['id']}
                          for x in (libs if libs else [{'id': 'Dokument', 'label': 'Dokument'}])],
            'library': _state.get('tool_library') or 'Dokument'}


def _templates_payload(refresh=False):
    """CAM-Vorlagen Lokal+Cloud; Cache bis Aktualisieren."""
    if refresh or _state.get('templates') is None:
        try:
            _state['templates'] = C.list_templates()
        except Exception:
            L.exc('CAM-Vorlagen listen')
            _state['templates'] = []
    return list(_state.get('templates') or [])


def _pass_tool_entry(label):
    """Werkzeug eines Vorfräs-/Fertig-Blocks (Label); None wenn leer/unbekannt."""
    label = (label or '').strip()
    if not label:
        return None
    return tool_entry(_state.get('tools'), label, 0, float((_state.get('cfg') or G.DEFAULTS)['tool_d']))


def _license_status():
    """OSS: immer frei (kein Schlüssel/Trial)."""
    return {'line': 'Open Source – kostenlos', 'licensed': True, 'apply_allowed': True,
            'machine_id': '', 'enforce': False, 'edition': 'OSS', 'products_line': ''}


def _theme():
    t, src = TH.detect(_app, L.info)
    if _state.get('theme_src') != src:
        _state['theme_src'] = src
        L.info('Farbschema: %s (%s)', t, src)
    return t


def _read_design(reason):
    design = _design()
    if design is None:
        _state['sheets'] = []
        return None
    if _state.get('sheets'):
        n = F._safe(lambda: E.persist_all(_state['sheets']), 0)
        if n:
            L.info('Bearbeitungen von %d Rohteil(en) gesichert', n)
    E.clear_mem()
    warn = []
    L.checkpoint('%s: Rohteile lesen' % reason)
    old = set(s['name'] for s in _state['sheets'])
    _state['sheets'] = R.collect(design, None, None, warn)
    for w in warn:
        L.warn(w)
    _state['sil_warn'] = [w for w in warn if 'Silhouette' in w]     # 2.0.1: im Fenster anzeigen
    names = [s['name'] for s in _state['sheets']]
    if _state.get('sel') is not None:          # Häkchen behalten, neue Rohteile angehakt
        _state['sel'] = [n for n in names if n in _state['sel'] or n not in old]
    _state['hints'] = sketch_hints(_state['sheets'], _plan_cfg())
    L.info('%s: %d Rohteil(e): %s', reason, len(names), ', '.join('%s %d Teile' % (s['name'], len(s['parts']))
                                                                  for s in _state['sheets']))
    return design


def _session():
    design = _design()
    cfg = _state['cfg'] or initial_cfg()[0]
    lic = _license_status()
    od = REFS.outdated(design)[0] if design else []
    return {'version': VERSION, 'buildDate': BUILD_DATE, 'theme': _theme(), 'design': bool(design),
            'fields': fields_payload(), 'groups': groups_payload(), 'cfg': cfg,
            'toolD': cfg.get('tool_d'), 'presets': sorted(presets().keys()), 'sheets': _sheets_payload(),
            'tools': _tools_payload(), 'templates': _templates_payload(),
            'plan': _plan_payload() if _sel_sheets() else None,
            'result': _state.get('result'), 'license': lic,
            'info': DIAG.info_payload(PRODUCT, APP_NAME, VERSION, BUILD_DATE, lic),
            'logDir': L.LOG_DIR, 'logFile': L.LOG_FILE, 'migration': _state.get('migration'),
            'outdated': od, 'silhouette': _state.get('sil_warn') or [], 'lastTab': _load_json(SETTINGS_FILE, {}).get('last_tab') or 'Rohteile',
            'i18n': _i18n_payload()}


def _to_palette(action, data):
    pal = F._safe(lambda: _ui.palettes.itemById(PALETTE_ID))
    if pal is None:
        return None
    try:
        txt = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False, default=str)
        return pal.sendInfoToHTML(action, txt)
    except Exception:
        L.exc('sendInfoToHTML(%s)' % action)
        return None


def _diag_text():
    lic = _license_status()
    rows = DIAG.diag_text(APP_NAME, VERSION, BUILD_DATE, _app, lic, L.LOG_FILE, {
        'Pfad': HERE, 'Farbschema': '%s (%s)' % (_theme(), _state.get('theme_src')),
        'Rohteile': ', '.join('%s (%d Teile)' % (s['name'], len(s['parts'])) for s in _state['sheets']) or '–',
        'Werkzeug': (_current_tool() or {}).get('label') or '–'})
    try:
        with open(L.LOG_FILE, 'r', encoding='utf-8-sig', errors='replace') as fh:
            tail = fh.readlines()[-40:]
        rows += '\n--- letzte Protokollzeilen ---\n' + ''.join(tail)
    except Exception:
        pass
    return rows


def sil_diag():
    """Gewählte Rohteile mit Diagnose neu lesen (nur lesen, keine Änderung) und je Teil die Flächendaten,
    Schnellweg-Entscheidung und Silhouetten-Info (offene Enden) in logs/silhouette_diag_*.json schreiben."""
    design = _design()
    if design is None:
        return {'error': 'Keine Konstruktion aktiv.'}
    names = [s['name'] for s in _sel_sheets()] or None
    F.DIAG.update(on=True, parts=[])
    warn = []
    try:
        sheets = R.collect(design, None, names, warn)
        out = {'version': VERSION, 'sheets': [], 'warnings': warn}
        for sh in sheets:
            out['sheets'].append({'name': sh['name'], 'parts': [
                {'name': p.get('name'), 'how': p['geo'].get('how'), 'path': p['geo'].get('path'),
                 'methods': p['geo'].get('methods'), 'bbox_gap_mm': p['geo'].get('bbox_gap'),
                 'open_ends': p['geo'].get('sil_open')} for p in sh['parts']]})
        out['parts'] = F.DIAG['parts']
        k = len(F.DIAG['parts'])
        path = L.dump_json('silhouette_diag', out)
        L.info('Diagnose-Silhouette: %d Teil(e) -> %s', k, path)
        return {'ok': True, 'file': path, 'parts': k, 'warnings': warn}
    except Exception as e:
        L.exc('Diagnose-Silhouette')
        return {'error': 'Diagnose-Silhouette fehlgeschlagen: %s' % e}
    finally:
        F.DIAG.update(on=False, parts=[])



def _lang():
    try:
        return ca_i18n.normalize_lang((_load_json(SETTINGS_FILE, {}) or {}).get('language') or 'de')
    except Exception:
        return 'de'

def _i18n_payload():
    return ca_i18n.payload(_lang())

def _save_settings():
    cfg = _state['cfg'] or initial_cfg()[0]
    te = _current_tool()
    pc = R.plan_cfg(cfg, te)
    old = _load_json(SETTINGS_FILE, {})
    sett = dict(old, version=VERSION, cfg=cfg, tool_d_werkzeug=pc['tool_d'], tool_label=_state.get('tool_label'), tool_library=_state.get('tool_library') or 'Dokument',
                tool_number=int(_state.get('tnr') or 0), fusion_bib=bool(_state.get('fusion_bib')),
                last_tab=_state.get('last_tab') or old.get('last_tab'),
                language=_state.get('language') or old.get('language') or 'de')
    return _save_json(SETTINGS_FILE, sett)


def _sheets_stale():
    """2.0.4: gemerkte Rohteile ungültig (Nesting in LazyNest gelöscht oder Rohteil von Hand entfernt)?"""
    for s in _state.get('sheets') or []:
        occ = s.get('occ')
        if occ is None:
            continue
        try:
            if getattr(occ, 'isValid', True) is False:
                return True
        except Exception:
            return True          # Zugriff auf gelöschtes Objekt wirft
    return False


def handle(act, d):
    """Palette -> Python (testbar). Rückgabe: dict/str für returnData."""
    if act == 'ready':
        _state['pal_ready'] = True
        _state['language'] = _lang()
        if not _state['sheets'] or _sheets_stale():
            _read_design('Palette geöffnet')
        return _session()
    if act in ('cfg', 'sheet', 'edit', 'run') and _sheets_stale():
        L.warn('Rohteile wurden gelöscht/geändert – Konstruktion neu gelesen (%s)', act)
        _read_design('Rohteil gelöscht')
        if act != 'cfg':
            s = _session()
            s['error'] = ('Rohteile haben sich geändert (Nesting gelöscht?) – bitte „Aktualisieren“, Auswahl '
                          'prüfen und erneut ausführen.')
            return s
    if act == 'cfg':                       # Einstellungen geändert -> Vorschau neu
        _state['cfg'] = clean_cfg(d.get('cfg'), _state['cfg'] or initial_cfg()[0])
        if 'tool' in d:
            t = d['tool'] or {}
            _state['tool_label'] = t.get('label') or None
            try:
                _state['tnr'] = max(0, int(t.get('tnr') or 0))
            except (TypeError, ValueError):
                _state['tnr'] = 0
        if 'sel' in d and isinstance(d['sel'], list):
            _state['sel'] = [n for n in d['sel'] if any(s['name'] == n for s in _state['sheets'])]
        if d.get('cur'):
            _state['cur'] = d['cur']
        return {'plan': _plan_payload() if _sel_sheets() else None, 'tools': _tools_payload(),
                'sheets': _sheets_payload()}
    if act == 'fusionBib':
        _state['fusion_bib'] = bool(d.get('on'))
        _load_tools(_state['fusion_bib'], _state.get('tool_library'))
        return {'tools': _tools_payload(), 'plan': _plan_payload() if _sel_sheets() else None}
    if act == 'toolLib':
        _state['tool_library'] = d.get('id') or 'Dokument'
        _state['tool_label'] = None          # Auswahl zurücksetzen, wenn Bibliothek wechselt
        _load_tools(_state.get('fusion_bib'), _state['tool_library'])
        return {'tools': _tools_payload(), 'plan': _plan_payload() if _sel_sheets() else None}
    if act == 'refresh':
        _read_design('Aktualisieren')
        if _state.get('tools') is None:
            _load_tools(_state.get('fusion_bib'))
        _state['templates'] = None
        return _session()
    if act == 'presetLoad':
        p = presets().get(d.get('name'))
        if not p:
            return {'error': 'Vorlage nicht gefunden'}
        _state['cfg'] = clean_cfg(p, _state['cfg'] or initial_cfg()[0])
        L.info('Vorlage geladen: %s', d.get('name'))
        return {'cfg': _state['cfg'], 'plan': _plan_payload() if _sel_sheets() else None}
    if act == 'presetSave':
        ok = save_preset(d.get('name'), _state['cfg'] or initial_cfg()[0])
        return {'ok': ok, 'presets': sorted(presets().keys())}
    if act in ('sheet', 'edit'):
        _editor_setup()
        rep = json.loads(_editor().handle(act, d))
        _state['cur'] = _editor().current
        if rep.get('parts') is not None:
            rep = dict(_plan_payload(rep.get('msgs')), msgs=rep.get('msgs') or [])
        return {'plan': rep}
    if act == 'language':
        _state['language'] = ca_i18n.normalize_lang(d.get('language') or 'de')
        _save_settings()
        return {'i18n': _i18n_payload(), 'ok': True, 'fields': fields_payload(), 'groups': groups_payload()}
    if act == 'tab':
        _state['last_tab'] = d.get('tab')
        return 'OK'
    if act == 'run':
        if not _sel_sheets():
            return {'error': 'Kein Rohteil gewählt.'}
        cfg = _state['cfg'] or initial_cfg()[0]
        te = _current_tool()
        packed = dict(te) if te else {'tool': None, 'label': '', 'info': {}}
        packed['vor'] = _pass_tool_entry(cfg.get('tool_label_vor')) or te
        packed['final'] = _pass_tool_entry(cfg.get('tool_label_final')) or te
        _save_settings()
        names = [s['name'] for s in _sel_sheets()]
        _state['pending'] = {'cfg': cfg, 'tool': packed, 'names': names}
        L.info('Ausführen: Rohteile %s, Werkzeug %s / Vor %s / Fertig %s, cfg %s', names,
               (te or {}).get('label') or '-', (packed.get('vor') or {}).get('label') or '-',
               (packed.get('final') or {}).get('label') or '-', json.dumps(cfg, ensure_ascii=True))
        _fire(EV_RUN)
        return {'ok': True}
    if act == 'license':
        return _license_status()  # OSS: ignoriert Schlüssel
    if act == 'openLogs':
        return {'ok': DIAG.open_folder(L.LOG_DIR), 'path': L.LOG_DIR}
    if act == 'silDiag':                   # 2.0.2: Diagnose-Silhouette – Flächendaten je Teil als JSON
        return sil_diag()
    if act == 'diag':
        txt = _diag_text()
        path = L.path('diagnose_%s.txt' % L.stamp())
        try:
            with open(path, 'w', encoding='utf-8-sig') as fh:
                fh.write(txt)
        except Exception:
            path = ''
        return {'text': txt, 'file': path}
    if act == 'close':
        F._safe(lambda: E.persist_all(_state.get('sheets')))
        _save_settings()
        pal = F._safe(lambda: _ui.palettes.itemById(PALETTE_ID))
        if pal is not None:
            F._safe(lambda: setattr(pal, 'isVisible', False))
        return 'OK'
    return {'error': 'Unbekannte Aktion %s' % act}


class PaletteHTML(adsk.core.HTMLEventHandler):
    def notify(self, args):
        try:
            ha = adsk.core.HTMLEventArgs.cast(args)
            act = ha.action
            L.info('Palette -> Python: %s (%d Zeichen)', act, len(ha.data or ''))
            try:
                d = json.loads(ha.data or '{}')
            except ValueError:
                d = {}
            r = handle(act, d if isinstance(d, dict) else {})
            ha.returnData = r if isinstance(r, str) else json.dumps(r, ensure_ascii=False, default=str)
        except Exception:
            L.exc('Palette')
            try:
                ha.returnData = json.dumps({'error': 'Interner Fehler – siehe Protokoll %s' % L.LOG_FILE})
            except Exception:
                pass


class PaletteClosed(adsk.core.UserInterfaceGeneralEventHandler):
    def notify(self, args):
        if _state.get('stopping'):
            return
        _fire_soft(EV_PERSIST)


def _show_palette():
    pal = _ui.palettes.itemById(PALETTE_ID)
    if pal and _state.get('pal_hooked'):
        _read_design('Fenster geöffnet')
        pal.isVisible = True
        _to_palette('session', _session())
        return pal
    if pal:
        pal.deleteMe()
    url = os.path.join(HERE, 'palette', 'index.html').replace('\\', '/')
    _read_design('Fenster geöffnet')
    pal = _ui.palettes.add(PALETTE_ID, '%s %s' % (APP_NAME, VERSION), url, True, True, True, PAL_W, PAL_H)
    F._safe(lambda: setattr(pal, 'dockingState', adsk.core.PaletteDockingStates.PaletteDockStateFloating))
    h = PaletteHTML()
    pal.incomingFromHTML.add(h)
    handlers.append(h)
    hc = PaletteClosed()
    pal.closed.add(hc)
    handlers.append(hc)
    _state['pal_hooked'] = True
    L.info('Palette angelegt (%s)', url)
    return pal


# ---------------------------------------------------------------- Ablauf
def _fire_soft(ev_id):
    try:
        if ev_id not in _custom_events:
            raise RuntimeError('nicht registriert')
        _app.fireCustomEvent(ev_id, '')
    except Exception as e:
        L.info('fireCustomEvent(%s): %s – direkt', ev_id, e)
        _deferred(ev_id)


def _fire(ev_id):
    """Fusion 2705 liefert bei fireCustomEvent immer False, stellt das Ereignis aber zu: Rückgabe ignorieren.
    CAM-Arbeit NUR im verzögerten Schritt – nie im Palette-Handler."""
    try:
        if ev_id not in _custom_events:
            raise RuntimeError('Ereignis %s nicht registriert' % ev_id)
        ok = _app.fireCustomEvent(ev_id, '')
        L.info('fireCustomEvent(%s) -> %s (ignoriert)', ev_id, ok)
    except Exception:
        L.exc('fireCustomEvent')
        _state.pop('pending', None)
        _msg('%s konnte den Ablauf nicht verzögert starten – nichts geändert. Bitte erneut ausführen.'
             '\n\nProtokoll: %s' % (APP_NAME, L.LOG_DIR))


def _ask_setup(sheet):
    return _ask('Für „%s“ gibt es kein CAM-Setup.\n\nJa = einfaches Setup hier anlegen (Modelle = Teile, '
                'Rohteil = Körper „Rohteil“, Nullpunkt links unten auf der Plattenunterseite).\n'
                'Nein = Rohteil überspringen (Setup besser mit CA LazyNest anlegen: „Nesting bearbeiten“ → '
                'Übernehmen).' % sheet['name'])


def _run_pending():
    pend = _state.pop('pending', None)
    if not pend:
        return
    try:
        F._safe(lambda: E.persist_all(_state.get('sheets')))
        design = _design()
        _to_palette('status', 'Operationen werden erstellt …')
        res = R.run(_app, _ui, design, pend['cfg'], pend['names'], pend['tool'], VERSION, _ask_setup)
        _state['result'] = {'lines': res['lines'], 'warnings': res['warnings'], 'ops': res['ops'],
                            'errors': res['errors'], 'aborted': bool(res.get('aborted')),
                            'plan_file': res.get('plan_file'), 'names': pend['names']}
        _to_palette('result', _state['result'])
        text = '\n'.join(res['lines'])
        if res['warnings']:
            text += '\n\nHinweise:\n• ' + '\n• '.join(res['warnings'][:15])
            if len(res['warnings']) > 15:
                text += '\n• … (%d weitere im Protokoll)' % (len(res['warnings']) - 15)
        text += '\n\nProtokoll: %s' % L.LOG_DIR
        _msg(text)
    except Exception:
        _err(APP_NAME)


def _deferred(ev_id):
    if ev_id == EV_RUN:
        _run_pending()
    elif ev_id == EV_PERSIST:
        n = F._safe(lambda: E.persist_all(_state.get('sheets')), 0)
        _save_settings()
        L.info('Fenster geschlossen – Bearbeitungen gesichert: %s Rohteil(e)', n)


class DeferredEvent(adsk.core.CustomEventHandler):
    def __init__(self, ev_id):
        super().__init__()
        self.ev_id = ev_id

    def notify(self, args):
        try:
            L.info('CustomEvent %s empfangen', self.ev_id)
            _deferred(self.ev_id)
        except Exception:
            _err(APP_NAME)


class CommandCreated(adsk.core.CommandCreatedEventHandler):
    def notify(self, args):
        try:
            cmd = args.command
            cmd.isRepeatable = False
            h = OpenExecute()
            cmd.execute.add(h)
            handlers.append(h)
        except Exception:
            _err('Fenster öffnen')


class OpenExecute(adsk.core.CommandEventHandler):
    def notify(self, args):
        try:
            if _design() is None:
                _msg('Kein Konstruktionsdokument aktiv.')
                return
            if _state.get('tools') is None:
                _load_tools(bool(_state.get('fusion_bib')))
            _show_palette()
        except Exception:
            _err('Fenster öffnen')


def _tlog(level, msg):
    (L.warn if level == 'WARN' else L.info)('%s', msg)


def _panel(ws, pid):
    p = F._safe(lambda: ws.toolbarPanels.itemById(pid))
    if p is None and ws is not None:
        for i in range(F._safe(lambda: ws.toolbarPanels.count, 0) or 0):
            q = ws.toolbarPanels.item(i)
            if 'Addins' in (F._safe(lambda: q.id, '') or ''):
                return q
    return p


def _migrate():
    """Einmalig: user_settings.json / user_presets.json aus Finalschnitt (oder Finalschnitt_backup_*)."""
    try:
        extra = []
        ad = os.environ.get('APPDATA')
        if ad:
            extra.append(os.path.join(ad, 'Autodesk', 'Autodesk Fusion 360', 'API', 'AddIns', 'Finalschnitt'))
        rep = CORE.ca_migrate.run_once(HERE, SETTINGS_FILE, 'Finalschnitt', ('user_settings.json', 'user_presets.json'),
                                       False, extra, L.warn, mark_key='migrated_from_finalschnitt')
        if rep is not None:
            L.info('Migration Finalschnitt -> LazySetup: Quelle %s, übernommen %s, vorhanden %s', rep['source'],
                   rep['copied'], rep['skipped'])
            _state['migration'] = {'source': rep['source'], 'copied': len(rep['copied'])} if rep['copied'] else None
    except Exception:
        L.exc('Migration Finalschnitt')


def run(context):
    global _app, _ui
    try:
        _app = adsk.core.Application.get()
        _ui = _app.userInterface
        L.info('==== %s v%s run() – Fusion %s, Python %s, Pfad %s', APP_NAME, VERSION,
               F._safe(lambda: _app.version), sys.version.split()[0], HERE)
        _migrate()
        cfg, sett = initial_cfg()
        _state.update(cfg=cfg, tool_label=sett.get('tool_label'), tnr=int(sett.get('tool_number', 0) or 0),
                      fusion_bib=bool(sett.get('fusion_bib', False)),
                      tool_library=sett.get('tool_library') or 'Dokument')
        for ev_id in (EV_RUN, EV_PERSIST):
            F._safe(lambda: _app.unregisterCustomEvent(ev_id))
            ev = _app.registerCustomEvent(ev_id)
            h = DeferredEvent(ev_id)
            ev.add(h)
            handlers.append(h)
            _custom_events[ev_id] = (ev, h)
        cd = _ui.commandDefinitions.itemById(CMD_ID)
        if cd:
            cd.deleteMe()
        cd = _ui.commandDefinitions.addButtonDefinition(
            CMD_ID, 'CA LazySetup',
            'Fertigschnitt für LazyNest-Rohteile: 2D-Kontur-Operationen, Innen vor Außen, Reihenfolge fürs Vakuum, '
            'Start zur Restfläche, Halte-/Brückenstege per Klick\n(CA LazySetup v%s)' % VERSION,
            os.path.join(RES, 'LazySetup'))
        h = CommandCreated()
        cd.commandCreated.add(h)
        handlers.append(h)
        for ws_id, pid in PANELS:
            ws = F._safe(lambda: _ui.workspaces.itemById(ws_id))
            panel = T.get_panel(_ui, CA_WHERE[ws_id], _tlog) if ws_id in CA_WHERE else None
            big = panel is not None
            if panel is None:
                panel = _panel(ws, pid)
            if panel is None:
                L.warn('Panel %s in %s nicht gefunden', pid, ws_id)
                continue
            ctl = panel.controls.itemById(CMD_ID)
            if ctl:
                ctl.deleteMe()
            ctl = panel.controls.addCommand(cd)
            if big and ctl is not None:
                F._safe(lambda: setattr(ctl, 'isPromotedByDefault', True))
                F._safe(lambda: setattr(ctl, 'isPromoted', True))
            L.info('Befehl in Panel %s (%s)', F._safe(lambda: panel.id), ws_id)
        T.register(_ui, 'LazySetup', VERSION, os.path.join(RES, 'CATools'), handlers, _tlog)
    except Exception:
        tb = L.exc('run()')
        if _ui:
            _ui.messageBox('%s konnte nicht gestartet werden:\n%s' % (APP_NAME, tb))


def _obj_valid(obj):
    """Fusion-Proxy noch benutzbar? isValid=False oder Exception -> nein (kein Native-Zugriff danach)."""
    if obj is None:
        return False
    try:
        return getattr(obj, 'isValid', True) is not False
    except Exception:
        return False


def _design_alive():
    try:
        if not _app:
            return False
        d = adsk.fusion.Design.cast(_app.activeProduct)
        if d is None:
            prod = F._safe(lambda: _app.activeDocument.products.itemByProductType('DesignProductType'))
            d = adsk.fusion.Design.cast(prod) if prod else None
        return _obj_valid(d)
    except Exception:
        return False


def stop(context):
    try:
        _state['stopping'] = True
        L.info('==== %s stop() start', APP_NAME)
        if _design_alive():
            F._safe(lambda: E.persist_all(_state.get('sheets')))
        else:
            L.info('stop(): persist übersprungen (kein gültiges Design)')
        if _ui:
            pal = F._safe(lambda: _ui.palettes.itemById(PALETTE_ID))
            if _obj_valid(pal):
                F._safe(lambda: pal.deleteMe())
            else:
                L.info('stop(): Palette deleteMe übersprungen')
        _state['pal_hooked'] = False
        _state['editor'] = None
        for ev_id, (ev, h) in list(_custom_events.items()):
            F._safe(lambda: ev.remove(h))
            F._safe(lambda: _app.unregisterCustomEvent(ev_id))
        _custom_events.clear()
        if _ui:
            T.unregister(_ui, 'LazySetup', [CMD_ID], _tlog)
            for ws_id, pid in PANELS:
                ws = F._safe(lambda: _ui.workspaces.itemById(ws_id))
                panel = _panel(ws, pid)
                ctl = F._safe(lambda: panel.controls.itemById(CMD_ID)) if panel else None
                if _obj_valid(ctl):
                    F._safe(lambda: ctl.deleteMe())
            cd = F._safe(lambda: _ui.commandDefinitions.itemById(CMD_ID))
            if _obj_valid(cd):
                F._safe(lambda: cd.deleteMe())
    except Exception:
        L.exc('stop()')
    handlers.clear()
    _state['tools'] = None
    L.info('==== %s stop()', APP_NAME)
