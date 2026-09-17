"""Backward-compatible facade for the new cross-platform adapter registry.

New code should import from ``can_adapters`` directly.
"""

from __future__ import annotations

from typing import Any

from can_adapters import (
    adapter_keys,
    list_adapter_devices,
    list_adapter_types,
    looks_like_serial_channel,
    open_can_bus,
    resolve_adapter,
)

CAN_BITRATE_DEFAULT = 1_000_000


def detect_kind(channel: Any, requested: str = "auto") -> str:
    kind, _ = resolve_adapter(requested, channel)
    return kind


def open_serial_bus(channel: Any, kind: str, bitrate: int = CAN_BITRATE_DEFAULT):
    """Legacy compatibility. Works for serial backends only by convention."""
    return open_can_bus(adapter=kind, channel=channel, bitrate=bitrate)


def list_adapter_ports() -> list[dict[str, Any]]:
    """Legacy serial-only view for older UI code."""
    result: list[dict[str, Any]] = []
    for item in list_adapter_devices(include_unknown_serial=True):
        if item["transport"] != "serial":
            continue
        result.append(
            {
                "device": item["channel"],
                "channel": item["channel"],
                "kind": item["adapter"],
                "adapter": item["adapter"],
                "transport": item["transport"],
                "description": item.get("metadata", {}).get("description", ""),
                "label": item["label"],
            }
        )
    return result


def list_serial_devices() -> list[str]:
    return [str(item["device"]) for item in list_adapter_ports()]


__all__ = [
    "CAN_BITRATE_DEFAULT",
    "adapter_keys",
    "detect_kind",
    "list_adapter_devices",
    "list_adapter_ports",
    "list_adapter_types",
    "list_serial_devices",
    "looks_like_serial_channel",
    "open_can_bus",
    "open_serial_bus",
    "resolve_adapter",
]
