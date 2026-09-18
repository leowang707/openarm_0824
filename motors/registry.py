from __future__ import annotations

from dataclasses import dataclass
from typing import Type

from .base import MotorBackend


@dataclass(frozen=True)
class BusProfile:
    """Physical CAN transport/profile for a motor configuration."""

    key: str
    label: str
    fd: bool
    nominal_bitrate: int
    data_bitrate: int | None = None
    implemented: bool = True
    notes: str = ""

    def __post_init__(self) -> None:
        if self.nominal_bitrate <= 0:
            raise ValueError("nominal_bitrate must be positive")
        if self.fd:
            if self.data_bitrate is None or self.data_bitrate <= 0:
                raise ValueError("CAN-FD profile requires positive data_bitrate")
        elif self.data_bitrate is not None:
            raise ValueError("Classic CAN profile must not define data_bitrate")

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "label": self.label,
            "fd": self.fd,
            "nominal_bitrate": self.nominal_bitrate,
            "data_bitrate": self.data_bitrate,
            "implemented": self.implemented,
            "notes": self.notes,
        }


@dataclass(frozen=True)
class MotorSpec:
    key: str
    name: str
    backend: Type[MotorBackend]
    bus_profiles: tuple[BusProfile, ...]
    default_bus_profile: str
    default_scan_start: int
    default_scan_end: int
    supported_modes: tuple[str, ...]
    motion_safe_default: bool = False

    def __post_init__(self) -> None:
        keys = [profile.key for profile in self.bus_profiles]
        if not keys:
            raise ValueError(f"{self.key}: at least one bus profile is required")
        if len(keys) != len(set(keys)):
            raise ValueError(f"{self.key}: duplicate bus profile key")
        if self.default_bus_profile not in keys:
            raise ValueError(
                f"{self.key}: default bus profile {self.default_bus_profile!r} "
                f"is not one of {keys}"
            )

    def get_bus_profile(self, key: str | None = None) -> BusProfile:
        wanted = key or self.default_bus_profile
        for profile in self.bus_profiles:
            if profile.key == wanted:
                return profile
        raise ValueError(
            f"{self.name} does not define bus profile {wanted!r}. "
            f"Available: {', '.join(profile.key for profile in self.bus_profiles)}"
        )

    @property
    def default_bitrate(self) -> int:
        """Compatibility accessor for existing code/clients."""
        return self.get_bus_profile().nominal_bitrate

    def to_dict(self) -> dict:
        default_profile = self.get_bus_profile()
        return {
            "key": self.key,
            "name": self.name,
            "default_bitrate": default_profile.nominal_bitrate,
            "default_bus_profile": self.default_bus_profile,
            "bus_profiles": [profile.to_dict() for profile in self.bus_profiles],
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
