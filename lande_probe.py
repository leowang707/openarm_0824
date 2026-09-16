from __future__ import annotations

import argparse

from can_adapter import list_adapter_ports, open_serial_bus
from lande_motor import LandeMotor


MODE_NAMES = {
    0x01: "Servo",
    0x02: "Torque-Position Mixed",
    0x03: "Velocity",
    0x04: "Torque",
}


def main():
    parser = argparse.ArgumentParser(
        description="Read-only PA043 CAN probe"
    )

    parser.add_argument(
        "--port",
        required=True,
        help="SLCAN COM port, e.g. COM5",
    )

    parser.add_argument(
        "--id",
        type=lambda x: int(x, 0),
        default=None,
        help="Known motor ID",
    )

    parser.add_argument(
        "--scan-end",
        type=lambda x: int(x, 0),
        default=0x10,
        help="Scan motor IDs from 0 to scan-end",
    )

    args = parser.parse_args()

    print("Detected serial ports:")

    for item in list_adapter_ports():
        print(
            f"  {item['device']} "
            f"{item['description']} "
            f"({item['kind']})"
        )

    print()
    print(f"Opening {args.port} as SLCAN")
    print("CAN bitrate: 1 Mbps")
    print("READ-ONLY test")

    bus = open_serial_bus(
        channel=args.port,
        kind="slcan",
        bitrate=1_000_000,
    )

    try:
        if args.id is not None:
            ids = [args.id]
        else:
            ids = range(0, args.scan_end + 1)

        found = []

        for motor_id in ids:
            motor = LandeMotor(bus, motor_id)

            try:
                fw = motor.get_firmware_version()

            except TimeoutError:
                print(f"ID {motor_id:3d}: no response")
                continue

            found.append(motor_id)

            print()
            print(f"*** FOUND MOTOR ID {motor_id} ***")
            print(f"Firmware Version : {fw}")

            try:
                mode = motor.get_control_mode()

                print(
                    f"Control Mode     : "
                    f"0x{mode:02X} "
                    f"({MODE_NAMES.get(mode, 'Unknown')})"
                )

            except TimeoutError:
                print("Control Mode     : timeout")

            try:
                stored_id = motor.get_motor_id()
                print(f"Stored Motor ID  : {stored_id}")

            except TimeoutError:
                print("Stored Motor ID  : timeout")

        print()

        if found:
            print("Found IDs:", found)
        else:
            print("No PA043 motor responded.")

    finally:
        bus.shutdown()


if __name__ == "__main__":
    main()