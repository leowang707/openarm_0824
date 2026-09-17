from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class AdapterDevice:
    adapter: str
    channel: Any
    label: str
    transport: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "adapter": self.adapter,
            "channel": self.channel,
            "label": self.label,
            "transport": self.transport,
            "metadata": dict(self.metadata),
        }


class CANAdapter(Protocol):
    key: str
    label: str
    transport: str
    default_channel: Any

    def supported(self) -> bool:
        ...

    def discover(self) -> list[AdapterDevice]:
        ...

    def normalize_channel(self, channel: Any) -> Any:
        ...

    def open(self, channel: Any, bitrate: int, **kwargs: Any):
        ...
