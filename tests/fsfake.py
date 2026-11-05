# -*- coding: utf-8 -*-
"""Fakes für Fusion-Design (Rohteile/Teile als Prismen aus echten Konturen) und Fusion-CAM.

Die CAM-Fakes bilden NUR das Verhalten nach, das Finalschnitt annimmt (Parameter-Namen aus Beispielen/Forum,
Auswahlwerte über getChoices). Sie prüfen die Logik (Reihenfolge, Werte, Rückfälle), nicht die echte API."""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
for p in (os.path.join(HERE, 'fsstubs'), os.path.dirname(HERE), HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import adsk.core as core  # noqa: E402


# ---------------------------------------------------------------- allgemein
class Attr:
    def __init__(self, g, n, v):
        self.groupName, self.name, self.value = g, n, v


class Attributes:
    """Wie Fusion: count/item, itemByName, add (überschreibt)."""
    def __init__(self):
        self.d = {}

    def add(self, g, n, v):
        self.d[(g, n)] = Attr(g, n, v)
        return self.d[(g, n)]

    def itemByName(self, g, n):
        return self.d.get((g, n))

    @property
    def count(self):
        return len(self.d)

    def item(self, i):
        return list(self.d.values())[i]


class Coll(list):
    @property
    def count(self):
        return len(self)

    def item(self, i):
        return self[i]


class Transform:
    def __init__(self, ox=0.0, oy=0.0, oz=0.0):
        self.o = (ox, oy, oz)

    def getAsCoordinateSystem(self):
        P = core.Point3D.create
        V = core.Vector3D.create
        return (P(*self.o), V(1, 0, 0), V(0, 1, 0), V(0, 0, 1))


# ---------------------------------------------------------------- B-Rep
class Evaluator:
    def __init__(self, a, b):
        self.a, self.b = a, b

    def getParameterExtents(self):
        return True, 0.0, 1.0

    def getStrokes(self, p0, p1, tol):
        return True, [core.Point3D.create(*self.a), core.Point3D.create(*self.b)]


class Edge:
    seq = 0
    generation = 0          # 1.3.1: Neuberechnung macht alle älteren Kanten-Objekte ungültig (wie Fusion)

    def __init__(self, a, b):
        Edge.seq += 1
        self.id = Edge.seq
        self.gen = Edge.generation
        self.evaluator = Evaluator(a, b)

    @property
    def isValid(self):
        return self.gen == Edge.generation


INVALIDATE = set()          # 'compute' (design.computeAll) / 'sketch' (sketches.add) erneuern die B-Rep


def invalidate_all():
    """Fusion baut Körper neu auf: alle bisherigen BRepEdge-Objekte ungültig, Schleifen liefern neue."""
    Edge.generation += 1
    for lp in Loop.all:
        for ce in lp.coEdges:
            ce.edge = Edge(ce.edge.evaluator.a, ce.edge.evaluator.b)


class CoEdge:
    def __init__(self, edge, opp):
        self.edge, self.isOpposedToEdge = edge, opp


class Loop:
    all = []

    def __init__(self, coedges, outer):
        self.coEdges = Coll(coedges)
        self.isOuter = outer
        Loop.all.append(self)


class Plane:
    def __init__(self, n):
        self.normal = core.Vector3D.create(*n)


class NoNormal:
    """Fläche, deren Geometrie keine Normale liefert (simuliert unlesbare B-Rep)."""
    surfaceType = 0


class FaceEval:
    def __init__(self, n):
        self.n = n

    def getNormalAtPoint(self, p):
        return True, core.Vector3D.create(*self.n)


class Face:
    def __init__(self, n, pt, loops, area):
        self.geometry = Plane(n)
        self.evaluator = FaceEval(n)
        self.pointOnFace = core.Point3D.create(*pt)
        self.loops = Coll(loops)
        self.area = area
        self.isParamReversed = False


class CylFace:
    """Seitenfläche ohne Normale (wird ignoriert)."""
    class _G:
        surfaceType = 1
    geometry = _G()
    loops = Coll()
    area = 1.0


def _loop(pts_mm, z_mm, off, ccw_from_top, outer, flip_every=2):
    """Schleife aus Polygonpunkten; Coedge-Richtung CCW/CW von oben; jede zweite Kante gegenläufig gespeichert."""
    from fs_geom import orient
    P = orient(pts_mm, ccw_from_top)
    w = [(off[0] + x / 10.0, off[1] + y / 10.0, off[2] + z_mm / 10.0) for x, y in P]
    ces = []
    for k in range(len(w)):
        a, b = w[k], w[(k + 1) % len(w)]
        if flip_every and k % flip_every == 0:
            ces.append(CoEdge(Edge(b, a), True))
        else:
            ces.append(CoEdge(Edge(a, b), False))
    return Loop(ces, outer)


def prism_body(outer, holes, thick, off, name='Körper', pockets=(), broken=False):
    from fs_geom import area
    bottom = Face((0, 0, -1), (off[0] + outer[0][0] / 10, off[1] + outer[0][1] / 10, off[2]),
                  [_loop(outer, 0.0, off, False, True)] + [_loop(h, 0.0, off, True, False) for h in holes],
                  area(outer) / 100.0)
    top = Face((0, 0, 1), (off[0] + outer[0][0] / 10, off[1] + outer[0][1] / 10, off[2] + thick / 10),
               [_loop(outer, thick, off, True, True)] + [_loop(h, thick, off, False, False) for h in holes],
               area(outer) / 100.0)
    faces = [bottom, top, CylFace()]
    if broken:
        for f in (bottom, top):
            f.geometry = NoNormal()
            f.evaluator = None
    for q, depth in pockets:
        z = thick - depth
        faces.append(Face((0, 0, 1), (off[0] + q[0][0] / 10, off[1] + q[0][1] / 10, off[2] + z / 10),
                          [_loop(q, z, off, True, True)], area(q) / 100.0))
    b = type('Body', (), {})()
    b.faces = Coll(faces)
    b.isSolid = True
    b.name = name
    b.bottom = bottom
    return b


# ---------------------------------------------------------------- Skizzen / Komponenten / Occurrences
class SketchPoint:
    def __init__(self, sk, p):
        self.sketch, self.geometry = sk, p

    def createForAssemblyContext(self, occ):
        px = SketchPoint(self.sketch, self.geometry)
        px.context = occ
        px.native = self
        return px


class SketchPoints(Coll):
    def __init__(self, sk):
        super().__init__([SketchPoint(sk, core.Point3D.create(0, 0, 0))])   # Ursprung
        self.sk = sk

    def add(self, p):
        sp = SketchPoint(self.sk, p)
        self.append(sp)
        return sp


class SketchCurve:
    """2.0.1: Skizzenlinie/-bogen (Start/Ende als Skizzenpunkte; Bögen wie Fusion immer CCW gespeichert)."""
    def __init__(self, sk, kind, pts):
        self.sk, self.kind, self.pts = sk, kind, pts
        self.isValid = True
        a, b = pts[0], pts[-1]
        if kind == 'arc' and len(pts) == 3:
            (x0, y0), (x1, y1), (x2, y2) = [(p.x, p.y) for p in pts]
            if (x1 - x0) * (y2 - y0) - (y1 - y0) * (x2 - x0) < 0:      # im Uhrzeigersinn -> umdrehen
                a, b = b, a
        self.startSketchPoint = type('SP', (), {'geometry': a})()
        self.endSketchPoint = type('SP', (), {'geometry': b})()

    def createForAssemblyContext(self, occ):
        px = SketchCurve(self.sk, self.kind, self.pts)
        px.startSketchPoint, px.endSketchPoint = self.startSketchPoint, self.endSketchPoint
        px.assemblyContext, px.nativeObject = occ, self
        return px


class _Lines(Coll):
    def __init__(self, sk):
        super().__init__()
        self.sk = sk

    def addByTwoPoints(self, a, b):
        a = a.geometry if hasattr(a, 'geometry') else a      # 2.0.3: Skizzenpunkt als Anfang (wie Fusion)
        b = b.geometry if hasattr(b, 'geometry') else b
        c = SketchCurve(self.sk, 'line', [a, b])
        self.append(c)
        return c


class _Arcs(Coll):
    def __init__(self, sk):
        super().__init__()
        self.sk = sk

    def addByThreePoints(self, a, m, b):
        c = SketchCurve(self.sk, 'arc', [a, m, b])
        self.append(c)
        return c

    BUG = {'radius_factor': 1.0}       # Test: falsch angelegter Bogen (Prüfung muss ihn verwerfen)

    def addByCenterStartSweep(self, c, s, sweep):
        """2.0.2: wie Fusion – Bogen um c ab s über sweep (rad, + = CCW), gespeichert immer CCW."""
        import math as _m
        r = _m.hypot(s.x - c.x, s.y - c.y) * self.BUG['radius_factor']
        a0 = _m.atan2(s.y - c.y, s.x - c.x)
        a1 = a0 + sweep
        if sweep < 0:
            a0, a1 = a1, a0
        P = lambda t: core.Point3D.create(c.x + r * _m.cos(t), c.y + r * _m.sin(t), s.z)
        arc = SketchCurve(self.sk, 'arc', [P(a0), P((a0 + a1) / 2), P(a1)])
        arc.startSketchPoint = type('SP', (), {'geometry': P(a0)})()
        arc.endSketchPoint = type('SP', (), {'geometry': P(a1)})()
        arc.length = r * abs(sweep)
        arc.center, arc.radius, arc.sweep = c, r, sweep
        ev = type('EV', (), {})()
        ev.getParameterExtents = lambda: (True, a0, a1)
        ev.getPointAtParameter = lambda t: (True, P(t))
        arc.geometry = type('G', (), {'evaluator': ev})()
        self.append(arc)
        arc.deleteMe = lambda: (self.remove(arc) if arc in self else None) or True
        return arc


class SketchCurves:
    def __init__(self, sk):
        self.sketchLines, self.sketchArcs = _Lines(sk), _Arcs(sk)

    @property
    def count(self):
        return len(self.sketchLines) + len(self.sketchArcs)


class Sketch:
    def __init__(self, comp, plane):
        self.comp, self.plane = comp, plane
        self.name = 'Skizze'
        self.isVisible = True
        self.isComputeDeferred = False
        self.sketchPoints = SketchPoints(self)
        self.sketchCurves = SketchCurves(self)

    def modelToSketchSpace(self, p):
        return core.Point3D.create(p.x, p.y, p.z)

    def sketchToModelSpace(self, p):
        return core.Point3D.create(p.x, p.y, p.z)

    def deleteMe(self):
        EVENTS.append(('sketch_delete', getattr(self, 'name', '')))
        self.comp.sketches.remove(self)
        return True


class Sketches(Coll):
    def __init__(self, comp):
        super().__init__()
        self.comp = comp

    def add(self, plane):
        s = Sketch(self.comp, plane)
        self.append(s)
        if 'sketch' in INVALIDATE:
            invalidate_all()
        return s


class Component:
    def __init__(self, name):
        self.name = name
        self.sketches = Sketches(self)
        self.xYConstructionPlane = 'XY'


class Occ:
    def __init__(self, name, parent=None, off=(0, 0, 0)):
        self.name = name
        self.fullPathName = (parent.fullPathName + '+' + name) if parent is not None and parent.fullPathName else name
        self.childOccurrences = Coll()
        self.bRepBodies = Coll()
        self.attributes = Attributes()
        self.transform2 = Transform(*off)
        self.component = Component(name.split(':')[0])
        self.nativeObject = None
        self.boundingBox = None


class BBox:
    def __init__(self, a, b):
        self.minPoint, self.maxPoint = core.Point3D.create(*a), core.Point3D.create(*b)


class Root:
    def __init__(self):
        self.occurrences = Coll()


EVENTS = []          # Reihenfolge riskanter Aufrufe (Tests 1.0.2): ('op_delete'|'sketch_delete'|'compute', name)


class Design:
    is_design = True

    def __init__(self):
        self.rootComponent = Root()
        self.attributes = Attributes()
        self.fail_compute = False
        self.computed = 0

    def computeAll(self):
        self.computed += 1
        EVENTS.append(('compute', ''))
        if self.fail_compute:
            raise RuntimeError('Fake: computeAll fehlgeschlagen')
        if 'compute' in INVALIDATE:
            invalidate_all()
        return True


def build_design(sheets, offset_cm=(300.0, 50.0, 0.0), pockets=None, attrs_on='proxy', nested=False,
                 platte=False, project=False, broken=(), with_bbox=True):
    """Design mit Rohteilen aus fs_testdata-Sheets (Teile = Prismen, Lage = Rohteil-Ursprung + Kontur).
    attrs_on: 'proxy' (Attribute am Proxy lesbar), 'native' (nur an occ.nativeObject bzw. an der Occurrence in
    rohteil.component.occurrences – wie ContourNest sie schreibt), 'none' (keine Teil-Attribute).
    nested: Körper liegen in einer Unter-Occurrence des Teils. platte: alte Platten-Komponente als Kind.
    project: ContourNest-Projekt als Design-Attribut. broken: Teilnamen mit unlesbarer B-Rep."""
    import json
    from fs_geom import bbox
    d = Design()
    if project:
        jparts, placements, seen = {}, [], {}
        for n, sh in enumerate(sheets):
            for p in sh['parts']:
                jparts[p['id']] = {'id': p['id'], 'name': p['name'], 'outer': p['local_outer'],
                                   'holes': p['local_holes']}
                cp = seen.get(p['id'], 0)
                seen[p['id']] = cp + 1
                p['_copy'] = cp
                placements.append(dict(p['placement'], sheet=n + 1, id=p['id'], name=p['name'], copy=cp,
                                       key='%s#%d' % (p['id'], cp)))
        proj = {'project_id': 'P1', 'job': {'parts': list(jparts.values())}, 'placements': placements}
        d.attributes.add('ContourNest', 'project_P1', json.dumps(proj))
        d.attributes.add('ContourNest', 'projects', json.dumps(['P1']))
    for n, sh in enumerate(sheets):
        off = (offset_cm[0] + n * 400.0, offset_cm[1], offset_cm[2])
        so = Occ('Rohteil %02d:1' % (n + 1), None, off)
        so.attributes.add('ContourNest', 'sheet', json.dumps({
            'index': n + 1, 'length_mm': sh['length'], 'width_mm': sh['width'], 'thickness_mm': sh['thickness'],
            'project_id': 'P1', 'project_sheet': n + 1, 'material': 'Spanplatte'}))
        stock = prism_body([(0, 0), (sh['length'], 0), (sh['length'], sh['width']), (0, sh['width'])], [],
                           sh['thickness'], off, 'Rohteil')
        so.bRepBodies.append(stock)
        if platte:
            pl = Occ('Platte:1', so, off)
            pl.bRepBodies.append(prism_body([(0, 0), (sh['length'], 0), (sh['length'], sh['width']),
                                             (0, sh['width'])], [], sh['thickness'], off, 'Rohteil'))
            so.childOccurrences.append(pl)
        for k, p in enumerate(sh['parts']):
            po = Occ('%s:%d' % (p['name'], k + 1), so, off)
            nat = Occ('%s:%d' % (p['name'], k + 1), None, (0, 0, 0))
            target = {'proxy': po, 'native': nat, 'none': None}[attrs_on]
            if attrs_on == 'native':
                po.nativeObject = nat
                so.component.occurrences = getattr(so.component, 'occurrences', Coll())
                so.component.occurrences.append(nat)
            if target is not None:
                target.attributes.add('ContourNest', 'part_id', p.get('id', p['name']))
                target.attributes.add('ContourNest', 'part_name', p['name'])
                target.attributes.add('ContourNest', 'copy', str(p.get('_copy', 0) + 1) if project else str(k))
                if p.get('small'):
                    target.attributes.add('ContourNest', 'small_part', 'true')
            pk = (pockets or {}).get(p['name'], ())
            body = prism_body(p['outer'], p.get('holes') or [], sh['thickness'], off, pockets=pk,
                              broken=p['name'] in broken)
            if nested:
                sub = Occ('Körper:1', po, off)
                sub.bRepBodies.append(body)
                po.childOccurrences.append(sub)
            else:
                po.bRepBodies.append(body)
            if with_bbox:
                b = bbox(p['outer'])
                po.boundingBox = BBox((off[0] + b[0] / 10, off[1] + b[1] / 10, off[2]),
                                      (off[0] + b[2] / 10, off[1] + b[3] / 10, off[2] + sh['thickness'] / 10))
            so.childOccurrences.append(po)
        d.rootComponent.occurrences.append(so)
    return d


# ---------------------------------------------------------------- CAM
class ChoiceValue:
    def __init__(self, choices, v):
        self.choices, self.value = list(choices), v

    def getChoices(self):
        return True, ['Titel ' + c for c in self.choices], list(self.choices)


class PlainValue:
    def __init__(self, v):
        self.value = v


class ChainSelection:
    def __init__(self):
        self._geo = []
        self.isReverted = False
        self.isOpen = True

    @property
    def inputGeometry(self):
        return self._geo

    @inputGeometry.setter
    def inputGeometry(self, v):
        if any(getattr(e, 'isValid', True) is False for e in v):     # wie Fusion 2704
            raise RuntimeError('2 : InternalValidationError : edge')
        self._geo = list(v)


class PocketSelection:
    def __init__(self):
        self.inputGeometry = []


class CurveSelections(list):
    @property
    def count(self):
        return len(self)

    def item(self, i):
        return self[i]

    def createNewChainSelection(self):
        c = ChainSelection()
        self.append(c)
        return c

    def createNewPocketSelection(self):
        c = PocketSelection()
        self.append(c)
        return c

    def clear(self):
        del self[:]


class ContoursValue:
    def __init__(self):
        self.applied = CurveSelections()

    def getCurveSelections(self):
        return CurveSelections(self.applied)

    def applyCurveSelections(self, sel):
        self.applied = CurveSelections(sel)


class Param:
    def __init__(self, name, kind, default=None, choices=None, fail=False):
        self.name, self.kind, self.title = name, kind, 'Titel ' + name
        self.fail = fail
        if kind == 'choice':
            self.value = ChoiceValue(choices, default if default is not None else choices[0])
        elif kind == 'contours':
            self.value = ContoursValue()
        else:
            self.value = PlainValue(default)
        self._expr = repr(default)

    @property
    def expression(self):
        if self.kind == 'choice':
            return "'%s'" % self.value.value
        if self.kind == 'bool':
            return 'true' if self.value.value else 'false'
        return self._expr

    @expression.setter
    def expression(self, e):
        if self.fail:
            raise RuntimeError('Fake: Parameter %s gesperrt' % self.name)
        if self.kind == 'choice':
            v = e.strip("'")
            if v not in self.value.choices:
                raise RuntimeError('ungültiger Wert %s' % v)
            self.value.value = v
        elif self.kind == 'bool':
            if e not in ('true', 'false'):
                raise RuntimeError('kein bool')
            self.value.value = e == 'true'
        elif self.kind in ('length', 'number'):
            s = e.replace('mm', '').strip()
            self.value.value = float(s) / (10.0 if 'mm' in e else 1.0)
            self._expr = e
        else:
            raise RuntimeError('nicht per Ausdruck setzbar')


BOTTOM_CHOICES = ['from stock top', 'from stock bottom', 'from model top', 'from model bottom', 'from contour',
                  'from selection']
CONTOUR2D = [
    ('contours', 'contours', None, None), ('tolerance', 'length', 0.001, None),
    ('compensation', 'choice', 'left', ['left', 'right']),
    ('bottomHeight_mode', 'choice', 'from contour', BOTTOM_CHOICES), ('bottomHeight_offset', 'length', 0.0, None),
    ('topHeight_mode', 'choice', 'from stock top', BOTTOM_CHOICES), ('topHeight_offset', 'length', 0.0, None),
    ('doMultipleDepths', 'bool', False, None), ('maximumStepdown', 'length', 0.1, None),
    ('useStockToLeave', 'bool', False, None), ('stockToLeave', 'length', 0.0, None),
    ('verticalStockToLeave', 'length', 0.0, None), ('doLeadIn', 'bool', True, None), ('doRamp', 'bool', False, None),
    ('group_tabs', 'bool', False, None), ('tabShape', 'choice', 'rectangular', ['rectangular', 'triangular']),
    ('tabWidth', 'length', 0.5, None), ('tabHeight', 'length', 0.2, None),
    ('tabPositioning', 'choice', 'distance', ['distance', 'tabCount', 'perContour']),
    ('tabPositions', 'objects', [], None), ('tabsPerContour', 'number', 3, None), ('tabDistance', 'length', 10.0, None),
    ('entryPositions', 'objects', [], None), ('preserveOrder', 'bool', False, None),
]
POCKET2D = [('pockets', 'contours', None, None), ('compensation', 'choice', 'left', ['left', 'right']),
            ('doMultipleDepths', 'bool', False, None), ('maximumStepdown', 'length', 0.1, None)]
SETUP_PARAMS = [('wcs_orientation_mode', 'choice', 'axesZX', ['axesZX', 'modelOrientation', 'selectedAxes']),
                ('wcs_origin_mode', 'choice', 'modelPoint', ['modelPoint', 'stockPoint', 'selectedPoint']),
                ('wcs_origin_boxPoint', 'choice', 'top center', ['top center', 'bottom 1', 'bottom center']),
                ('job_stockFixedX', 'length', 0.0, None), ('job_stockFixedY', 'length', 0.0, None),
                ('job_stockFixedZ', 'length', 0.0, None)]


class Params(Coll):
    def __init__(self, spec, missing=(), failing=()):
        super().__init__(Param(n, k, d, c, n in failing) for n, k, d, c in spec if n not in missing)

    def itemByName(self, n):
        return next((p for p in self if p.name == n), None)


class OpInput:
    def __init__(self, strategy):
        self.strategy = strategy
        self.tool = None
        self.displayName = ''
        self.toolPreset = None


class Operation:
    def __init__(self, setup, inp, cam):
        self.setup, self.strategy, self.tool = setup, inp.strategy, inp.tool
        self.name = inp.displayName or inp.strategy
        spec = {'contour2d': CONTOUR2D, 'pocket2d': POCKET2D}.get(inp.strategy, [])
        self.parameters = Params(spec, cam.missing, cam.failing)
        self.attributes = Attributes()
        self.parentSetup = setup

    def deleteMe(self):
        EVENTS.append(('op_delete', getattr(self, 'name', '')))
        self.setup.operations.remove(self)
        return True


class Operations(Coll):
    def __init__(self, setup, cam):
        super().__init__()
        self.setup, self.cam = setup, cam

    def createInput(self, strategy):
        if strategy not in ('contour2d', 'pocket2d'):
            raise RuntimeError('unbekannte Strategie')
        return OpInput(strategy)

    def add(self, inp):
        if self.cam.fail_add and inp.displayName and self.cam.fail_add in inp.displayName:
            raise RuntimeError('Fake: add fehlgeschlagen')
        op = Operation(self.setup, inp, self.cam)
        self.append(op)
        return op


class Setup:
    def __init__(self, cam, name='Setup'):
        self.cam = cam
        self.name = name
        self.attributes = Attributes()
        self.operations = Operations(self, cam)
        self.parameters = Params(SETUP_PARAMS)
        self.models = []
        self.stockMode = None
        self.stockSolids = None
        self.isValid = True

    @property
    def allOperations(self):
        return Coll(self.operations)


class SetupInput:
    def __init__(self, t):
        self.type = t
        self.models = []
        self.name = ''


class Setups(Coll):
    def __init__(self, cam):
        super().__init__()
        self.cam = cam

    def createInput(self, t):
        return SetupInput(t)

    def add(self, inp):
        s = Setup(self.cam, inp.name or 'Setup%d' % (len(self) + 1))
        s.models = list(inp.models)
        self.append(s)
        return s


class Tool:
    def __init__(self, number, d_mm, desc, ttype='flat end mill'):
        self.parameters = Params([
            ('tool_type', 'str', ttype, None), ('tool_diameter', 'length', d_mm / 10.0, None),
            ('tool_number', 'number', number, None), ('tool_description', 'str', desc, None),
            ('tool_numberOfFlutes', 'number', 2, None), ('tool_feedCutting', 'number', 500.0, None),
            ('tool_spindleSpeed', 'number', 18000, None)])
        self.presets = Coll()


class ToolLibraries:
    def __init__(self, libs):
        self.libs = libs       # {url: [tools]} unter 'local/...'

    def urlByLocation(self, loc):
        return core.URL.create('loc%d' % loc)

    def childAssetURLs(self, url):
        if url.toString() == 'loc0':
            return [core.URL.create(u) for u in self.libs if u.startswith('local/') and u.count('/') == 1]
        if url.toString() == 'local/Ordner':
            return [core.URL.create(u) for u in self.libs if u.startswith('local/Ordner/')]
        return []

    def childFolderURLs(self, url):
        return [core.URL.create('local/Ordner')] if url.toString() == 'loc0' else []

    def toolLibraryAtURL(self, url):
        return Coll(self.libs.get(url.toString(), []))


class LibraryManager:
    def __init__(self, libs):
        self.toolLibraries = ToolLibraries(libs)


class CAM:
    def __init__(self, design=None):
        self.setups = Setups(self)
        self.documentToolLibrary = Coll()
        self.generated = []
        self.missing = set()
        self.failing = set()
        self.fail_add = None
        root = Occ('root')
        root.fullPathName = ''
        if design is not None:
            root.childOccurrences = design.rootComponent.occurrences
        self.designRootOccurrence = root

    def generateToolpath(self, ops):
        self.generated.append(list(ops))
        return object()


class Products:
    def __init__(self, cam):
        self.cam = cam

    def itemByProductType(self, t):
        return self.cam if t == 'CAMProductType' else None


class App:
    def __init__(self, design, cam):
        self.activeProduct = design
        self.activeDocument = type('Doc', (), {'products': Products(cam)})()
        self.userInterface = None


def linked_setup(cam, sheet_no, project='P1'):
    import json
    s = cam.setups.add(SetupInput(0))
    s.name = 'ContourNest Rohteil %02d' % sheet_no
    s.attributes.add('ContourNest', 'cam_link', json.dumps({'project_id': project, 'project_sheet': sheet_no}))
    return s
