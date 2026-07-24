"""Unified ``battle-sh`` command line: ``host``, ``join``, and ``relay``.

A single entry point drives the whole multiplayer experience so players never
run ``uv``, clone the repo, or invoke Python modules directly:

    battle-sh host                 # create a Match and print an Invite
    battle-sh join --invite ...    # join a Match via its Invite
    battle-sh relay                # run the Match Relay server

The relay URL defaults to ``ws://127.0.0.1:8765`` and can be set with
``--relay`` or the ``BATTLE_SH_RELAY`` environment variable.
"""

from __future__ import annotations

import argparse
import asyncio
import os

from battle_sh.networking.protocol import DEFAULT_GRACE_SECONDS
from battle_sh.networking.relay import run_relay
from battle_sh.observability import configure_client_logging, configure_logging
from battle_sh.ui.play import LiveIO, run_guest, run_host

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
    subcommands = parser.add_subparsers(dest="command", required=True)

    host = subcommands.add_parser(
        "host", help="Start a new multiplayer game and connect to the relay"
    )
    host.add_argument(
        "--relay",
        default=_default_relay(),
        help=f"Relay WebSocket URL (default: {_default_relay()})",
    )
    host.add_argument(
        "--grace-seconds",
        type=float,
        default=DEFAULT_GRACE_SECONDS,
        help="Reconnect grace window in seconds",
    )

    join = subcommands.add_parser(
        "join", help="Join an existing game through the relay"
    )
    join.add_argument(
        "--relay",
        default=_default_relay(),
        help=f"Relay WebSocket URL (default: {_default_relay()})",
    )
    join.add_argument(
        "--invite",
        default=None,
        help="Invite phrase from the host (prompted if omitted)",
    )
    join.add_argument(
        "--grace-seconds",
        type=float,
        default=DEFAULT_GRACE_SECONDS,
        help="Reconnect grace window in seconds",
    )

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


def _run_host(args: argparse.Namespace) -> None:
    configure_client_logging("host")
    try:
        asyncio.run(
            run_host(args.relay, LiveIO(), grace_seconds=args.grace_seconds)
        )
    except KeyboardInterrupt:
        print("Interrupted. Exiting.")


def _run_join(args: argparse.Namespace) -> None:
    configure_client_logging("guest")
    io = LiveIO()
    try:
        invite = args.invite
        if not invite:
            invite = io.ask("Paste Invite phrase (or q to quit)> ").strip()
        if invite.lower() in {"q", "quit", "exit"}:
            raise SystemExit(0)
        if not invite:
            raise SystemExit("Invite is required to join a game")
        asyncio.run(
            run_guest(args.relay, invite, io, grace_seconds=args.grace_seconds)
        )
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
        if args.command == "host":
            _run_host(args)
        elif args.command == "join":
            _run_join(args)
        elif args.command == "relay":
            _run_relay(args)
    except KeyboardInterrupt:
        print("Interrupted. Exiting.")


if __name__ == "__main__":
    main()
