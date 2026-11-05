"""Stub von adsk.cam: Enums, CAM.cast, CAMManager (Bibliotheken liefert der Test über CAMManager._lm)."""


class OperationTypes:
    MillingOperation = 0
    TurningOperation = 1
    JetOperation = 2


class SetupStockModes:
    FixedBoxStock = 0
    SolidStock = 6


class LibraryLocations:
    LocalLibraryLocation = 0
    CloudLibraryLocation = 1
    NetworkLibraryLocation = 2
    OnlineSamplesLibraryLocation = 3
    ExternalLibraryLocation = 4
    Fusion360LibraryLocation = 5
    HubLibraryLocation = 6


class CAM:
    @staticmethod
    def cast(x):
        return x


class _MgrHolder:
    def __init__(self, lm):
        self.libraryManager = lm


class CAMManager:
    _lm = None

    @staticmethod
    def get():
        return _MgrHolder(CAMManager._lm)
