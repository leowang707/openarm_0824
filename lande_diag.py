from __future__ import annotations

import argparse
import time

import can

from can_adapters import adapter_keys, open_can_bus
from lande_motor import (
    DOCUMENTED_MOTOR_ID_MAX,
    PARAMETER_ADDRESSABLE_MOTOR_ID_MAX,
)

FIRMWARE_READ = bytes([0x67, 0x0A, 0, 0, 0, 0, 0x04, 0x76])
RESET_STATE = bytes([0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFD])


def _int_auto(text: str) -> int:
    return int(text, 0)


def _print_rx(prefix: str, msg: can.Message) -> None:
    kind = "EXT" if msg.is_extended_id else "STD"
    fd = " FD" if getattr(msg, "is_fd", False) else ""
    print(
        f"{prefix} ID=0x{msg.arbitration_id:03X} "
        f"{kind}{fd} DLC={msg.dlc} "
        f"DATA={bytes(msg.data).hex(' ').upper()}"
    )


def _drain(bus) -> None:
    while bus.recv(timeout=0) is not None:
        pass


def _collect_raw(bus, timeout: float, prefix: str = "RX") -> list[can.Message]:
    found: list[can.Message] = []
    deadline = time.perf_counter() + timeout
    while time.perf_counter() < deadline:
        remain = deadline - time.perf_counter()
        msg = bus.recv(timeout=min(0.01, max(0.0, remain)))
        if msg is None:
            continue
        found.append(msg)
        _print_rx(prefix, msg)
    return found


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Raw PA043 CAN2.0A diagnostic; no PA043 reply parser."
    )
    parser.add_argument("--adapter", choices=adapter_keys(), required=True)
    parser.add_argument("--channel", required=True)
    parser.add_argument("--bitrate", type=_int_auto, default=1_000_000)
    parser.add_argument(
        "--action",
        choices=["listen", "firmware-scan", "reset-scan"],
        default="listen",
    )
    parser.add_argument("--start-id", type=_int_auto, default=0)
    parser.add_argument("--end-id", type=_int_auto, default=None)
    parser.add_argument("--reply-timeout", type=float, default=0.03)
    parser.add_argument("--listen-seconds", type=float, default=5.0)
    args = parser.parse_args()

    if args.bitrate != 1_000_000:
        print("WARNING: PA043 manual specifies Classic CAN2.0A at 1 Mbps.")

    bus = open_can_bus(
        adapter=args.adapter,
        channel=args.channel,
        bitrate=args.bitrate,
    )

    print(f"Adapter : {args.adapter}")
    print(f"Channel : {args.channel}")
    print(f"Bitrate : {args.bitrate}")
    print("Frame   : Classic CAN2.0A / standard 11-bit / not CAN FD")
    print(f"Action  : {args.action}")
    print()

    try:
        _drain(bus)

        if args.action == "listen":
            frames = _collect_raw(bus, max(0.0, args.listen_seconds))
            print(f"Total RX frames: {len(frames)}")
            return

        if args.action == "firmware-scan":
            end_id = (
                PARAMETER_ADDRESSABLE_MOTOR_ID_MAX
                if args.end_id is None
                else int(args.end_id)
            )
            if end_id > PARAMETER_ADDRESSABLE_MOTOR_ID_MAX:
                raise ValueError(
                    "Parameter scan above 0x1FF is undocumented by the "
                    "vendor's CAN2.0A + (0x600 + Motor-ID) rules."
                )

            total_rx = 0
            for motor_id in range(args.start_id, end_id + 1):
                tx_id = 0x600 + motor_id
                tx = can.Message(
                    arbitration_id=tx_id,
                    is_extended_id=False,
                    is_fd=False,
                    data=FIRMWARE_READ,
                )
                print(
                    f"TX candidate=0x{motor_id:03X} "
                    f"ID=0x{tx_id:03X} "
                    f"DATA={FIRMWARE_READ.hex(' ').upper()}"
                )
                _drain(bus)
                bus.send(tx)
                total_rx += len(
                    _collect_raw(bus, args.reply_timeout, "  RX")
                )
            print(f"Total RX frames: {total_rx}")
            return

        end_id = (
            DOCUMENTED_MOTOR_ID_MAX
            if args.end_id is None
            else int(args.end_id)
        )
        if end_id > 0x7FF:
            raise ValueError("Reset-state scan end-id must be <= 0x7FF.")

        total_rx = 0
        for motor_id in range(args.start_id, end_id + 1):
            tx = can.Message(
                arbitration_id=motor_id,
                is_extended_id=False,
                is_fd=False,
                data=RESET_STATE,
            )
            print(
                f"TX candidate=0x{motor_id:03X} "
                f"ID=0x{motor_id:03X} "
                f"DATA={RESET_STATE.hex(' ').upper()}"
            )
            _drain(bus)
            bus.send(tx)
            total_rx += len(
                _collect_raw(bus, args.reply_timeout, "  RX")
            )
        print(f"Total RX frames: {total_rx}")

    finally:
        bus.shutdown()


if __name__ == "__main__":
    main()
