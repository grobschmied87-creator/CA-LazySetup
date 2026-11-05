"""Minimal-Stub von adsk.fusion."""


class Design:
    @staticmethod
    def cast(x):
        return x if getattr(x, 'is_design', False) else None
