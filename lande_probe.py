from __future__ import annotations

import argparse

from can_adapters import adapter_keys, list_adapter_devices
from motor_service import MotorService


def _int_auto(text: str) -> int:
    return int(text, 0)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Read-only LANDA PA043 probe using the universal adapter registry"
    )
    parser.add_argument(
        "--adapter",
        choices=["auto", *adapter_keys()],
        default="auto",
        help="CAN adapter backend",
    )
    parser.add_argument(
        "--channel",
        "--port",
        dest="channel",
        default=None,
        help="COM5, /dev/ttyUSB0, 0 for gs_usb, or can0 for SocketCAN",
    )
    parser.add_argument("--id", type=_int_auto, default=None, help="Known Motor ID")
    parser.add_argument(
        "--scan-end",
        type=_int_auto,
        default=0x10,
        help="Scan 0..scan-end when --id is omitted",
    )
    args = parser.parse_args()

    print("Detected CAN devices:")
    devices = list_adapter_devices(include_unknown_serial=True)
    if not devices:
        print("  (none)")
    else:
        for item in devices:
            print(
                f"  [{item['adapter']}] {item['label']} "
                f"(channel={item['channel']})"
            )
    print()

    service = MotorService()
    try:
        info = service.connect(
            adapter=args.adapter,
            channel=args.channel,
            motor_model="lande_pa043",
        )
    except Exception as exc:
        print(f"Cannot open CAN adapter: {exc}")
        raise SystemExit(2)

    print(f"Adapter     : {info['adapter']}")
    print(f"Channel     : {info['channel']}")
    print(f"CAN bitrate : {info['bitrate']}")
    print("Test mode   : READ-ONLY")
    print()

    try:
        if args.id is not None:
            start_id = end_id = args.id
        else:
            start_id = 0
            end_id = args.scan_end

        motors = service.scan(start_id, end_id)

        if not motors:
            print("No PA043 motor responded.")
            print("Check adapter backend, CAN-H/CAN-L, common ground, 1 Mbps, termination, and ID range.")
            return

        for item in motors:
            print("=" * 56)
            print(f"FOUND PA043 Motor ID {item['id']} (0x{item['id']:03X})")
            print(f"Firmware Version : {item.get('firmware')}")
            print(
                "Control Mode     : "
                f"{item.get('control_mode_key') or 'Unknown'} "
                f"({item.get('control_mode_name') or 'Unknown'})"
            )
            print(f"Stored Motor ID  : {item.get('stored_id')}")

        print("=" * 56)
        print("Found IDs:", [item["id"] for item in motors])

    finally:
        service.disconnect()


if __name__ == "__main__":
    main()
