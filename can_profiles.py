"""CAN configuration metadata, not hardware auto-detection or negotiation.

A declared profile does not prove that a device is configured for it.
The motor protocol binding and the host backend must both support it.
"""
from __future__ import annotations

from dataclasses import dataclass


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
    evidence: str = "documented"
    protocol_key: str = ""

    def __post_init__(self) -> None:
        if not self.key or not self.label:
            raise ValueError("Profile key and label must be non-empty")
        if type(self.fd) is not bool or type(self.implemented) is not bool:
            raise TypeError("fd and implemented must be bool")
        if type(self.nominal_bitrate) is not int:
            raise TypeError("nominal_bitrate must be int")
        if self.data_bitrate is not None and type(self.data_bitrate) is not int:
            raise TypeError("data_bitrate must be int or None")
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
            "evidence": self.evidence,
            "protocol_key": self.protocol_key,
        }
