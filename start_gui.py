from __future__ import annotations

import argparse

from gui_server import run_server


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Cross-platform CAN motor GUI"
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5000)
    args = parser.parse_args()
    run_server(host=args.host, port=args.port)


if __name__ == "__main__":
    main()
