# -*- coding: utf-8 -*-
"""Vorschau /workspace/finalschnitt_preview.png: zwei echte Rohteile (cn_logs3 mit Durchbrüchen, cn_logs4)
mit Schnittfolge, Startpunkten (Pfeil zur Mitte), Stegen (grün) und Brückenstegen (violett).
Die Einzelbilder erzeugt fs_geom.render_preview (dieselbe Funktion wie im Add-in, ohne Zusatzbibliotheken);
nur das Zusammensetzen mit Beschriftung nutzt PIL."""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.dirname(HERE), HERE]

import fs_geom as G       # noqa: E402
import fs_testdata as TD  # noqa: E402
from PIL import Image, ImageDraw, ImageFont  # noqa: E402

OUT = sys.argv[1] if len(sys.argv) > 1 else '/workspace/finalschnitt_preview.png'
SOURCES = [os.path.join(TD.ROOT, 'cn_logs3', 'apply_20261009_102512_483.json'),
           os.path.join(TD.ROOT, 'cn_logs4', 'apply_20261009_103838_358.json')]


def font(sz):
    for f in ('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', '/usr/share/fonts/dejavu/DejaVuSans.ttf'):
        if os.path.isfile(f):
            return ImageFont.truetype(f, sz)
    return ImageFont.load_default()


def main():
    tiles = []
    for src in SOURCES:
        sh = TD.sheets_from(src)[0]
        pl = G.plan_sheet(sh)
        tmp = '/tmp/fs_prev_%d.png' % len(tiles)
        G.render_preview(pl, tmp, 1000)
        sm = G.plan_summary(pl)
        lines = ['%s – %s' % (os.path.basename(os.path.dirname(src)), sh['name'])]
        for o in sm['order']:
            lines.append('%d. %s  %.0f cm²  %d Stege%s%s' % (
                o['nr'], o['name'], o['area_cm2'], len(o['tabs']),
                ' (%d Brücke)' % sum(t['bridge'] for t in o['tabs']) if any(t['bridge'] for t in o['tabs']) else '',
                ', %d Durchbr%s' % (o['holes'], 'uch' if o['holes'] == 1 else 'üche') if o['holes'] else ''))
        tiles.append((Image.open(tmp), lines))
    W = 1000 + 560
    H = sum(t.height + 20 for t, _l in tiles) + 90
    im = Image.new('RGB', (W, H), 'white')
    d = ImageDraw.Draw(im)
    d.text((14, 10), 'Finalschnitt v1.1.0 – Vorschau (Werkzeug Ø 8 mm, Standardwerte)', fill='black', font=font(22))
    y = 50
    for t, lines in tiles:
        im.paste(t, (0, y))
        for k, ln in enumerate(lines):
            d.text((1010, y + 8 + k * 22), ln, fill='black', font=font(16 if k else 18))
        y += t.height + 20
    lg = [((200, 0, 0), 'Startpunkt (Pfeil zur Plattenmitte)'), ((0, 140, 0), 'Haltesteg'),
          ((140, 0, 170), 'Brückensteg (Nachbarteil)'), ((200, 120, 0), 'Durchbruch (wird zuerst geschnitten)')]
    x = 14
    for c, t in lg:
        d.ellipse([x, y + 6, x + 14, y + 20], fill=c)
        d.text((x + 20, y + 3), t, fill='black', font=font(16))
        x += 330
    im.save(OUT)
    print(OUT, im.size)


if __name__ == '__main__':
    main()
