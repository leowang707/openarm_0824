from __future__ import annotations

import platform
from typing import Any

import can

from .base import AdapterCapabilities, AdapterDevice
from .registry import register_adapter


class SocketCANAdapter:
    capabilities = AdapterCapabilities(
        classic_can=True,
        can_fd=False,
        notes='Current SocketCAN path has no CAN-FD profile plumbing yet.',
    )
    key = "socketcan"
    label = "Linux SocketCAN"
    transport = "network"
    default_channel = "can0"

    def supported(self) -> bool:
        return platform.system().lower() == "linux"

    def discover(self) -> list[AdapterDevice]:
        if not self.supported():
            return []

        try:
            configs = can.detect_available_configs(interfaces="socketcan")
        except Exception:
            return []

        devices: list[AdapterDevice] = []
        for config in configs:
            channel = config.get("channel")
            if not channel:
                continue
            devices.append(
                AdapterDevice(
                    adapter=self.key,
                    channel=str(channel),
                    label=f"{channel} — SocketCAN",
                    transport=self.transport,
                    metadata=dict(config),
                )
            )
        return devices

    def normalize_channel(self, channel: Any) -> str:
        value = str(channel or "can0").strip()
        return value or "can0"

    def open(self, channel: Any, bitrate: int, **kwargs: Any):
        # SocketCAN bitrate is configured by the Linux network layer, e.g.:
        # sudo ip link set can0 down
        # sudo ip link set can0 type can bitrate 1000000
        # sudo ip link set can0 up
        del bitrate
        return can.Bus(
            interface="socketcan",
            channel=self.normalize_channel(channel),
            ignore_config=True,
            **kwargs,
        )


register_adapter(SocketCANAdapter())
