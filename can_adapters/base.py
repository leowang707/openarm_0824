from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class AdapterCapabilities:
    """Transport capabilities exposed by an adapter backend."""

    classic_can: bool = True
    can_fd: bool = False
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "classic_can": self.classic_can,
            "can_fd": self.can_fd,
            "notes": self.notes,
        }


@dataclass(frozen=True)
class AdapterDevice:
    adapter: str
    channel: Any
    label: str
    transport: str
    metadata: dict[str, Any] = field(default_factory=dict)
    hardware_family: str | None = None
    auto_selectable: bool = True
    capabilities: AdapterCapabilities | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "adapter": self.adapter,
            "channel": self.channel,
            "label": self.label,
            "transport": self.transport,
            "metadata": dict(self.metadata),
            "backend": self.adapter,
            "hardware_family": self.hardware_family,
            "auto_selectable": self.auto_selectable,
            "capabilities": self.capabilities.to_dict() if self.capabilities else None,
        }


class CANAdapter(Protocol):
    key: str
    label: str
    transport: str
    default_channel: Any
    capabilities: AdapterCapabilities

    def supported(self) -> bool:
        ...

    def discover(self) -> list[AdapterDevice]:
        ...

    def normalize_channel(self, channel: Any) -> Any:
        ...

    def open(self, channel: Any, bitrate: int, **kwargs: Any):
        ...
