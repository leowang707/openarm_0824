from __future__ import annotations

import threading
from typing import Any

import can_adapters  # noqa: F401 - ensure built-in adapters are registered
import motors  # noqa: F401 - ensure built-in motor models are registered

from can_adapters import (
    list_adapter_devices,
    list_adapter_types,
    open_can_bus,
    resolve_adapter,
)
from motors import get_motor_spec, list_motor_models


class MotorService:
    """Application-facing service combining a motor model with a CAN adapter."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self.bus = None
        self.backend = None
        self.adapter: str | None = None
        self.channel: Any = None
        self.motor_model: str | None = None
        self.bitrate: int | None = None

    @staticmethod
    def capabilities() -> dict[str, Any]:
        return {
            "adapters": list_adapter_types(),
            "devices": list_adapter_devices(include_unknown_serial=True),
            "motors": list_motor_models(),
        }

    @property
    def connected(self) -> bool:
        return self.backend is not None and self.bus is not None

    def connect(
        self,
        *,
        adapter: str,
        channel: Any,
        motor_model: str,
        bitrate: int | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            self.disconnect()

            motor_spec = get_motor_spec(motor_model)
            use_bitrate = int(bitrate or motor_spec.default_bitrate)
            kind, resolved_channel = resolve_adapter(adapter, channel)

            bus = open_can_bus(
                adapter=kind,
                channel=resolved_channel,
                bitrate=use_bitrate,
            )

            try:
                backend = motor_spec.backend(bus)
            except Exception:
                bus.shutdown()
                raise

            self.bus = bus
            self.backend = backend
            self.adapter = kind
            self.channel = resolved_channel
            self.motor_model = motor_spec.key
            self.bitrate = use_bitrate

            return self.connection_info()

    def disconnect(self) -> None:
        with self._lock:
            backend = self.backend
            bus = self.bus

            self.backend = None
            self.bus = None
            self.adapter = None
            self.channel = None
            self.motor_model = None
            self.bitrate = None

            if backend is not None:
                try:
                    backend.shutdown()
                except Exception:
                    pass

            if bus is not None:
                try:
                    bus.shutdown()
                except Exception:
                    pass

    def _require_backend(self):
        if self.backend is None or self.motor_model is None:
            raise RuntimeError("Motor service is not connected")
        return self.backend

    def connection_info(self) -> dict[str, Any]:
        return {
            "connected": self.connected,
            "adapter": self.adapter,
            "channel": self.channel,
            "motor_model": self.motor_model,
            "bitrate": self.bitrate,
        }

    def scan(
        self,
        start_id: int | None = None,
        end_id: int | None = None,
    ) -> list[dict[str, Any]]:
        with self._lock:
            backend = self._require_backend()
            spec = get_motor_spec(self.motor_model)
            start = spec.default_scan_start if start_id is None else int(start_id)
            end = spec.default_scan_end if end_id is None else int(end_id)
            return backend.scan(start, end)

    def get_motor(self, motor_id: int):
        with self._lock:
            return self._require_backend().get_motor(int(motor_id))

    def enable(self, motor_id: int) -> None:
        with self._lock:
            self._require_backend().enable(int(motor_id))

    def disable(self, motor_id: int) -> None:
        with self._lock:
            self._require_backend().disable(int(motor_id))

    def get_state(self, motor_id: int) -> dict[str, Any]:
        with self._lock:
            return self._require_backend().get_state(int(motor_id))

    def get_control_mode(self, motor_id: int) -> str | None:
        with self._lock:
            return self._require_backend().get_control_mode(int(motor_id))

    def set_control_mode(self, motor_id: int, mode: str, save: bool = True):
        with self._lock:
            return self._require_backend().set_control_mode(int(motor_id), mode, save)

    def send_command(self, motor_id: int, mode: str, **kwargs: Any):
        with self._lock:
            return self._require_backend().send_command(int(motor_id), mode, **kwargs)
