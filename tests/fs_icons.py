# -*- coding: utf-8 -*-
"""Erzeugt resources/Finalschnitt/*.png (Platte mit Teilen, Schnittweg mit Startpfeil und Stegen)."""
import os

from PIL import Image, ImageDraw

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'resources', 'Finalschnitt')


def icon(n):
    s = 8
    im = Image.new('RGBA', (n * s, n * s), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    W = n * s
    m = W * 0.06
    d.rounded_rectangle([m, m + W * 0.08, W - m, W - m - W * 0.08], radius=W * 0.05, fill=(222, 196, 150, 255),
                        outline=(120, 90, 50, 255), width=max(1, int(W * 0.03)))
    # Teil (blau) mit Schnittweg (rot gestrichelt) und Stegen (grün)
    x0, y0, x1, y1 = W * 0.24, W * 0.30, W * 0.76, W * 0.70
    d.rectangle([x0, y0, x1, y1], fill=(110, 160, 230, 255), outline=(30, 60, 120, 255), width=max(1, int(W * 0.03)))
    g = W * 0.07
    path = [(x0 - g, y0 - g), (x1 + g, y0 - g), (x1 + g, y1 + g), (x0 - g, y1 + g), (x0 - g, y0 - g)]
    d.line(path, fill=(210, 30, 30, 255), width=max(2, int(W * 0.05)), joint='curve')
    for cx, cy in (((x0 + x1) / 2, y0 - g), ((x0 + x1) / 2, y1 + g)):
        d.rectangle([cx - W * 0.05, cy - W * 0.05, cx + W * 0.05, cy + W * 0.05], fill=(30, 150, 40, 255))
    r = W * 0.07
    d.ellipse([x1 + g - r, y0 - g - r, x1 + g + r, y0 - g + r], fill=(210, 30, 30, 255))
    return im.resize((n, n), Image.LANCZOS)


def main():
    os.makedirs(OUT, exist_ok=True)
    for n in (16, 32, 64):
        icon(n).save(os.path.join(OUT, '%dx%d.png' % (n, n)))
        icon(n * 2).save(os.path.join(OUT, '%dx%d@2x.png' % (n, n)))
    print('Icons ->', OUT)


if __name__ == '__main__':
    main()
