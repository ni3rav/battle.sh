"""Host and Guest terminal Match play over a Relay."""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field

from battle_sh.networking.connection import (
    DuplicateShotError,
    IllegalShotError,
    MatchConnection,
    MatchConnectionError,
    NotYourTurnError,
    RevealVerificationError,
    ShotReport,
)
from battle_sh.networking.protocol import MatchOutcome
from battle_sh.rules.board import ShotResultKind, parse_coordinate
from battle_sh.rules.placement import Coordinate, Placement
from battle_sh.ui.boards import render_match_boards
from battle_sh.ui.placement_flow import run_placement
from rich.console import Console
from websockets.exceptions import ConnectionClosed


@dataclass
class ScriptedIO:
    """Injectable line IO for tests — records printed text, feeds scripted inputs."""

    inputs: deque[str]
    outputs: list[str] = field(default_factory=list)
    console: Console = field(
        default_factory=lambda: Console(record=True, force_terminal=True)
    )

    def print(self, *args: object, **kwargs: object) -> None:
        text = " ".join(str(a) for a in args)
        self.outputs.append(text)
        self.console.print(*args, **kwargs)  # type: ignore[arg-type]

    def ask(self, prompt: str) -> str:
        self.outputs.append(prompt)
        if not self.inputs:
            raise EOFError(f"No scripted input left for prompt: {prompt!r}")
        return self.inputs.popleft()


@dataclass
class LiveIO:
    console: Console = field(default_factory=Console)

    def print(self, *args: object, **kwargs: object) -> None:
        self.console.print(*args, **kwargs)  # type: ignore[arg-type]

    def ask(self, prompt: str) -> str:
        return self.console.input(prompt)


async def run_host(
    relay_url: str,
    io: LiveIO | ScriptedIO,
    *,
    placement_factory: Callable[[], Placement] | None = None,
    on_invite: Callable[[str], None] | None = None,
    grace_seconds: float = 30.0,
) -> None:
    io.print(f"Connecting to Relay {relay_url} as Host…")
    conn = await MatchConnection.connect(relay_url, grace_seconds=grace_seconds)
    try:
        invite = await conn.create_match()
        if on_invite is not None:
            on_invite(invite)
        io.print(f"Invite (send out-of-band): {invite}")
        io.print("Waiting for Guest to join…")
        await conn.wait_for_player_joined()
        io.print("Guest joined.")

        placement = run_placement(
            io.console, io.ask, placement_factory=placement_factory
        )
        await conn.lock_placement(placement)
        io.print("Placement locked. Waiting for opponent Placement Commitment…")
        await conn.wait_for_opponent_commitment()
        io.print("Both Commitments exchanged. You take the first Shot.")

        await _play_match(conn, placement, io)
    finally:
        await conn.close()


async def run_guest(
    relay_url: str,
    invite: str,
    io: LiveIO | ScriptedIO,
    *,
    placement_factory: Callable[[], Placement] | None = None,
    grace_seconds: float = 30.0,
) -> None:
    io.print(f"Connecting to Relay {relay_url} as Guest…")
    conn = await MatchConnection.connect(relay_url, grace_seconds=grace_seconds)
    try:
        await conn.join_match(invite)
        io.print(f"Joined Match with Invite {invite}.")

        placement = run_placement(
            io.console, io.ask, placement_factory=placement_factory
        )
        await conn.lock_placement(placement)
        io.print("Placement locked. Waiting for opponent Placement Commitment…")
        await conn.wait_for_opponent_commitment()
        io.print("Both Commitments exchanged. Waiting for Host's first Shot…")

        await _play_match(conn, placement, io)
    finally:
        await conn.close()


async def _play_match(
    conn: MatchConnection,
    placement: Placement,
    io: LiveIO | ScriptedIO,
) -> None:
    own_marks: dict[Coordinate, ShotResultKind] = {}
    tracking: dict[Coordinate, ShotResultKind] = {}
    revealed: set[Coordinate] = set()
    verification_ok: bool | None = None

    try:
        while conn.match_end is None:
            render_match_boards(
                io.console, placement, own_marks, tracking, frozenset(revealed)
            )
            if conn.my_turn:
                report = await _take_shot_until_legal(conn, io)
                _apply_outgoing(report, tracking, revealed)
                if report.verification_ok is not None:
                    verification_ok = report.verification_ok
                if report.match_end is not None:
                    break
            else:
                io.print("Waiting for opponent Shot…")
                report = await conn.serve_opponent_shot()
                if report.match_end is not None:
                    break
                io.print(_format_shot_feedback(report, outgoing=False))
                _apply_incoming(report, own_marks)
    except (ConnectionClosed, asyncio.TimeoutError, MatchConnectionError) as exc:
        io.print(f"Connection issue: {exc}")
        end = await conn.wait_for_match_end()
        _announce_end(io, end.outcome, end.winner, verification_ok, conn.role)
        return
    except RevealVerificationError as exc:
        io.print(f"Commitment verification failed: {exc}")
        verification_ok = False
        end = conn.match_end
        if end is None:
            end = await conn.wait_for_match_end()
        _announce_end(io, end.outcome, end.winner, verification_ok, conn.role)
        return

    end = conn.match_end
    if end is None:
        end = await conn.wait_for_match_end()
    _announce_end(io, end.outcome, end.winner, verification_ok, conn.role)


async def _take_shot_until_legal(
    conn: MatchConnection, io: LiveIO | ScriptedIO
) -> ShotReport:
    while True:
        raw = io.ask("Shot (e.g. B7)> ").strip()
        try:
            report = await conn.fire_shot(raw)
            io.print(_format_shot_feedback(report, outgoing=True))
            return report
        except (IllegalShotError, DuplicateShotError, NotYourTurnError) as exc:
            io.print(f"Rejected: {exc}")


def _apply_outgoing(
    report: ShotReport,
    tracking: dict[Coordinate, ShotResultKind],
    revealed: set[Coordinate],
) -> None:
    coord = parse_coordinate(report.coordinate)
    kind: ShotResultKind = report.result  # type: ignore[assignment]
    tracking[coord] = kind
    for cell in report.revealed_cells:
        c = parse_coordinate(cell)
        revealed.add(c)
        tracking[c] = "sunk"


def _apply_incoming(
    report: ShotReport, own_marks: dict[Coordinate, ShotResultKind]
) -> None:
    coord = parse_coordinate(report.coordinate)
    kind: ShotResultKind = report.result  # type: ignore[assignment]
    own_marks[coord] = kind
    if report.result == "sunk":
        for cell in report.revealed_cells:
            own_marks[parse_coordinate(cell)] = "sunk"


def _format_shot_feedback(report: ShotReport, *, outgoing: bool) -> str:
    who = "Your Shot" if outgoing else "Incoming Shot"
    base = f"{who} {report.coordinate}: {report.result}"
    if report.ship:
        base += f" ({report.ship})"
    return base


def _announce_end(
    io: LiveIO | ScriptedIO,
    outcome: MatchOutcome,
    winner: str | None,
    verification_ok: bool | None,
    role: str | None,
) -> None:
    if outcome == MatchOutcome.ABANDONED:
        io.print("Match Abandoned (no Winner).")
    elif outcome == MatchOutcome.WINNER:
        if winner == role:
            io.print("Winner: you.")
        else:
            io.print(f"Winner: {winner}.")
    if verification_ok is True:
        io.print("Commitment verification: OK.")
    elif verification_ok is False:
        io.print("Commitment verification: FAILED.")
    else:
        io.print("Commitment verification: not applicable on this side.")
    io.print("Exiting.")
