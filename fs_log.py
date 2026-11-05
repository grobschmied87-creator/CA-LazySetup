# -*- coding: utf-8 -*-
"""Datei-Protokoll für CA LazySetup (vormals Finalschnitt) (Selbstdiagnose auf dem Anwender-PC).

logs/finalschnitt.log        laufendes Protokoll (UTF-8 mit BOM, rotierend, max. 2 MB × 4 Dateien), jede Zeile sofort
logs/*.json                  reines ASCII (Umlaute als Unicode-Escapes) – kodierungsunabhängig
logs/plan_<zeit>.json        Planung je Ausführung (Reihenfolge, Startpunkte, Stege, Brücken)
logs/params_<strategie>_<zeit>.json  vollständige Parameterliste einer erzeugten Operation (echte Namen/Werte)
logs/preview_<rohteil>_<zeit>.png    Vorschau (Reihenfolge, Startpunkte, Stege)
Das Protokoll darf NIE eine Funktion stören: jeder Fehler hier wird verschluckt."""
import datetime
import json
import os
import traceback

LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logs')
LOG_FILE = os.path.join(LOG_DIR, 'lazysetup.log')
VERSION = ''          # wird von LazySetup.py gesetzt
MAX_BYTES = 2 * 1024 * 1024
BACKUPS = 3
KEEP_JSON = 40


_bom_checked = []


def _has_bom(path):
    try:
        with open(path, 'rb') as f:
            return f.read(3) == b'\xef\xbb\xbf'
    except OSError:
        return True


def _write(level, msg, sync=False):
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        try:
            old = LOG_FILE not in _bom_checked and os.path.exists(LOG_FILE) and not _has_bom(LOG_FILE)
            _bom_checked.append(LOG_FILE)
            if old or os.path.getsize(LOG_FILE) > MAX_BYTES:   # Altdatei ohne BOM (v1.0.0) ebenfalls weiterrollen
                for i in range(BACKUPS, 0, -1):
                    src = LOG_FILE + ('.%d' % (i - 1) if i > 1 else '')
                    dst = LOG_FILE + '.%d' % i
                    if os.path.exists(src):
                        if os.path.exists(dst):
                            os.remove(dst)
                        os.replace(src, dst)
        except OSError:
            pass
        line = '%s %-5s %s\n' % (datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S,%f')[:-3], level, msg)
        new = not os.path.exists(LOG_FILE) or os.path.getsize(LOG_FILE) == 0
        # UTF-8 MIT BOM: Windows-Editoren erkennen die Kodierung sicher (ohne BOM -> cp1252 -> „Ã¤“).
        with open(LOG_FILE, 'a', encoding='utf-8-sig' if new else 'utf-8', newline='\r\n' if os.name == 'nt' else None) as f:
            f.write(line)
            f.flush()
            if sync:
                try:
                    os.fsync(f.fileno())
                except OSError:
                    pass
    except Exception:
        pass


SAFE_MODE = True     # Sicherheitsmodus (ab 1.0.2): Kontrollpunkt vor jedem riskanten CAM-/Geometrie-Aufruf


_LAST_CP = [None]


def checkpoint(msg, *a):
    """Kontrollpunkt VOR einem riskanten API-Aufruf, sofort auf die Platte (flush + fsync).
    Stürzt Fusion im Aufruf ab, nennt die letzte Protokollzeile („CP …“) genau diesen Aufruf.
    2.0.2: am Ende „[+N ms]“ = Abstand zum vorigen Kontrollpunkt (Profil direkt aus dem Protokoll) – Profil direkt aus dem Protokoll."""
    if SAFE_MODE:
        import time as _time
        now = _time.perf_counter()
        d = '' if _LAST_CP[0] is None else ' [+%d ms]' % int((now - _LAST_CP[0]) * 1000)
        _LAST_CP[0] = now
        _write('CP', _fmt(msg, a) + d, sync=True)


def _fmt(msg, a):
    try:
        return msg % a if a else msg
    except Exception:
        return '%s %r' % (msg, a)


def info(msg, *a):
    _write('INFO', _fmt(msg, a))


def warn(msg, *a):
    _write('WARN', _fmt(msg, a))


def error(msg, *a):
    _write('FEHLER', _fmt(msg, a))


def exc(where):
    """Aktuelle Ausnahme mit vollständigem Traceback protokollieren; liefert den Traceback-Text."""
    tb = traceback.format_exc()
    _write('FEHLER', '%s\n%s' % (where, tb))
    return tb


def stamp():
    return datetime.datetime.now().strftime('%Y%m%d_%H%M%S_%f')[:-3]


def path(name):
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
    except Exception:
        pass
    return os.path.join(LOG_DIR, name)


def _prune(prefix):
    try:
        fs = sorted(f for f in os.listdir(LOG_DIR) if f.startswith(prefix))
        for f in fs[:-KEEP_JSON]:
            os.remove(os.path.join(LOG_DIR, f))
    except Exception:
        pass


def dump_json(kind, data):
    """logs/<kind>_<zeit>.json schreiben; liefert den Pfad ('' bei Fehler)."""
    try:
        p = path('%s_%s.json' % (kind, stamp()))
        if isinstance(data, dict):
            data = dict(data, finalschnitt_version=VERSION)
        with open(p, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=True, indent=1, default=str)   # ASCII mit Escapes: in jedem Editor lesbar
        _prune(kind + '_')
        return p
    except Exception:
        exc('dump_json %s' % kind)
        return ''
