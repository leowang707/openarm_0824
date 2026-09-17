"""Motor model registry."""

from .base import MotorBackend
from .registry import (
    MotorSpec,
    get_motor_spec,
    list_motor_models,
    motor_keys,
    register_motor,
)

# Import built-ins for registration side effects.
from . import lande as _lande  # noqa: F401,E402
from . import damiao as _damiao  # noqa: F401,E402

__all__ = [
    "MotorBackend",
    "MotorSpec",
    "get_motor_spec",
    "list_motor_models",
    "motor_keys",
    "register_motor",
]
