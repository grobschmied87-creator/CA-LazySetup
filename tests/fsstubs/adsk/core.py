"""Minimal-Stub von adsk.core für Finalschnitt-Tests."""


class _H:
    def __init__(self, *a, **k):
        pass


for _n in ('CommandCreatedEventHandler', 'CommandEventHandler', 'InputChangedEventHandler',
           'ValidateInputsEventHandler', 'CustomEventHandler', 'HTMLEventHandler',
           'UserInterfaceGeneralEventHandler'):
    globals()[_n] = type(_n, (_H,), {})


class Point3D:
    def __init__(self, x=0.0, y=0.0, z=0.0):
        self.x, self.y, self.z = x, y, z

    @staticmethod
    def create(x=0.0, y=0.0, z=0.0):
        return Point3D(x, y, z)


class Vector3D(Point3D):
    @staticmethod
    def create(x=0.0, y=0.0, z=0.0):
        return Vector3D(x, y, z)


class ObjectCollection(list):
    @staticmethod
    def create():
        return ObjectCollection()

    @staticmethod
    def createWithArray(a):
        return ObjectCollection(a)

    def add(self, o):
        self.append(o)
        return True

    @property
    def count(self):
        return len(self)

    def item(self, i):
        return self[i]


class URL:
    def __init__(self, s):
        self.s = s

    @staticmethod
    def create(s):
        return URL(s)

    def toString(self):
        return self.s


class DropDownStyles:
    TextListDropDownStyle = 1
    CheckBoxDropDownStyle = 2
    LabeledIconDropDownStyle = 0


class MessageBoxButtonTypes:
    OKButtonType = 0
    YesNoButtonType = 3


class MessageBoxIconTypes:
    QuestionIconType = 2


class DialogResults:
    DialogOK = 0
    DialogYes = 2
    DialogNo = 3


class Application:
    _inst = None

    @staticmethod
    def get():
        return Application._inst


class HTMLEventArgs:
    @staticmethod
    def cast(a):
        return a


class PaletteDockingStates:
    PaletteDockStateFloating = 0
    PaletteDockStateRight = 3
