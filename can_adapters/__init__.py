"""Cross-platform CAN adapter registry."""

from .base import AdapterDevice
from .registry import (
    ThreadSafeBus,
    adapter_keys,
    discover_all,
    get_adapter,
    list_adapter_devices,
    list_adapter_types,
    looks_like_serial_channel,
    open_can_bus,
    register_adapter,
    resolve_adapter,
)

# Import built-ins for registration side effects.
from . import slcan as _slcan  # noqa: F401,E402
from . import usbcan_a as _usbcan_a  # noqa: F401,E402
from . import gs_usb as _gs_usb  # noqa: F401,E402
from . import socketcan as _socketcan  # noqa: F401,E402

__all__ = [
    "AdapterDevice",
    "ThreadSafeBus",
    "adapter_keys",
    "discover_all",
    "get_adapter",
    "list_adapter_devices",
    "list_adapter_types",
    "looks_like_serial_channel",
    "open_can_bus",
    "register_adapter",
    "resolve_adapter",
]
