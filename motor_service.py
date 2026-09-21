from __future__ import annotations

import threading
from typing import Any

import can_adapters  # noqa: F401 - ensure built-in adapters are registered
import motors  # noqa: F401 - ensure built-in motor models are registered

from can_adapters import (
    get_adapter,
    list_adapter_devices,
    list_adapter_types,
    open_can_bus,
    resolve_adapter,
)
from motors import get_motor_spec, list_motor_models, list_motor_brands


class MotorService:
    """Application-facing service combining a motor model with a CAN adapter."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self.bus = None
        self.backend = None
        self.adapter: str | None = None
        self.channel: Any = None
        self.motor_model: str | None = None
        self.bus_profile: str | None = None
        self.bitrate: int | None = None
        self.data_bitrate: int | None = None
        self.fd: bool = False

    @staticmethod
    def capabilities(*, include_devices: bool = True) -> dict[str, Any]:
        return {
            "adapters": list_adapter_types(),
            "devices": list_adapter_devices(include_unknown_serial=True) if include_devices else [],
            "brands": list_motor_brands(),
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
        bus_profile: str | None = None,
        bitrate: int | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            motor_spec = get_motor_spec(motor_model)
            profile = motor_spec.get_bus_profile(bus_profile)

            if not profile.implemented:
                raise RuntimeError(
                    f"{motor_spec.name} bus profile {profile.key!r} is recorded "
                    "but not implemented by this repository yet"
                )

            if profile.protocol_key and profile.protocol_key != motor_spec.protocol_family:
                raise RuntimeError(
                    f"No motor protocol binding for {profile.protocol_key!r}; "
                    "a CAN-FD flag alone cannot select a wire protocol"
                )

            if bitrate is not None and int(bitrate) != profile.nominal_bitrate:
                raise ValueError(
                    f"Explicit bitrate {int(bitrate)} conflicts with profile "
                    f"{profile.key!r} nominal bitrate {profile.nominal_bitrate}"
                )

            kind, resolved_channel = resolve_adapter(adapter, channel)
            adapter_backend = get_adapter(kind)

            if profile.fd and not adapter_backend.capabilities.can_fd:
                raise RuntimeError(
                    f"Bus profile {profile.key!r} requires CAN-FD, but adapter "
                    f"{kind!r} is Classic-CAN only in the current repo backend"
                )
            if not profile.fd and not adapter_backend.capabilities.classic_can:
                raise RuntimeError(
                    f"Bus profile {profile.key!r} requires Classic CAN, but "
                    f"adapter {kind!r} does not expose Classic CAN"
                )

            # Do not close a working connection until the requested configuration
            # has passed validation. Opening an adapter does not prove motor RX.
            self.disconnect()
            bus = open_can_bus(
                adapter=kind,
                channel=resolved_channel,
                bitrate=profile.nominal_bitrate,
                fd=profile.fd,
                data_bitrate=profile.data_bitrate,
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
            self.bus_profile = profile.key
            self.bitrate = profile.nominal_bitrate
            self.data_bitrate = profile.data_bitrate
            self.fd = profile.fd

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
            self.bus_profile = None
            self.bitrate = None
            self.data_bitrate = None
            self.fd = False

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
            "connection_state": "adapter_open" if self.connected else "disconnected",
            "adapter": self.adapter,
            "channel": self.channel,
            "motor_model": self.motor_model,
            "bus_profile": self.bus_profile,
            "bitrate": self.bitrate,
            "data_bitrate": self.data_bitrate,
            "fd": self.fd,
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

    def enable(self, motor_id: int):
        with self._lock:
            return self._require_backend().enable(int(motor_id))

    def disable(self, motor_id: int):
        with self._lock:
            return self._require_backend().disable(int(motor_id))

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
