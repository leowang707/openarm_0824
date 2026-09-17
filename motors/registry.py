from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Type

from .base import MotorBackend


@dataclass(frozen=True)
class MotorSpec:
    key: str
    name: str
    backend: Type[MotorBackend]
    default_bitrate: int
    default_scan_start: int
    default_scan_end: int
    supported_modes: tuple[str, ...]
    motion_safe_default: bool = False

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "name": self.name,
            "default_bitrate": self.default_bitrate,
            "default_scan_start": self.default_scan_start,
            "default_scan_end": self.default_scan_end,
            "supported_modes": list(self.supported_modes),
            "motion_safe_default": self.motion_safe_default,
        }


_MOTORS: dict[str, MotorSpec] = {}


def register_motor(spec: MotorSpec) -> None:
    if spec.key in _MOTORS:
        raise ValueError(f"Duplicate motor model: {spec.key}")
    _MOTORS[spec.key] = spec


def get_motor_spec(key: str) -> MotorSpec:
    try:
        return _MOTORS[key]
    except KeyError as exc:
        raise ValueError(
            f"Unknown motor model {key!r}. Available: {', '.join(motor_keys())}"
        ) from exc


def motor_keys() -> list[str]:
    return list(_MOTORS.keys())


def list_motor_models() -> list[dict]:
    return [spec.to_dict() for spec in _MOTORS.values()]
