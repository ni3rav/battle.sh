"""Unified ``battle-sh`` command line: menu-first player app and ``relay``.

A single entry point drives the whole multiplayer experience so players never
run ``uv``, clone the repo, or invoke Python modules directly:

    battle-sh                      # open the Textual player app
    battle-sh --relay URL          # same, with Relay URL
    battle-sh relay                # run the Match Relay server

The relay URL defaults to ``ws://127.0.0.1:8765`` and can be set with
``--relay`` or the ``BATTLE_SH_RELAY`` environment variable. Reconnect grace
is ``--grace-seconds`` (CLI-only; not collected in the TUI).
"""

from __future__ import annotations

import argparse
import asyncio
import os

from battle_sh.networking.protocol import DEFAULT_GRACE_SECONDS
from battle_sh.networking.relay import run_relay
from battle_sh.observability import configure_client_logging, configure_logging

DEFAULT_RELAY = "ws://127.0.0.1:8765"
DEFAULT_BIND_HOST = "127.0.0.1"
DEFAULT_PORT = 8765


def _default_relay() -> str:
    return os.environ.get("BATTLE_SH_RELAY", DEFAULT_RELAY)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="battle-sh",
        description="Terminal two-player Battleship over a WebSocket Relay.",
    )
    parser.add_argument(
        "--relay",
        default=_default_relay(),
        help=f"Relay WebSocket URL (default: {_default_relay()})",
    )
    parser.add_argument(
        "--grace-seconds",
        type=float,
        default=DEFAULT_GRACE_SECONDS,
        help="Reconnect grace window in seconds",
    )

    subcommands = parser.add_subparsers(dest="command", required=False)

    relay = subcommands.add_parser("relay", help="Run the Match Relay server")
    relay.add_argument(
        "--bind-host",
        default=DEFAULT_BIND_HOST,
        help="Address to bind (use 127.0.0.1 behind Caddy)",
    )
    relay.add_argument(
        "--port", type=int, default=DEFAULT_PORT, help="Listen port"
    )
    relay.add_argument(
        "--grace-seconds",
        type=float,
        default=DEFAULT_GRACE_SECONDS,
        help="Reconnect grace window in seconds",
    )
    return parser


def _run_player(args: argparse.Namespace) -> None:
    from battle_sh.ui.textual_app import BattleShApp

    configure_client_logging("player")
    try:
        BattleShApp(
            relay_url=args.relay, grace_seconds=args.grace_seconds
        ).run()
    except KeyboardInterrupt:
        print("Interrupted. Exiting.")


def _run_relay(args: argparse.Namespace) -> None:
    configure_logging(component="relay")
    try:
        asyncio.run(
            run_relay(args.bind_host, args.port, grace_seconds=args.grace_seconds)
        )
    except KeyboardInterrupt:
        print("Relay stopped.")


def main(argv: list[str] | None = None) -> None:
    try:
        args = build_parser().parse_args(argv)
        if args.command == "relay":
            _run_relay(args)
        else:
            _run_player(args)
    except KeyboardInterrupt:
        print("Interrupted. Exiting.")


if __name__ == "__main__":
    main()
