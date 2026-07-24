"""Host and Guest terminal Match play over a Relay."""

from __future__ import annotations

import asyncio
import contextlib
import signal
from collections import deque
from collections.abc import Awaitable, Callable, Generator
from dataclasses import dataclass, field
from typing import TypeVar

from battle_sh.networking.connection import (
    DuplicateShotError,
    IllegalShotError,
    MatchConnection,
    MatchConnectionError,
    MatchEnd,
    NotYourTurnError,
    RevealVerificationError,
    ShotReport,
    close_code_and_reason,
)
from battle_sh.networking.protocol import DEFAULT_GRACE_SECONDS, MatchOutcome
from battle_sh.rules.board import ShotResultKind, parse_coordinate
from battle_sh.rules.placement import (
    STANDARD_FLEET_LENGTHS,
    Coordinate,
    Placement,
)
from battle_sh.ui.aim_flow import run_aim_async
from battle_sh.ui.boards import own_board_renderable
from battle_sh.ui.clock import Clock, FakeClock, SystemClock, format_elapsed
from battle_sh.ui.keys import KeySource, ScriptedKeySource, TerminalKeySource
from battle_sh.ui.placement_flow import QuitRequested, run_placement_async
from battle_sh.ui.shell import (
    CombatBoards,
    MatchStatus,
    combat_frame,
    combat_wait_frame,
    lobby_frame,
    wait_frame,
)
from battle_sh.ui.wait_flow import wait_honoring_quit
from rich.console import Console
from rich.live import Live
from websockets.exceptions import ConnectionClosed

T = TypeVar("T")

_FLEET_SIZE = len(STANDARD_FLEET_LENGTHS)
_TOTAL_CELLS = sum(STANDARD_FLEET_LENGTHS.values())


async def _leave_on_quit(conn: MatchConnection) -> None:
    """Tell the Relay this was intentional so the opponent skips reconnect grace."""
    with contextlib.suppress(ConnectionClosed, OSError, MatchConnectionError):
        await conn.leave_match()


@contextlib.contextmanager
def _sigint_as_key_interrupt(keys: KeySource) -> Generator[None]:
    """Route SIGINT into ``TerminalKeySource.request_interrupt`` (two-step quit).

    Without this, asyncio cancels the Match task on Ctrl+C and ``leave_match``
    never runs — the opponent only sees a disconnect grace window.
    """
    if not isinstance(keys, TerminalKeySource):
        yield
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        yield
        return
    try:
        loop.add_signal_handler(signal.SIGINT, keys.request_interrupt)
    except (NotImplementedError, RuntimeError, ValueError):
        yield
        return
    try:
        yield
    finally:
        with contextlib.suppress(NotImplementedError, RuntimeError, ValueError):
            loop.remove_signal_handler(signal.SIGINT)


def _your_fleet_status(
    placement: Placement, own_marks: dict[Coordinate, ShotResultKind]
) -> tuple[int, tuple[tuple[str, bool], ...]]:
    """Per-ship afloat/sunk state for our own fleet from incoming hit marks."""
    afloat = 0
    fleet: list[tuple[str, bool]] = []
    for name in STANDARD_FLEET_LENGTHS:
        cells = placement.ships[name]
        hits = sum(1 for c in cells if own_marks.get(c) in ("hit", "sunk"))
        is_afloat = hits < len(cells)
        afloat += 1 if is_afloat else 0
        fleet.append((name, is_afloat))
    return afloat, tuple(fleet)


def _count_hits(marks: dict[Coordinate, ShotResultKind]) -> int:
    return sum(1 for kind in marks.values() if kind in ("hit", "sunk"))


def _phase_status(
    conn: MatchConnection, role: str, state: str, *, opponent_present: bool
) -> MatchStatus:
    """Lightweight status (connection/state) for lobby and wait phases."""
    connected = conn.is_connected
    return MatchStatus(
        role=role,
        state=state,
        turn="—",
        your_ships_afloat=_FLEET_SIZE,
        your_ships_total=_FLEET_SIZE,
        enemy_ships_afloat=_FLEET_SIZE,
        enemy_ships_total=_FLEET_SIZE,
        your_hits=0,
        enemy_hits=0,
        total_cells=_TOTAL_CELLS,
        you_connected=connected,
        opponent_connected=connected and opponent_present and conn.opponent_connected,
        synchronized=conn.ready_to_fire,
    )


def _connection_lost_message(exc: ConnectionClosed) -> str:
    _code, reason = close_code_and_reason(exc)
    if "keepalive" in reason.lower():
        return (
            "Connection lost (keepalive timeout). Match Abandoned. Exiting."
        )
    return f"Connection lost: {exc}. Match Abandoned. Exiting."


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


async def _announce_match_end_or_error(
    io: LiveIO | ScriptedIO,
    conn: MatchConnection,
    exc: MatchConnectionError,
    *,
    match_started_at: float | None,
    verification_ok: bool | None = None,
) -> None:
    end = conn.match_end
    if end is not None:
        match_time = (
            format_elapsed(io.clock.now() - match_started_at)
            if match_started_at is not None
            else "0:00"
        )
        _announce_end(io, end, verification_ok, conn.role, match_time)
        return
    io.print(f"Match error: {exc.message}. Exiting.")


async def run_host(
    relay_url: str,
    io: LiveIO | ScriptedIO,
    *,
    placement_factory: Callable[[], Placement] | None = None,
    on_invite: Callable[[str], None] | None = None,
    grace_seconds: float = DEFAULT_GRACE_SECONDS,
) -> None:
    io.print(f"Connecting to Relay {relay_url} as Host…")
    try:
        conn = await MatchConnection.connect(relay_url, grace_seconds=grace_seconds)
    except OSError as exc:
        io.print(f"Could not connect to Relay {relay_url}: {exc}")
        return
    match_started_at: float | None = None
    try:
        with _sigint_as_key_interrupt(io.keys):
            invite = await conn.create_match()
            if on_invite is not None:
                on_invite(invite)
            io.print(f"Invite (share with your opponent): {invite}")

            await _live_wait(
                io,
                conn.wait_for_player_joined(),
                frame=lambda status, spin: lobby_frame(
                    role="Host",
                    invite=invite,
                    status=status or "Waiting for Guest…",
                    status_info=_phase_status(
                        conn, "Host", "Lobby", opponent_present=False
                    ),
                ),
                initial_status="Waiting for Guest…",
                conn=conn,
            )
            match_started_at = io.clock.now()
            io.print("Guest joined.")

            placement = await _run_placement_with_match_time(
                io,
                role="Host",
                match_started_at=match_started_at,
                placement_factory=placement_factory,
                conn=conn,
            )
            await conn.lock_placement(placement)

            await _wait_for_opponent_commitment(
                io, conn, "Host", match_started_at, placement
            )
            io.print("Both ready. You fire first.")

            await _play_match(
                conn, placement, io, role="Host", match_started_at=match_started_at
            )
    except QuitRequested:
        await _leave_on_quit(conn)
        io.print("Match Abandoned. Exiting.")
    except KeyboardInterrupt:
        await _leave_on_quit(conn)
        io.print("Match Abandoned. Exiting.")
    except asyncio.CancelledError:
        # Platforms without add_signal_handler (or a stray cancel) still must
        # leave so the opponent skips reconnect grace.
        await _leave_on_quit(conn)
        raise
    except ConnectionClosed as exc:
        io.print(_connection_lost_message(exc))
    except MatchConnectionError as exc:
        await _announce_match_end_or_error(
            io, conn, exc, match_started_at=match_started_at
        )
    finally:
        await conn.close()


async def run_guest(
    relay_url: str,
    invite: str,
    io: LiveIO | ScriptedIO,
    *,
    placement_factory: Callable[[], Placement] | None = None,
    grace_seconds: float = DEFAULT_GRACE_SECONDS,
) -> None:
    io.print(f"Connecting to Relay {relay_url} as Guest…")
    try:
        conn = await MatchConnection.connect(relay_url, grace_seconds=grace_seconds)
    except OSError as exc:
        io.print(f"Could not connect to Relay {relay_url}: {exc}")
        return
    match_started_at: float | None = None
    try:
        with _sigint_as_key_interrupt(io.keys):
            await conn.join_match(invite)
            match_started_at = io.clock.now()
            io.print(f"Joined Match with Invite {invite}.")

            placement = await _run_placement_with_match_time(
                io,
                role="Guest",
                match_started_at=match_started_at,
                placement_factory=placement_factory,
                conn=conn,
            )
            await conn.lock_placement(placement)

            await _wait_for_opponent_commitment(
                io, conn, "Guest", match_started_at, placement
            )
            io.print("Both ready. Waiting for Host's first shot…")

            await _play_match(
                conn, placement, io, role="Guest", match_started_at=match_started_at
            )
    except QuitRequested:
        await _leave_on_quit(conn)
        io.print("Match Abandoned. Exiting.")
    except KeyboardInterrupt:
        await _leave_on_quit(conn)
        io.print("Match Abandoned. Exiting.")
    except asyncio.CancelledError:
        await _leave_on_quit(conn)
        raise
    except ConnectionClosed as exc:
        io.print(_connection_lost_message(exc))
    except MatchConnectionError as exc:
        await _announce_match_end_or_error(
            io, conn, exc, match_started_at=match_started_at
        )
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
            status_info=_phase_status(
                conn, role, "Placement — waiting for opponent", opponent_present=True
            ),
        ),
        initial_status="Waiting for opponent to lock…",
        conn=conn,
    )


async def _run_placement_with_match_time(
    io: LiveIO | ScriptedIO,
    *,
    role: str,
    match_started_at: float,
    placement_factory: Callable[[], Placement] | None,
    conn: MatchConnection,
) -> Placement:
    def top_info() -> str:
        elapsed = format_elapsed(io.clock.now() - match_started_at)
        return f"{role} · Placement · Match time {elapsed}"

    async def watch_match_end() -> None:
        end = await conn.poll_incoming(timeout=0.05)
        if end is not None:
            raise MatchConnectionError(
                "match_ended", "Match ended during Placement"
            )

    # Read keys off the event loop so the WebSocket keepalive keeps answering
    # pings while the Player arranges ships (rendering stays on the loop thread).
    return await run_placement_async(
        io.keys,
        console=io.console,
        placement_factory=placement_factory,
        top_info=top_info,
        clock=io.clock,
        async_on_tick=watch_match_end,
    )


async def _live_wait(
    io: LiveIO | ScriptedIO,
    awaitable: Awaitable[T],
    *,
    frame: Callable[[str, int], object],
    initial_status: str,
    conn: MatchConnection | None = None,
) -> T:
    status = initial_status
    spin = 0

    def on_message(text: str) -> None:
        nonlocal status
        status = text

    if conn is not None:
        conn.set_status_listener(on_message)

    with Live(
        frame(status, spin),  # type: ignore[arg-type]
        console=io.console,
        auto_refresh=False,
        transient=False,
    ) as live:

        def on_tick() -> None:
            nonlocal spin, status
            spin += 1
            if conn is not None:
                reconnect = conn.opponent_reconnect_status()
                if reconnect is not None:
                    status = reconnect
            live.update(frame(status, spin), refresh=True)  # type: ignore[arg-type]

        try:
            return await wait_honoring_quit(
                awaitable,
                keys=io.keys,
                clock=io.clock,
                on_message=on_message,
                on_tick=on_tick,
            )
        finally:
            if conn is not None:
                conn.set_status_listener(None)


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
    enemy_sunk_ships: list[str] = []
    verification_ok: bool | None = None
    last_shot: Coordinate | None = None
    frozen_match_time: str | None = None
    status_message = ""

    def boards() -> CombatBoards:
        return CombatBoards(
            placement=placement,
            own_marks=own_marks,
            tracking=tracking,
            revealed=frozenset(revealed),
        )

    def match_status() -> MatchStatus:
        your_afloat, your_fleet = _your_fleet_status(placement, own_marks)
        over = conn.match_end is not None
        connected = conn.is_connected
        return MatchStatus(
            role=role,
            state="Match over" if over else "Combat",
            turn="You" if conn.my_turn else "Opponent",
            your_ships_afloat=your_afloat,
            your_ships_total=_FLEET_SIZE,
            enemy_ships_afloat=_FLEET_SIZE - len(enemy_sunk_ships),
            enemy_ships_total=_FLEET_SIZE,
            your_hits=_count_hits(tracking),
            enemy_hits=_count_hits(own_marks),
            total_cells=_TOTAL_CELLS,
            you_connected=connected,
            opponent_connected=connected and not over and conn.opponent_connected,
            synchronized=conn.ready_to_fire,
            your_fleet=your_fleet,
            enemy_sunk=tuple(enemy_sunk_ships),
        )

    def elapsed() -> str:
        return format_elapsed(io.clock.now() - match_started_at)

    def freeze_match_time() -> str:
        nonlocal frozen_match_time
        if frozen_match_time is None:
            frozen_match_time = elapsed()
        return frozen_match_time

    try:
        while conn.match_end is None:
            if conn.my_turn:
                report = await _take_shot_until_legal(
                    conn,
                    io,
                    role=role,
                    boards=boards(),
                    elapsed=elapsed,
                    last_shot=last_shot,
                    status_info=match_status(),
                    initial_status=status_message or "Your turn — Aim and fire.",
                )
                if report.match_end is not None:
                    freeze_match_time()
                    break
                last_shot = parse_coordinate(report.coordinate)
                _apply_outgoing(report, tracking, revealed)
                if report.result == "sunk" and report.ship:
                    enemy_sunk_ships.append(report.ship)
                if report.verification_ok is not None:
                    verification_ok = report.verification_ok
                status_message = _format_shot_feedback(report, outgoing=True)
            else:
                wait_status = status_message or "Waiting for opponent…"
                report = await _live_wait(
                    io,
                    conn.serve_opponent_shot(),
                    frame=lambda status, spin, _ws=wait_status: combat_wait_frame(
                        role=role,
                        match_time=elapsed(),
                        boards=boards(),
                        spinner_frame=spin,
                        status=status or _ws,
                        status_info=match_status(),
                    ),
                    initial_status=wait_status,
                    conn=conn,
                )
                if report.match_end is not None:
                    freeze_match_time()
                    break
                status_message = _format_shot_feedback(report, outgoing=False)
                _apply_incoming(report, own_marks)
    except (ConnectionClosed, asyncio.TimeoutError, MatchConnectionError) as exc:
        io.print(f"Connection issue: {exc}")
        match_time = freeze_match_time()
        end = await conn.wait_for_match_end()
        _announce_end(io, end, verification_ok, conn.role, match_time)
        return
    except RevealVerificationError as exc:
        io.print(f"Commitment verification failed: {exc}")
        verification_ok = False
        match_time = freeze_match_time()
        end = conn.match_end
        if end is None:
            end = await conn.wait_for_match_end()
        _announce_end(io, end, verification_ok, conn.role, match_time)
        return

    match_time = freeze_match_time()
    end = conn.match_end
    if end is None:
        end = await conn.wait_for_match_end()
    _announce_end(io, end, verification_ok, conn.role, match_time)


async def _take_shot_until_legal(
    conn: MatchConnection,
    io: LiveIO | ScriptedIO,
    *,
    role: str,
    boards: CombatBoards,
    elapsed: Callable[[], str],
    last_shot: Coordinate | None,
    status_info: MatchStatus | None = None,
    initial_status: str = "Your turn — Aim and fire.",
) -> ShotReport:
    fired = frozenset(boards.tracking)

    def frame(aim: Coordinate, status: str) -> object:
        return combat_frame(
            role=role,
            match_time=elapsed(),
            boards=boards,
            aim=aim,
            status=status or initial_status,
            status_info=status_info,
        )

    async def watch_match_end() -> None:
        end = await conn.poll_incoming(timeout=0.05)
        if end is not None:
            raise MatchConnectionError(
                "match_ended", "Match ended while Aiming"
            )

    while True:
        # Read keys off the event loop so the WebSocket keepalive keeps answering
        # pings while the Player takes aim (rendering stays on the loop thread).
        # poll_incoming on each tick so opponent leave Abandons without waiting
        # for a fire key.
        try:
            aim = await run_aim_async(
                io.keys,
                fired=fired,
                start=last_shot,
                clock=io.clock,
                console=io.console,
                frame=frame,
                async_on_tick=watch_match_end,
            )
        except MatchConnectionError:
            end = conn.match_end
            if end is None:
                raise
            return ShotReport(
                result="miss",
                coordinate="",
                match_end=end,
            )
        try:
            return await conn.fire_shot(str(aim))
        except (IllegalShotError, DuplicateShotError, NotYourTurnError) as exc:
            io.print(f"Try again: {exc}")


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
    end: MatchEnd,
    verification_ok: bool | None,
    role: str | None,
    match_time: str,
) -> None:
    if end.outcome == MatchOutcome.ABANDONED:
        io.print("Match Abandoned. Exiting.")
    elif end.outcome == MatchOutcome.WINNER:
        if end.winner == role:
            io.print("You win!")
        else:
            io.print(f"Winner: {end.winner}.")
    io.print(f"Match time {match_time}")
    if verification_ok is True:
        io.print("Commitment verification: OK.")
    elif verification_ok is False:
        io.print("Commitment verification: FAILED.")
    else:
        io.print("Commitment verification: not applicable on this side.")
    if end.outcome != MatchOutcome.ABANDONED:
        io.print("Exiting.")
