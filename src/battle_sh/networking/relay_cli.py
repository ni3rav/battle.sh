"""CLI entry: `python -m battle_sh.networking.relay_cli`."""

from __future__ import annotations

import argparse
import asyncio

from battle_sh.networking.relay import run_relay
from battle_sh.observability import configure_logging


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run the battle.sh Match Relay")
    parser.add_argument(
        "--bind-host",
        default="127.0.0.1",
        help="Address to bind (use 127.0.0.1 behind Caddy)",
    )
    parser.add_argument("--port", type=int, default=8765, help="Listen port")
    parser.add_argument(
        "--grace-seconds",
        type=float,
        default=30.0,
        help="Reconnect grace window in seconds",
    )
    args = parser.parse_args(argv)
    # Relay logs to stderr so systemd / a terminal captures structured records.
    configure_logging(component="relay")
    asyncio.run(
        run_relay(args.bind_host, args.port, grace_seconds=args.grace_seconds)
    )


if __name__ == "__main__":
    main()
