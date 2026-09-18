from __future__ import annotations

import platform
from typing import Any

import can

from .base import AdapterCapabilities, AdapterDevice
from .registry import register_adapter


class GsUsbAdapter:
    capabilities = AdapterCapabilities(
        classic_can=True,
        can_fd=False,
        notes='Current gs_usb path is treated as Classic CAN only.',
    )
    key = "gs_usb"
    label = "gs_usb / CANable / candleLight"
    transport = "usb"
    default_channel = 0

    def supported(self) -> bool:
        return platform.system().lower() in {"windows", "linux", "darwin"}

    def discover(self) -> list[AdapterDevice]:
        devices: list[AdapterDevice] = []

        try:
            configs = can.detect_available_configs(interfaces="gs_usb")
        except Exception:
            return devices

        for index, config in enumerate(configs):
            # python-can gs_usb accepts a device index as channel. Using the index
            # avoids tying the rest of the application to USB bus/address details.
            devices.append(
                AdapterDevice(
                    adapter=self.key,
                    channel=index,
                    label=f"gs_usb device {index}",
                    transport=self.transport,
                    metadata=dict(config),
                )
            )

        return devices

    def normalize_channel(self, channel: Any) -> int:
        if channel in (None, ""):
            return 0
        try:
            return int(channel)
        except (TypeError, ValueError) as exc:
            raise ValueError("gs_usb channel must be a device index, e.g. 0") from exc

    def open(self, channel: Any, bitrate: int, **kwargs: Any):
        index = self.normalize_channel(channel)
        return can.Bus(
            interface="gs_usb",
            channel=index,
            bitrate=int(bitrate),
            ignore_config=True,
            **kwargs,
        )


register_adapter(GsUsbAdapter())
