from __future__ import annotations

import platform
import threading
from typing import Any, Optional

from serial.tools import list_ports

from .base import AdapterDevice, CANAdapter


_ADAPTERS: dict[str, CANAdapter] = {}


def register_adapter(adapter: CANAdapter) -> None:
    if adapter.key in _ADAPTERS:
        raise ValueError(f"Duplicate CAN adapter: {adapter.key}")
    _ADAPTERS[adapter.key] = adapter


def get_adapter(key: str) -> CANAdapter:
    try:
        return _ADAPTERS[key]
    except KeyError as exc:
        raise ValueError(
            f"Unknown CAN adapter {key!r}. Available: {', '.join(adapter_keys())}"
        ) from exc


def adapter_keys() -> list[str]:
    return list(_ADAPTERS.keys())


def list_adapter_types() -> list[dict[str, Any]]:
    return [
        {
            "key": adapter.key,
            "label": adapter.label,
            "transport": adapter.transport,
            "supported": bool(adapter.supported()),
        }
        for adapter in _ADAPTERS.values()
    ]


def looks_like_serial_channel(channel: Any) -> bool:
    name = str(channel or "").strip()
    upper = name.upper()
    return (
        upper.startswith("COM")
        or name.startswith("/dev/tty")
        or name.startswith("/dev/cu.")
    )


def _serial_metadata(port: Any) -> dict[str, Any]:
    return {
        "description": port.description or "",
        "hwid": port.hwid or "",
        "vid": getattr(port, "vid", None),
        "pid": getattr(port, "pid", None),
        "serial_number": getattr(port, "serial_number", None) or "",
        "manufacturer": getattr(port, "manufacturer", None) or "",
        "product": getattr(port, "product", None) or "",
    }


def discover_all(include_unknown_serial: bool = True) -> list[AdapterDevice]:
    devices: list[AdapterDevice] = []

    for adapter in _ADAPTERS.values():
        if not adapter.supported():
            continue
        try:
            devices.extend(adapter.discover())
        except Exception:
            # Discovery should not make the whole UI unusable when one optional
            # backend/driver is missing.
            continue

    if include_unknown_serial:
        known_serial = {
            str(device.channel).upper()
            for device in devices
            if device.transport == "serial"
        }
        for port in list_ports.comports():
            if port.device.upper() in known_serial:
                continue
            devices.append(
                AdapterDevice(
                    adapter="unknown_serial",
                    channel=port.device,
                    label=f"{port.device} — {port.description or 'Unknown serial device'}",
                    transport="serial",
                    metadata=_serial_metadata(port),
                )
            )

    devices.sort(key=lambda d: (d.adapter, str(d.channel)))
    return devices


def list_adapter_devices(include_unknown_serial: bool = True) -> list[dict[str, Any]]:
    return [
        device.to_dict()
        for device in discover_all(include_unknown_serial=include_unknown_serial)
    ]


def resolve_adapter(requested: str = "auto", channel: Any = None) -> tuple[str, Any]:
    requested = str(requested or "auto").strip().lower()
    has_channel = channel not in (None, "")

    if requested != "auto":
        adapter = get_adapter(requested)
        if not adapter.supported():
            raise RuntimeError(
                f"Adapter {requested!r} is not supported on {platform.system()}"
            )

        if not has_channel:
            discovered = adapter.discover()
            if len(discovered) == 1:
                channel = discovered[0].channel
            elif len(discovered) > 1:
                raise RuntimeError(
                    f"Multiple {requested} devices detected; specify a channel"
                )
            elif adapter.default_channel is not None:
                channel = adapter.default_channel
            else:
                raise RuntimeError(f"No {requested} device detected")

        return requested, adapter.normalize_channel(channel)

    # auto + explicit channel
    if has_channel:
        text = str(channel).strip()

        # Linux network-style SocketCAN interface.
        if platform.system().lower() == "linux" and text.startswith(("can", "vcan")):
            adapter = get_adapter("socketcan")
            return "socketcan", adapter.normalize_channel(text)

        # Serial channels: match only adapters that positively discovered this port.
        if looks_like_serial_channel(text):
            matches: list[tuple[str, Any]] = []
            for key, adapter in _ADAPTERS.items():
                if adapter.transport != "serial" or not adapter.supported():
                    continue
                try:
                    for device in adapter.discover():
                        if str(device.channel).upper() == text.upper():
                            matches.append((key, device.channel))
                except Exception:
                    pass

            if len(matches) == 1:
                return matches[0]
            if len(matches) > 1:
                raise RuntimeError(
                    f"Serial channel {text} matches multiple adapters: "
                    + ", ".join(key for key, _ in matches)
                )
            raise RuntimeError(
                f"Cannot identify CAN protocol for serial channel {text}. "
                "Choose --adapter explicitly."
            )

        # Non-serial devices (e.g. gs_usb index 0).
        matches = []
        for key, adapter in _ADAPTERS.items():
            if not adapter.supported():
                continue
            try:
                for device in adapter.discover():
                    if str(device.channel) == text:
                        matches.append((key, device.channel))
            except Exception:
                pass

        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise RuntimeError(
                f"Channel {channel!r} is ambiguous. Specify --adapter explicitly."
            )
        raise RuntimeError(f"Cannot auto-detect CAN adapter for channel {channel!r}")

    # auto + no channel
    detected = discover_all(include_unknown_serial=False)
    detected = [d for d in detected if d.adapter in _ADAPTERS]

    if len(detected) == 1:
        return detected[0].adapter, detected[0].channel
    if not detected:
        raise RuntimeError("No supported CAN adapter detected")

    summary = ", ".join(f"{d.adapter}:{d.channel}" for d in detected)
    raise RuntimeError(
        "Multiple CAN adapters detected; select adapter/channel explicitly: " + summary
    )


class ThreadSafeBus:
    """Serialize individual send/recv operations around a python-can Bus."""

    def __init__(self, bus: Any, *, adapter_kind: str, channel: Any) -> None:
        self._bus = bus
        self._io_lock = threading.RLock()
        self.adapter_kind = adapter_kind
        self.channel = channel

    def send(self, msg: Any, timeout: Optional[float] = None) -> Any:
        with self._io_lock:
            return self._bus.send(msg, timeout=timeout)

    def recv(self, timeout: Optional[float] = None) -> Any:
        with self._io_lock:
            return self._bus.recv(timeout=timeout)

    def shutdown(self) -> Any:
        with self._io_lock:
            return self._bus.shutdown()

    def flush_tx_buffer(self) -> Any:
        fn = getattr(self._bus, "flush_tx_buffer", None)
        if fn is None:
            return None
        with self._io_lock:
            return fn()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._bus, name)


def open_can_bus(
    adapter: str = "auto",
    channel: Any = None,
    bitrate: int = 1_000_000,
    **kwargs: Any,
) -> ThreadSafeBus:
    kind, resolved_channel = resolve_adapter(adapter, channel)
    backend = get_adapter(kind)
    raw_bus = backend.open(resolved_channel, int(bitrate), **kwargs)
    return ThreadSafeBus(
        raw_bus,
        adapter_kind=kind,
        channel=resolved_channel,
    )
