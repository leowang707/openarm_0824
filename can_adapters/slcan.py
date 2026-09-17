from __future__ import annotations

import platform
from typing import Any

import can
from serial.tools import list_ports

from .base import AdapterDevice
from .registry import register_adapter

BABEL_VID, BABEL_PID = 0x1D50, 0x60C7
SLCAN_TTY_BAUD = 115_200


class SlcanAdapter:
    key = "slcan"
    label = "SLCAN / Lawicel"
    transport = "serial"
    default_channel = None

    def supported(self) -> bool:
        return platform.system().lower() in {"windows", "linux", "darwin"}

    def discover(self) -> list[AdapterDevice]:
        devices: list[AdapterDevice] = []

        for port in list_ports.comports():
            vid = getattr(port, "vid", None)
            pid = getattr(port, "pid", None)
            blob = " ".join(
                (
                    port.description or "",
                    port.hwid or "",
                    getattr(port, "manufacturer", None) or "",
                    getattr(port, "product", None) or "",
                )
            ).lower()

            is_slcan = (
                (vid == BABEL_VID and pid == BABEL_PID)
                or "1d50:60c7" in blob
                or "zubax" in blob
                or "babel" in blob
                or "slcan" in blob
                or "canface" in blob
            )
            if not is_slcan:
                continue

            devices.append(
                AdapterDevice(
                    adapter=self.key,
                    channel=port.device,
                    label=f"{port.device} — {port.description or 'SLCAN'}",
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
            raise ValueError("SLCAN requires a COM/tty channel")
        return value

    def open(self, channel: Any, bitrate: int, **kwargs: Any):
        channel = self.normalize_channel(channel)
        tty_baudrate = int(kwargs.pop("tty_baudrate", SLCAN_TTY_BAUD))
        return can.Bus(
            interface="slcan",
            channel=channel,
            bitrate=int(bitrate),
            tty_baudrate=tty_baudrate,
            sleep_after_open=float(kwargs.pop("sleep_after_open", 1.0)),
            ignore_config=True,
            **kwargs,
        )


register_adapter(SlcanAdapter())
