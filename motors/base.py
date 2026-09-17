from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class MotorBackend(ABC):
    """Common interface exposed to the application layer."""

    model_key: str
    model_name: str
    supported_modes: tuple[str, ...] = ()

    def __init__(self, bus: Any) -> None:
        self.bus = bus

    @abstractmethod
    def scan(self, start_id: int, end_id: int) -> list[dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def get_motor(self, motor_id: int):
        raise NotImplementedError

    @abstractmethod
    def enable(self, motor_id: int) -> None:
        raise NotImplementedError

    @abstractmethod
    def disable(self, motor_id: int) -> None:
        raise NotImplementedError

    @abstractmethod
    def get_state(self, motor_id: int) -> dict[str, Any]:
        raise NotImplementedError

    def get_control_mode(self, motor_id: int) -> str | None:
        del motor_id
        return None

    def set_control_mode(self, motor_id: int, mode: str, save: bool = True):
        del motor_id, mode, save
        raise NotImplementedError(f"{self.model_name} does not support mode changes")

    def send_command(self, motor_id: int, mode: str, **kwargs: Any):
        del motor_id, mode, kwargs
        raise NotImplementedError(f"{self.model_name} does not expose generic commands")

    def shutdown(self) -> None:
        """Release model-specific resources. The MotorService owns the CAN bus."""
