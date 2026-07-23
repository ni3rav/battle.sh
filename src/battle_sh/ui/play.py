"""Host and Guest terminal Match play over a Relay."""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TypeVar

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
from battle_sh.ui.aim_flow import run_aim
from battle_sh.ui.boards import own_board_renderable
from battle_sh.ui.clock import Clock, FakeClock, SystemClock, format_elapsed
from battle_sh.ui.keys import KeySource, ScriptedKeySource, TerminalKeySource
from battle_sh.ui.placement_flow import QuitRequested, run_placement
from battle_sh.ui.shell import combat_frame, combat_wait_frame, lobby_frame, wait_frame
from battle_sh.ui.wait_flow import wait_honoring_quit
from rich.console import Console
from rich.live import Live
from websockets.exceptions import ConnectionClosed

T = TypeVar("T")


@dataclass
class ScriptedIO:
    """Injectable line IO for tests — records printed text, feeds scripted inputs.

    ``keys`` and ``clock`` sit beside line ``ask`` so Match UI work can drive
    immediate keys and time without a real TTY.
    """

    inputs: deque[str]
    outputs: list[str] = field(default_factory=list[str])
    console: Console = field(
        default_factory=lambda: Console(record=True, force_terminal=True)
    )
    keys: KeySource = field(default_factory=lambda: ScriptedKeySource([]))
    clock: Clock = field(default_factory=FakeClock)

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
    clock: Clock = field(default_factory=SystemClock)
    keys: KeySource = field(default_factory=TerminalKeySource)

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
        io.print(f"Invite code (share with your opponent): {invite}")

        await _live_wait(
            io,
            conn.wait_for_player_joined(),
            frame=lambda status, spin: lobby_frame(
                role="Host",
                invite=invite,
                status=status or "Waiting for Guest…",
            ),
            initial_status="Waiting for Guest…",
        )
        match_started_at = io.clock.now()
        io.print("Guest joined.")

        placement = _run_placement_with_match_time(
            io,
            role="Host",
            match_started_at=match_started_at,
            placement_factory=placement_factory,
        )
        await conn.lock_placement(placement)

        await _wait_for_opponent_commitment(
            io, conn, "Host", match_started_at, placement
        )
        io.print("Both ready. You fire first.")

        await _play_match(conn, placement, io, role="Host", match_started_at=match_started_at)
    except QuitRequested:
        io.print("Quitting. Match Abandoned for your opponent.")
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
        match_started_at = io.clock.now()
        io.print(f"Joined Match with Invite {invite}.")

        placement = _run_placement_with_match_time(
            io,
            role="Guest",
            match_started_at=match_started_at,
            placement_factory=placement_factory,
        )
        await conn.lock_placement(placement)

        await _wait_for_opponent_commitment(io, conn, "Guest", match_started_at, placement)
        io.print("Both ready. Waiting for Host's first shot…")

        await _play_match(conn, placement, io, role="Guest", match_started_at=match_started_at)
    except QuitRequested:
        io.print("Quitting. Match Abandoned for your opponent.")
    finally:
        await conn.close()


async def _wait_for_opponent_commitment(
    io: LiveIO | ScriptedIO,
    conn: MatchConnection,
    role: str,
    match_started_at: float,
    placement: Placement,
) -> None:
    await _live_wait(
        io,
        conn.wait_for_opponent_commitment(),
        frame=lambda status, spin: wait_frame(
            role=role,
            phase="Waiting for opponent Placement",
            match_time=format_elapsed(io.clock.now() - match_started_at),
            spinner_frame=spin,
            status=status or "Waiting for opponent to lock…",
            board=own_board_renderable(placement, {}),
        ),
        initial_status="Waiting for opponent to lock…",
    )


def _run_placement_with_match_time(
    io: LiveIO | ScriptedIO,
    *,
    role: str,
    match_started_at: float,
    placement_factory: Callable[[], Placement] | None,
) -> Placement:
    def top_info() -> str:
        elapsed = format_elapsed(io.clock.now() - match_started_at)
        return f"{role} · Placement · Match time {elapsed}"

    return run_placement(
        io.keys,
        console=io.console,
        placement_factory=placement_factory,
        top_info=top_info,
        clock=io.clock,
    )


async def _live_wait(
    io: LiveIO | ScriptedIO,
    awaitable: Awaitable[T],
    *,
    frame: Callable[[str, int], object],
    initial_status: str,
) -> T:
    status = initial_status
    spin = 0

    def on_message(text: str) -> None:
        nonlocal status
        status = text

    with Live(
        frame(status, spin),  # type: ignore[arg-type]
        console=io.console,
        auto_refresh=False,
        transient=False,
    ) as live:

        def on_tick() -> None:
            nonlocal spin
            spin += 1
            live.update(frame(status, spin), refresh=True)  # type: ignore[arg-type]

        return await wait_honoring_quit(
            awaitable,
            keys=io.keys,
            clock=io.clock,
            on_message=on_message,
            on_tick=on_tick,
        )


async def _play_match(
    conn: MatchConnection,
    placement: Placement,
    io: LiveIO | ScriptedIO,
    *,
    role: str,
    match_started_at: float,
) -> None:
    own_marks: dict[Coordinate, ShotResultKind] = {}
    tracking: dict[Coordinate, ShotResultKind] = {}
    revealed: set[Coordinate] = set()
    verification_ok: bool | None = None
    last_shot: Coordinate | None = None

    try:
        while conn.match_end is None:
            if conn.my_turn:
                report = await _take_shot_until_legal(
                    conn,
                    io,
                    role=role,
                    match_started_at=match_started_at,
                    placement=placement,
                    own_marks=own_marks,
                    tracking=tracking,
                    revealed=frozenset(revealed),
                    last_shot=last_shot,
                )
                last_shot = parse_coordinate(report.coordinate)
                _apply_outgoing(report, tracking, revealed)
                if report.verification_ok is not None:
                    verification_ok = report.verification_ok
                if report.match_end is not None:
                    break
            else:
                report = await _wait_opponent_shot(
                    conn,
                    io,
                    role=role,
                    match_started_at=match_started_at,
                    placement=placement,
                    own_marks=own_marks,
                    tracking=tracking,
                    revealed=frozenset(revealed),
                )
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
    conn: MatchConnection,
    io: LiveIO | ScriptedIO,
    *,
    role: str,
    match_started_at: float,
    placement: Placement,
    own_marks: dict[Coordinate, ShotResultKind],
    tracking: dict[Coordinate, ShotResultKind],
    revealed: frozenset[Coordinate],
    last_shot: Coordinate | None,
) -> ShotReport:
    fired = frozenset(tracking)

    def frame(aim: Coordinate, status: str) -> object:
        return combat_frame(
            role=role,
            match_time=format_elapsed(io.clock.now() - match_started_at),
            placement=placement,
            own_marks=own_marks,
            tracking=tracking,
            revealed=revealed,
            aim=aim,
            status=status or "Your turn — Aim and fire.",
        )

    while True:
        aim = run_aim(
            io.keys,
            fired=fired,
            start=last_shot,
            clock=io.clock,
            console=io.console,
            frame=frame,
        )
        try:
            report = await conn.fire_shot(str(aim))
            io.print(_format_shot_feedback(report, outgoing=True))
            return report
        except (IllegalShotError, DuplicateShotError, NotYourTurnError) as exc:
            io.print(f"Try again: {exc}")


async def _wait_opponent_shot(
    conn: MatchConnection,
    io: LiveIO | ScriptedIO,
    *,
    role: str,
    match_started_at: float,
    placement: Placement,
    own_marks: dict[Coordinate, ShotResultKind],
    tracking: dict[Coordinate, ShotResultKind],
    revealed: frozenset[Coordinate],
) -> ShotReport:
    return await _live_wait(
        io,
        conn.serve_opponent_shot(),
        frame=lambda status, spin: combat_wait_frame(
            role=role,
            match_time=format_elapsed(io.clock.now() - match_started_at),
            placement=placement,
            own_marks=own_marks,
            tracking=tracking,
            revealed=revealed,
            spinner_frame=spin,
            status=status or "Waiting for opponent…",
        ),
        initial_status="Waiting for opponent…",
    )


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
    cell = report.coordinate
    if outgoing:
        if report.result == "miss":
            return f"You shot {cell} — miss."
        if report.result == "hit":
            ship = f" ({report.ship})" if report.ship else ""
            return f"You shot {cell} — hit{ship}!"
        ship = report.ship or "ship"
        return f"You shot {cell} — sunk their {ship}!"
    if report.result == "miss":
        return f"Opponent shot {cell} — miss."
    if report.result == "hit":
        ship = f" ({report.ship})" if report.ship else ""
        return f"Opponent shot {cell} — hit{ship}!"
    ship = report.ship or "ship"
    return f"Opponent shot {cell} — they sank your {ship}!"


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
            io.print("You win!")
        else:
            io.print(f"Winner: {winner}.")
    if verification_ok is True:
        io.print("Commitment verification: OK.")
    elif verification_ok is False:
        io.print("Commitment verification: FAILED.")
    else:
        io.print("Commitment verification: not applicable on this side.")
    io.print("Exiting.")
