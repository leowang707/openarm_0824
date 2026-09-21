"""Print model/profile/backend metadata; enumerate devices only on request."""
from __future__ import annotations
import argparse
import json
from motor_service import MotorService


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--devices", action="store_true", help="Also enumerate interfaces (no motor commands)")
    args = parser.parse_args()
    print(json.dumps(MotorService.capabilities(include_devices=args.devices), indent=2, ensure_ascii=True))


if __name__ == "__main__":
    main()
