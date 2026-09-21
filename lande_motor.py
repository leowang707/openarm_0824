"""Compatibility module. Canonical PA043 code is motors.lande.protocol.

Kept so existing imports, CLI scripts and users do not break in this refactor.
"""
from motors.lande import protocol as _protocol
from motors.lande.protocol import *  # noqa: F401,F403


def __getattr__(name):
    return getattr(_protocol, name)
