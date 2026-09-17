"""Backward-compatible import for the PA043 backend."""

from motors.lande import LandeBackend, MODE_KEYS, MODE_KEYS_REVERSE

__all__ = ["LandeBackend", "MODE_KEYS", "MODE_KEYS_REVERSE"]
