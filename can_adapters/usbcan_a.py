from __future__ import annotations

import platform
from typing import Any

import can
from serial.tools import list_ports

from .base import AdapterDevice
from .registry import register_adapter

CH340_VID, CH340_PID = 0x1A86, 0x7523


class UsbCanAAdapter:
    key = "usbcan_a"
    label = "Waveshare USB-CAN-A"
    transport = "serial"
    default_channel = None

    def supported(self) -> bool:
        return platform.system().lower() in {"windows", "linux", "darwin"}

    def discover(self) -> list[AdapterDevice]:
        devices: list[AdapterDevice] = []

        for port in list_ports.comports():
            vid = getattr(port, "vid", None)
            pid = getattr(port, "pid", None)
            blob = " ".join((port.description or "", port.hwid or "")).lower()

            is_candidate = (
                (vid == CH340_VID and pid == CH340_PID)
                or "1a86:7523" in blob
                or "ch340" in blob
            )
            if not is_candidate:
                continue

            devices.append(
                AdapterDevice(
                    adapter=self.key,
                    channel=port.device,
                    label=f"{port.device} — Waveshare USB-CAN-A / CH340",
                    transport=self.transport,
                    metadata={
                        "vid": vid,
                        "pid": pid,
                        "description": port.description or "",
                        "hwid": port.hwid or "",
                    },
                )
            )

        return devices

    def normalize_channel(self, channel: Any) -> str:
        value = str(channel or "").strip()
        if not value:
            raise ValueError("USB-CAN-A requires a COM/tty channel")
        return value

    def open(self, channel: Any, bitrate: int, **kwargs: Any):
        # This imports the existing project-level usbcan_a.py backend.
        from usbcan_a import register_backend

        register_backend()
        channel = self.normalize_channel(channel)
        baudrate = int(kwargs.pop("baudrate", 2_000_000))

        return can.Bus(
            interface="usbcan_a",
            channel=channel,
            bitrate=int(bitrate),
            baudrate=baudrate,
            ignore_config=True,
            **kwargs,
        )


register_adapter(UsbCanAAdapter())
