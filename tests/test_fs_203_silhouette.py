# -*- coding: utf-8 -*-
"""LazySetup 2.0.3: offene Silhouetten-Ketten (bettdeckel groß, Griffausschnitt mit zwei Bögen R100: Lücken
75,236 mm = Sehne der Bögen) werden entlang der Flächenschleifen geschlossen; Schnellweg-Toleranz 0,12 mm."""
import math
import unittest

import fs_silhouette as S  # noqa: E402


def lid():
    """Deckel 970 × 515 mm mit Griffausschnitt oben: Bogen R100 – Gerade 54,2 mm – Bogen R100 (wie bettdeckel
    groß), Abtastung 0,05 mm Sehnenfehler. CCW."""
    W, H = 970.0, 515.0
    cl, cr = (400.0, H + 70.0), (454.2, H + 70.0)
    pts = [(0.0, 0.0), (W, 0.0), (W, H)]
    def arc(c, a0, a1, n=14):
        return [(c[0] + 100 * math.cos(a0 + (a1 - a0) * i / n), c[1] + 100 * math.sin(a0 + (a1 - a0) * i / n))
                for i in range(n + 1)]
    # Schnittwinkel mit y = H: sin(a) = (H - c_y)/100 = -0.7
    a = math.asin(-0.7)
    right = arc(cr, a, -math.pi / 2)                 # von (c2 + 71.4, H) nach (c2.x, H - 30)
    left = arc(cl, -math.pi / 2, -math.pi - a)        # von (c1.x, H - 30) nach (c1 - 71.4, H)
    pts += right + left
    pts += [(0.0, H)]
    out = []
    for p in pts:
        q = S._q(p)
        if not out or out[-1] != q:
            out.append(q)
    return out, (cl, cr)


class Bridge(unittest.TestCase):
    def test_arcs_missing_are_bridged(self):
        P, cs = lid()
        self.assertGreater(S.signed_area(P), 0)
        n = len(P)
        kept = []
        for i in range(n):
            a, b = P[i], P[(i + 1) % n]
            if any(abs(math.dist(a, c) - 100) < 0.01 and abs(math.dist(b, c) - 100) < 0.01 for c in cs):
                continue                                  # beide Bögen fehlen (wie im Protokoll 12.10. 15:43)
            kept.append((a, b, (0, 0, i)))
        info = {'open': [], 'closed_tol': 0, 'dropped_small': 0}
        loops = S._stitch(kept, info)
        self.assertTrue(info['open'])
        loops = S._bridge(kept, [[(P, list(range(n)), 0)]], [0], loops, info)
        self.assertEqual(info['open'], [])
        self.assertGreaterEqual(info['bridged'], 2)
        self.assertEqual(len(loops), 1)
        self.assertAlmostEqual(S.signed_area(loops[0][0]), S.signed_area(P), delta=1.0)

    def test_long_way_not_bridged(self):
        """Eine Lücke, die nur über (fast) den ganzen Umfang schließbar wäre, bleibt offen (nie raten)."""
        P, _cs = lid()
        n = len(P)
        kept = [(P[i], P[(i + 1) % n], (0, 0, i)) for i in range(n) if i not in (0, 1)]
        regs = [[(P, list(range(n)), 0)]]
        info = {'open': [], 'closed_tol': 0, 'dropped_small': 0}
        loops = S._stitch(kept, info)
        k = len(info['open'])
        # nur die Unterkante fehlt (970 mm + 970 mm Lücke): zu lang -> bleibt offen
        S._bridge(kept, regs, [0], loops, info)
        self.assertEqual(len(info['open']), k)

    def test_silhouette_two_faces_differently_sampled(self):
        P, cs = lid()
        # Oberseite: Bögen anders abgetastet (zusätzliche Punkte auf dem Kreis)
        Q = []
        n = len(P)
        for i in range(n):
            a, b = P[i], P[(i + 1) % n]
            Q.append(a)
            for c in cs:
                if abs(math.dist(a, c) - 100) < 0.01 and abs(math.dist(b, c) - 100) < 0.01:
                    a0 = math.atan2(a[1] - c[1], a[0] - c[0])
                    a1 = math.atan2(b[1] - c[1], b[0] - c[0])
                    am = a0 + (a1 - a0) * 0.37
                    Q.append((c[0] + 100 * math.cos(am), c[1] + 100 * math.sin(am)))
        regs = [[(P, [0] * len(P))], [(Q[::-1], [0] * len(Q))]]
        self.assertEqual(S.fast_path(regs, [0, 1])['region'], 0)
        info = {}
        sh = S.silhouette(regs, info)
        self.assertEqual(len(sh), 1)
        self.assertEqual(info['open'], [])

    def test_fast_tol_default(self):
        self.assertAlmostEqual(S.FAST_TOL, 0.12)
        sq = [(0.0, 0.0), (100.0, 0.0), (100.0, 100.0), (0.0, 100.0)]
        out = [(0.0, -0.1), (100.0, -0.1), (100.0, 100.0), (0.0, 100.0)]   # 0,1 mm über der Unterseite
        regs = [[(sq, [0] * 4)], [(out[::-1], [0] * 4)]]
        self.assertEqual(S.fast_path(regs, [0])['region'], 0)
        self.assertIsNone(S.fast_path(regs, [0], tol=0.05)['region'])


if __name__ == '__main__':
    unittest.main()
