"""Motor model registry."""

from .base import MotorBackend
from .registry import (
    BusProfile,
    MotorSpec,
    get_motor_spec,
    list_motor_models,
    list_motor_brands,
    motor_keys,
    register_motor,
)

# Import built-ins for registration side effects.
from . import lande as _lande  # noqa: F401,E402
from . import damiao as _damiao  # noqa: F401,E402

__all__ = [
    "MotorBackend",
    "BusProfile",
    "MotorSpec",
    "get_motor_spec",
    "list_motor_models",
    "list_motor_brands",
    "motor_keys",
    "register_motor",
]
