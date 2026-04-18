from __future__ import annotations

import argparse

from .server import run_server


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="jones")
    subparsers = parser.add_subparsers(dest="command", required=True)

    web = subparsers.add_parser("jones-web", help="Run simple Jones chat web server")
    web.add_argument("--host", default="127.0.0.1")
    web.add_argument("--port", type=int, default=8010)
    web.add_argument("--backend", choices=["mock", "deepinfra"], default="deepinfra")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "jones-web":
        run_server(host=args.host, port=args.port, backend=args.backend)
        return 0

    parser.error("Unsupported command")
    return 2
