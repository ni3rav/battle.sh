"""CLI entry: `python -m battle_sh.ui.cli` for Host / Guest play."""

from __future__ import annotations

import argparse
import asyncio
import os
import tempfile

from battle_sh.observability import configure_logging
from battle_sh.ui.play import LiveIO, run_guest, run_host


def _configure_client_logging(role: str) -> None:
    """Route client logs to a file so they never corrupt the terminal UI."""
    log_file = os.environ.get("BATTLE_SH_LOG_FILE")
    if not log_file:
        log_dir = os.path.join(tempfile.gettempdir(), "battle-sh")
        log_file = os.path.join(log_dir, f"{role}-{os.getpid()}.log")
    configure_logging(component=f"client-{role}", log_file=log_file)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Play battle.sh as Host or Guest against a Relay"
    )
    parser.add_argument(
        "role",
        choices=("host", "guest"),
        help="Host creates the Match; Guest joins with an Invite",
    )
    parser.add_argument(
        "--relay",
        default="ws://127.0.0.1:8765",
        help="Relay WebSocket URL (local default ws://127.0.0.1:8765)",
    )
    parser.add_argument(
        "--grace-seconds",
        type=float,
        default=30.0,
        help="Reconnect grace window in seconds",
    )
    parser.add_argument(
        "--invite",
        default=None,
        help="Invite phrase (Guest only; prompted if omitted)",
    )
    args = parser.parse_args(argv)
    _configure_client_logging(args.role)
    io = LiveIO()

    if args.role == "host":
        asyncio.run(
            run_host(args.relay, io, grace_seconds=args.grace_seconds)
        )
        return

    invite = args.invite
    if not invite:
        invite = io.ask("Paste Invite phrase (or q to quit)> ").strip()
    if invite.lower() in {"q", "quit", "exit"}:
        raise SystemExit(0)
    if not invite:
        raise SystemExit("Invite is required for Guest")
    asyncio.run(
        run_guest(args.relay, invite, io, grace_seconds=args.grace_seconds)
    )


if __name__ == "__main__":
    main()
