import argparse
import time
import serial


BAUD_RATES = [
    9600,
    19200,
    38400,
    57600,
    115200,
    230400,
    250000,
    460800,
    500000,
    576000,
    750000,
    921600,
    1000000,
    1500000,
    2000000,
    3000000,
]


def query(ser, cmd):
    ser.reset_input_buffer()

    ser.write(cmd.encode("ascii") + b"\r")
    ser.flush()

    time.sleep(0.12)

    return ser.read(128)


def test_baud(port, baud):
    print("=" * 60)
    print(f"Testing {port} @ {baud}")
    print("=" * 60)

    try:
        with serial.Serial(
            port=port,
            baudrate=baud,
            bytesize=8,
            parity="N",
            stopbits=1,
            timeout=0.25,
            write_timeout=1.0,
            xonxoff=False,
            rtscts=False,
            dsrdtr=False,
        ) as ser:

            tests = [
                ("V", "software version"),
                ("v", "hardware version"),
                ("N", "serial number"),
                ("F", "status flags"),
            ]

            valid = 0

            for cmd, name in tests:
                try:
                    reply = query(ser, cmd)

                except Exception as exc:
                    print(
                        f"{cmd} ({name}): "
                        f"ERROR: {exc}"
                    )
                    continue

                print(
                    f"{cmd} ({name}): "
                    f"raw={reply!r}"
                )

                if reply and reply != b"\x07":
                    valid += 1

            if valid >= 2:
                print(
                    f">>> POSSIBLE SLCAN FOUND "
                    f"@ {baud}"
                )
                return True

            if valid == 1:
                print(
                    f">>> Weak SLCAN evidence "
                    f"@ {baud}"
                )

            return False

    except Exception as exc:
        print(
            f"Could not open at {baud}: "
            f"{exc}"
        )
        return False


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--port",
        required=True,
        help="Serial port, e.g. COM5",
    )

    parser.add_argument(
        "--baud",
        type=int,
        default=None,
        help="Test only one baudrate",
    )

    args = parser.parse_args()

    if args.baud is not None:
        rates = [args.baud]
    else:
        rates = BAUD_RATES

    found = []

    for baud in rates:
        if test_baud(args.port, baud):
            found.append(baud)

        time.sleep(0.1)

    print()
    print("=" * 60)

    if found:
        print(
            "SLCAN candidate baudrate(s):",
            found,
        )
    else:
        print(
            "No standard SLCAN response "
            "detected at tested baudrates."
        )

    print("=" * 60)


if __name__ == "__main__":
    main()