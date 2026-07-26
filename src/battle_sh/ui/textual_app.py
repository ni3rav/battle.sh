"""Textual player app: opening, Host/Join lobby, Placement, Combat, QuitArm."""

from __future__ import annotations

import contextlib
from collections.abc import Callable
from typing import Literal, cast

from rich.console import Console, Group
from rich.text import Text
from textual import events
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Input, OptionList, Static
from textual.widgets.option_list import Option
from textual.worker import Worker, WorkerCancelled, WorkerState

from battle_sh.networking.connection import (
    DuplicateShotError,
    IllegalShotError,
    MatchConnection,
    MatchConnectionError,
    MatchEnd,
    NotYourTurnError,
    RevealVerificationError,
)
from battle_sh.networking.protocol import MatchOutcome, Role
from battle_sh.rules.board import ShotResultKind, parse_coordinate
from battle_sh.rules.placement import Coordinate, Placement, random_placement
from battle_sh.ui.aim_flow import apply_aim_key, initial_aim
from battle_sh.ui.boards import own_board_renderable, tracking_board_renderable
from battle_sh.ui.clock import Clock, SystemClock, format_elapsed
from battle_sh.ui.keys import Key
from battle_sh.ui.placement_flow import apply_placement_key
from battle_sh.ui.play import (
    apply_incoming_shot,
    apply_outgoing_shot,
    combat_match_status,
    format_shot_feedback,
)
from battle_sh.ui.quit_arm import QUIT_WARN, QuitArm
from battle_sh.ui.shell import (
    AIM_CONTROLS,
    PLACEMENT_CONTROLS,
    SPINNER,
    WAIT_CONTROLS,
    MatchStatus,
    connection_line,
    sidebar_scoreboard_renderable,
)

BANNER = (
    "░██                      ░██       ░██    ░██                           ░██        \n"
    "░██                      ░██       ░██    ░██                           ░██        \n"
    "░████████   ░██████   ░████████ ░████████ ░██  ░███████       ░███████  ░████████  \n"
    "░██    ░██       ░██     ░██       ░██    ░██ ░██    ░██     ░██        ░██    ░██ \n"
    "░██    ░██  ░███████     ░██       ░██    ░██ ░█████████      ░███████  ░██    ░██ \n"
    "░███   ░██ ░██   ░██     ░██       ░██    ░██ ░██                   ░██ ░██    ░██ \n"
    "░██░█████   ░█████░██     ░████     ░████ ░██  ░███████  ░██  ░███████  ░██    ░██ "
)

OPTION_HOST = "host"
OPTION_JOIN = "join"
OPTION_EXIT = "exit"
OPTION_BACK = "back"
OPTION_SUBMIT_JOIN = "submit_join"

_PlacementPhase = Literal["editing", "waiting"]
_CombatPhase = Literal["aiming", "waiting"]


class OpeningScreen(Screen[None]):
    """ASCII-branded opening menu: Host, Join, Exit."""

    def compose(self) -> ComposeResult:
        with Vertical(id="opening"):
            yield Static(BANNER, id="banner")
            yield OptionList(
                Option("Host", id=OPTION_HOST),
                Option("Join", id=OPTION_JOIN),
                Option("Exit", id=OPTION_EXIT),
                id="menu",
            )
            yield Static("", id="status")

    def on_mount(self) -> None:
        self.query_one("#menu", OptionList).focus()

    def set_status(self, message: str) -> None:
        self.query_one("#status", Static).update(message)

    def on_option_list_option_selected(
        self, event: OptionList.OptionSelected
    ) -> None:
        option_id = event.option.id
        app = _battle_app(self)
        if option_id == OPTION_EXIT:
            app.exit()
            return
        if option_id == OPTION_HOST:
            app.push_screen(HostWaitingScreen())
            return
        if option_id == OPTION_JOIN:
            app.push_screen(JoinScreen())
            return


class HostWaitingScreen(Screen[None]):
    """Host lobby: create Match, show Invite, wait for Guest; Back cancels."""

    BINDINGS = [
        Binding("escape", "back", "Back", show=False),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._invite: str | None = None
        self._conn: MatchConnection | None = None
        self._worker: Worker[None] | None = None

    def compose(self) -> ComposeResult:
        with Vertical(id="host-waiting"):
            yield Static("Host · Lobby — waiting for Guest", id="headline")
            yield Static("Creating Match…", id="invite")
            yield Static(
                "Share the Invite with your opponent.\n"
                "Match time starts when they join.",
                id="body",
            )
            yield OptionList(Option("Back", id=OPTION_BACK), id="menu")
            yield Static("", id="status")

    def on_mount(self) -> None:
        self.query_one("#menu", OptionList).focus()
        self._worker = self.run_worker(
            self._host_lobby(),
            name="host_lobby",
            group="lobby",
            exclusive=True,
            exit_on_error=False,
        )

    def displayed_invite(self) -> str | None:
        """Invite phrase currently shown on the waiting screen, if any."""
        return self._invite

    def set_status(self, message: str) -> None:
        self.query_one("#status", Static).update(message)

    async def _host_lobby(self) -> None:
        app = _battle_app(self)
        try:
            conn = await MatchConnection.connect(
                app.relay_url, grace_seconds=app.grace_seconds
            )
            self._conn = conn
            invite = await conn.create_match()
            self._invite = invite
            self.query_one("#invite", Static).update(f"Invite: {invite}")
            self.set_status("Waiting for Guest…")
            await conn.wait_for_player_joined()
            self._conn = None
            app.show_placement(role="host", conn=conn)
        except WorkerCancelled:
            return
        except (MatchConnectionError, OSError, ConnectionError) as exc:
            self.set_status(f"Could not Host: {exc}")
            return

    def on_option_list_option_selected(
        self, event: OptionList.OptionSelected
    ) -> None:
        if event.option.id == OPTION_BACK:
            self.action_back()

    def action_back(self) -> None:
        self.run_worker(
            self._cancel_and_leave(),
            name="host_back",
            group="lobby",
            exclusive=True,
            exit_on_error=False,
        )

    async def _cancel_and_leave(self) -> None:
        if self._worker is not None and self._worker.state == WorkerState.RUNNING:
            self._worker.cancel()
        conn = self._conn
        self._conn = None
        if conn is not None and not await _leave_and_close(conn):
            self._conn = conn
            self.set_status("Could not cancel Match. Try Back again.")
            return
        _battle_app(self).pop_screen()


class JoinScreen(Screen[None]):
    """Guest lobby: paste Invite in-app; Back returns to opening."""

    BINDINGS = [
        Binding("escape", "back", "Back", show=False),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._conn: MatchConnection | None = None

    def compose(self) -> ComposeResult:
        with Vertical(id="join"):
            yield Static("Join · paste Invite", id="headline")
            yield Input(placeholder="Invite phrase", id="invite-input")
            yield OptionList(
                Option("Join", id=OPTION_SUBMIT_JOIN),
                Option("Back", id=OPTION_BACK),
                id="menu",
            )
            yield Static("", id="status")

    def on_mount(self) -> None:
        self.query_one("#invite-input", Input).focus()

    def set_status(self, message: str) -> None:
        self.query_one("#status", Static).update(message)

    def status_text(self) -> str:
        """Human-readable status line shown on the Join screen."""
        return str(self.query_one("#status", Static).content)

    def on_option_list_option_selected(
        self, event: OptionList.OptionSelected
    ) -> None:
        if event.option.id == OPTION_BACK:
            self.action_back()
            return
        if event.option.id == OPTION_SUBMIT_JOIN:
            self._submit_join()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "invite-input":
            self._submit_join()

    def _submit_join(self) -> None:
        invite = self.query_one("#invite-input", Input).value.strip()
        if not invite:
            self.set_status("Invite is required. Paste an Invite or go Back.")
            return
        self.run_worker(
            self._join_lobby(invite),
            name="join_lobby",
            group="lobby",
            exclusive=True,
            exit_on_error=False,
        )

    async def _join_lobby(self, invite: str) -> None:
        app = _battle_app(self)
        self.set_status("Connecting…")
        try:
            conn = await MatchConnection.connect(
                app.relay_url, grace_seconds=app.grace_seconds
            )
            self._conn = conn
            await conn.join_match(invite)
            self._conn = None
            app.show_placement(role="guest", conn=conn)
        except (MatchConnectionError, OSError, ConnectionError) as exc:
            if self._conn is not None:
                with contextlib.suppress(OSError, ConnectionError):
                    await self._conn.close()
                self._conn = None
            message = (
                exc.message
                if isinstance(exc, MatchConnectionError)
                else str(exc)
            )
            self.set_status(f"Could not Join: {message}")

    def action_back(self) -> None:
        self.run_worker(
            self._leave_and_pop(),
            name="join_back",
            group="lobby",
            exclusive=True,
            exit_on_error=False,
        )

    async def _leave_and_pop(self) -> None:
        conn = self._conn
        self._conn = None
        if conn is not None and not await _leave_and_close(conn):
            self._conn = conn
            self.set_status("Could not leave. Try Back again.")
            return
        _battle_app(self).pop_screen()


class PlacementScreen(Screen[None]):
    """Placement phase: three-band chrome, exact keys, lock → wait for opponent."""

    # No Back / Escape — mid-Match Abandon is two-step Ctrl+C only.
    DEFAULT_CSS = """
    PlacementScreen {
        layout: vertical;
    }
    #info {
        height: 3;
        padding: 0 1;
    }
    #middle {
        height: 1fr;
        layout: horizontal;
    }
    #board-panel {
        width: 1fr;
        padding: 0 1;
    }
    #controls {
        width: 34;
        padding: 0 1;
    }
    #status {
        height: 3;
        padding: 0 1;
    }
    """

    def __init__(
        self,
        *,
        role: Role,
        conn: MatchConnection,
        match_started_at: float,
        placement_factory: Callable[[], Placement],
    ) -> None:
        super().__init__()
        self.role: Role = role
        self.conn = conn
        self._match_started_at = match_started_at
        self._factory = placement_factory
        self._placement = placement_factory()
        self._selected: str | None = None
        self._phase: _PlacementPhase = "editing"
        self._spin = 0
        self._watch_worker: Worker[None] | None = None

    def compose(self) -> ComposeResult:
        label = "Host" if self.role == "host" else "Guest"
        with Vertical(id="placement"):
            yield Static(
                f"{label} · Placement · Match time 0:00",
                id="info",
            )
            with Horizontal(id="middle"):
                with Vertical(id="board-panel"):
                    yield Static(
                        own_board_renderable(self._placement, {}),
                        id="board",
                    )
                    yield Static(
                        "No ship selected — press 1-5 or tab.",
                        id="selected-line",
                    )
                yield Static(
                    Text.from_markup(PLACEMENT_CONTROLS),
                    id="controls",
                )
            yield Static(" ", id="status")

    def on_mount(self) -> None:
        self._refresh_info()
        self.set_interval(0.25, self._on_tick)
        self._watch_worker = self.run_worker(
            self._watch_match_end(),
            name="placement_watch",
            group="placement",
            exclusive=False,
            exit_on_error=False,
        )

    def info_text(self) -> str:
        """Info-band text currently shown (Match time / wait headline)."""
        return str(self.query_one("#info", Static).content)

    def controls_text(self) -> str:
        """Controls-band text currently shown."""
        return str(self.query_one("#controls", Static).content)

    def status_text(self) -> str:
        """Status-band text currently shown."""
        return str(self.query_one("#status", Static).content)

    def board_text(self) -> str:
        """Plain-text export of the board widget's current renderable."""
        content = self.query_one("#board", Static).content
        console = Console(record=True, width=80, force_terminal=True)
        console.print(content)  # type: ignore[arg-type]
        return console.export_text()

    def set_status(self, message: str) -> None:
        self.query_one("#status", Static).update(message or " ")

    def _refresh_info(self) -> None:
        """Refresh the info band Match time (and wait spinner when waiting)."""
        app = _battle_app(self)
        elapsed = format_elapsed(app.clock.now() - self._match_started_at)
        label = "Host" if self.role == "host" else "Guest"
        if self._phase == "waiting":
            spin = SPINNER[self._spin % len(SPINNER)]
            text = (
                f"{label} · Waiting for opponent Placement · "
                f"Match time {elapsed}  {spin}"
            )
        else:
            text = f"{label} · Placement · Match time {elapsed}"
        self.query_one("#info", Static).update(text)

    def _on_tick(self) -> None:
        app = _battle_app(self)
        app.quit_arm.expire_if_due()
        if self._phase == "waiting":
            self._spin += 1
        self._refresh_info()

    def _refresh_board(self) -> None:
        self.query_one("#board", Static).update(
            own_board_renderable(self._placement, {}, selected=self._selected)
        )
        selected_line = (
            f"Selected: {self._selected}"
            if self._selected
            else "No ship selected — press 1-5 or tab."
        )
        self.query_one("#selected-line", Static).update(selected_line)

    def _enter_waiting(self) -> None:
        self._phase = "waiting"
        self.query_one("#controls", Static).update(Text.from_markup(WAIT_CONTROLS))
        self.set_status("Waiting for opponent to lock…")
        self._refresh_info()

    def on_key(self, event: events.Key) -> None:
        if self._phase == "waiting":
            # Wait honors only Ctrl+C (app binding); ignore Placement/Aim keys.
            return
        if event.key in {"ctrl+c", "ctrl+q"}:
            return
        key = Key(event.key)
        placement, selected, action, message = apply_placement_key(
            key,
            self._placement,
            self._selected,
            factory=self._factory,
            arm=None,  # Ctrl+C is handled by the app QuitArm binding
        )
        self._placement = placement
        self._selected = selected
        if message is not None:
            self.set_status(message)
        self._refresh_board()
        if action == "lock":
            event.stop()
            self.run_worker(
                self._lock_and_wait(),
                name="placement_lock",
                group="placement",
                exclusive=True,
                exit_on_error=False,
            )

    async def _lock_and_wait(self) -> None:
        if self._watch_worker is not None and self._watch_worker.state == WorkerState.RUNNING:
            self._watch_worker.cancel()
            self._watch_worker = None
        try:
            await self.conn.lock_placement(self._placement)
        except (MatchConnectionError, OSError, ConnectionError) as exc:
            self.set_status(f"Could not lock Placement: {exc}")
            # Stay in editing — resume watching for opponent Abandon.
            self._watch_worker = self.run_worker(
                self._watch_match_end(),
                name="placement_watch",
                group="placement",
                exclusive=False,
                exit_on_error=False,
            )
            return
        self._enter_waiting()
        try:
            await self.conn.wait_for_opponent_commitment()
        except WorkerCancelled:
            return
        except MatchConnectionError as exc:
            end = self.conn.match_end
            if end is not None:
                self.set_status(f"Match {end.outcome}.")
            else:
                self.set_status(f"Match ended: {exc.message}")
            await self._close_and_return_to_opening()
            return
        except (OSError, ConnectionError) as exc:
            self.set_status(f"Connection lost: {exc}")
            await self._close_and_return_to_opening()
            return
        _battle_app(self).show_combat(
            role=self.role,
            conn=self.conn,
            placement=self._placement,
            match_started_at=self._match_started_at,
        )

    async def _watch_match_end(self) -> None:
        """While editing, notice an opponent Abandon without blocking keys."""
        try:
            while self._phase == "editing":
                end = await self.conn.poll_incoming(timeout=0.05)
                if end is not None:
                    self.set_status(f"Match {end.outcome}.")
                    await self._close_and_return_to_opening()
                    return
        except WorkerCancelled:
            return
        except (MatchConnectionError, OSError, ConnectionError):
            return

    async def confirm_quit(self) -> None:
        """Confirmed two-step Ctrl+C: leave_match so the opponent Abandons now."""
        if self._watch_worker is not None and self._watch_worker.state == WorkerState.RUNNING:
            self._watch_worker.cancel()
            self._watch_worker = None
        await _leave_and_close(self.conn)
        await self._return_to_opening()

    async def _close_and_return_to_opening(self) -> None:
        with contextlib.suppress(OSError, ConnectionError):
            await self.conn.close()
        await self._return_to_opening()

    async def _return_to_opening(self) -> None:
        _pop_to_opening(_battle_app(self))


class CombatScreen(Screen[None]):
    """Combat phase: Aim / off-turn wait, exact keys, boards + scoreboard."""

    DEFAULT_CSS = """
    CombatScreen {
        layout: vertical;
    }
    #info {
        height: 4;
        padding: 0 1;
    }
    #middle {
        height: 1fr;
        layout: horizontal;
    }
    #board {
        width: 1fr;
        padding: 0 1;
    }
    #controls {
        width: 34;
        padding: 0 1;
    }
    #status {
        height: 3;
        padding: 0 1;
    }
    """

    def __init__(
        self,
        *,
        role: Role,
        conn: MatchConnection,
        placement: Placement,
        match_started_at: float,
    ) -> None:
        super().__init__()
        self.role: Role = role
        self.conn = conn
        self._placement = placement
        self._match_started_at = match_started_at
        self._own_marks: dict[Coordinate, ShotResultKind] = {}
        self._tracking: dict[Coordinate, ShotResultKind] = {}
        self._revealed: set[Coordinate] = set()
        self._enemy_sunk: list[str] = []
        self._last_shot: Coordinate | None = None
        self._aim = initial_aim(None, frozenset())
        self._phase: _CombatPhase = "aiming" if conn.my_turn else "waiting"
        self._spin = 0
        self._status = (
            "Your turn — Aim and fire." if conn.my_turn else "Waiting for opponent…"
        )
        self._frozen_match_time: str | None = None
        self._busy = False
        self._action_worker: Worker[None] | None = None
        self._watch_worker: Worker[None] | None = None

    def compose(self) -> ComposeResult:
        label = "Host" if self.role == "host" else "Guest"
        with Vertical(id="combat"):
            yield Static(f"{label} · Aim · Match time 0:00", id="info")
            with Horizontal(id="middle"):
                yield Static("", id="board")
                yield Static(Text.from_markup(AIM_CONTROLS), id="controls")
            yield Static(" ", id="status")

    def on_mount(self) -> None:
        self._refresh_all()
        self.set_interval(0.25, self._on_tick)
        if self._phase == "waiting":
            self._action_worker = self.run_worker(
                self._wait_for_opponent_shot(),
                name="combat_wait",
                group="combat",
                exclusive=True,
                exit_on_error=False,
            )
        else:
            self._start_aim_watch()

    def _cancel_watch(self) -> None:
        if self._watch_worker is not None and self._watch_worker.state == WorkerState.RUNNING:
            self._watch_worker.cancel()
        self._watch_worker = None

    def _start_aim_watch(self) -> None:
        self._cancel_watch()
        self._watch_worker = self.run_worker(
            self._watch_match_end_while_aiming(),
            name="combat_aim_watch",
            group="combat_watch",
            exclusive=False,
            exit_on_error=False,
        )

    def info_text(self) -> str:
        return _static_plain(self.query_one("#info", Static), width=100)

    def controls_text(self) -> str:
        return _static_plain(self.query_one("#controls", Static), width=40)

    def status_text(self) -> str:
        return str(self.query_one("#status", Static).content)

    def board_text(self) -> str:
        return _static_plain(self.query_one("#board", Static), width=80)

    def set_status(self, message: str) -> None:
        self._status = message or " "
        self._refresh_status()

    def _role_label(self) -> str:
        return "Host" if self.role == "host" else "Guest"

    def _elapsed(self) -> str:
        if self._frozen_match_time is not None:
            return self._frozen_match_time
        app = _battle_app(self)
        return format_elapsed(app.clock.now() - self._match_started_at)

    def _freeze_match_time(self) -> str:
        if self._frozen_match_time is None:
            self._frozen_match_time = self._elapsed()
        return self._frozen_match_time

    def _match_status(self) -> MatchStatus:
        return combat_match_status(
            conn=self.conn,
            role=self._role_label(),
            placement=self._placement,
            own_marks=self._own_marks,
            tracking=self._tracking,
            enemy_sunk_ships=self._enemy_sunk,
        )

    def _refresh_all(self) -> None:
        self._refresh_info()
        self._refresh_board()
        self._refresh_controls()
        self._refresh_status()

    def _refresh_status(self) -> None:
        # Match combat_wait_frame: spinner lives on the status line while waiting.
        if self._phase == "waiting":
            spin = SPINNER[self._spin % len(SPINNER)]
            text = f"{spin} {self._status}" if self._status.strip() else spin
        else:
            text = self._status or " "
        self.query_one("#status", Static).update(text)

    def _refresh_info(self) -> None:
        label = self._role_label()
        elapsed = self._elapsed()
        status = self._match_status()
        if self._phase == "waiting":
            headline = f"{label} · Waiting · Match time {elapsed}"
        else:
            headline = f"{label} · Aim · Match time {elapsed}"
        self.query_one("#info", Static).update(
            Group(Text(headline), Text.from_markup(connection_line(status)))
        )

    def _refresh_board(self) -> None:
        aim = self._aim if self._phase == "aiming" else None
        self.query_one("#board", Static).update(
            Group(
                own_board_renderable(self._placement, self._own_marks),
                Text(""),
                tracking_board_renderable(
                    self._tracking, frozenset(self._revealed), aim=aim
                ),
            )
        )

    def _refresh_controls(self) -> None:
        controls = AIM_CONTROLS if self._phase == "aiming" else WAIT_CONTROLS
        self.query_one("#controls", Static).update(
            Group(
                Text.from_markup(controls),
                Text(""),
                sidebar_scoreboard_renderable(self._match_status()),
            )
        )

    def _on_tick(self) -> None:
        app = _battle_app(self)
        app.quit_arm.expire_if_due()
        if self._phase == "waiting":
            self._spin += 1
            self._refresh_status()
        self._refresh_info()

    def on_key(self, event: events.Key) -> None:
        if self._phase != "aiming" or self._busy:
            return
        if event.key in {"ctrl+c", "ctrl+q"}:
            return
        key = Key(event.key)
        fired = frozenset(self._tracking)
        aim, message, action = apply_aim_key(
            key, self._aim, self._status, fired=fired, arm=None
        )
        self._aim = aim
        if message:
            self.set_status(message)
        self._refresh_board()
        if action == "fire":
            event.stop()
            self._busy = True
            self._cancel_watch()
            self._action_worker = self.run_worker(
                self._fire(aim),
                name="combat_fire",
                group="combat",
                exclusive=True,
                exit_on_error=False,
            )

    async def _fire(self, aim: Coordinate) -> None:
        try:
            report = await self.conn.fire_shot(str(aim))
        except (IllegalShotError, DuplicateShotError, NotYourTurnError) as exc:
            self.set_status(f"Try again: {exc}")
            self._busy = False
            self._start_aim_watch()
            return
        except (MatchConnectionError, OSError, ConnectionError, RevealVerificationError) as exc:
            await self._end_from_error(exc)
            return
        apply_outgoing_shot(report, self._tracking, self._revealed)
        if report.result == "sunk" and report.ship:
            self._enemy_sunk.append(report.ship)
        self._last_shot = parse_coordinate(report.coordinate)
        self.set_status(format_shot_feedback(report, outgoing=True))
        if report.match_end is not None:
            await self._show_match_end(report.match_end)
            return
        self._phase = "waiting"
        self._busy = False
        self._refresh_all()
        self._action_worker = self.run_worker(
            self._wait_for_opponent_shot(),
            name="combat_wait",
            group="combat",
            exclusive=True,
            exit_on_error=False,
        )

    async def _wait_for_opponent_shot(self) -> None:
        try:
            report = await self.conn.serve_opponent_shot()
        except WorkerCancelled:
            return
        except (MatchConnectionError, OSError, ConnectionError, RevealVerificationError) as exc:
            await self._end_from_error(exc)
            return
        if report.match_end is not None and not report.coordinate:
            await self._show_match_end(report.match_end)
            return
        if report.coordinate:
            apply_incoming_shot(report, self._own_marks)
            self.set_status(format_shot_feedback(report, outgoing=False))
        if report.match_end is not None:
            await self._show_match_end(report.match_end)
            return
        self._aim = initial_aim(self._last_shot, frozenset(self._tracking))
        self._phase = "aiming"
        self._busy = False
        if not self._status or self._status.startswith("Waiting"):
            self.set_status("Your turn — Aim and fire.")
        self._refresh_all()
        self._start_aim_watch()

    async def _watch_match_end_while_aiming(self) -> None:
        """While Aiming, notice opponent Abandon without blocking keys."""
        try:
            while self._phase == "aiming" and not self._busy:
                end = await self.conn.poll_incoming(timeout=0.05)
                if end is not None:
                    await self._show_match_end(end)
                    return
        except WorkerCancelled:
            return
        except (MatchConnectionError, OSError, ConnectionError):
            return

    async def _end_from_error(self, exc: BaseException) -> None:
        end = self.conn.match_end
        if end is None:
            with contextlib.suppress(MatchConnectionError, OSError, ConnectionError):
                end = await self.conn.wait_for_match_end()
        if end is not None:
            await self._show_match_end(end)
            return
        self.set_status(f"Match ended: {exc}")
        await self._close_and_return_to_opening()

    async def _show_match_end(self, end: MatchEnd) -> None:
        match_time = self._freeze_match_time()
        with contextlib.suppress(OSError, ConnectionError):
            await self.conn.close()
        _battle_app(self).show_match_end(
            role=self.role, end=end, match_time=match_time
        )

    async def confirm_quit(self) -> None:
        self._cancel_watch()
        if self._action_worker is not None and self._action_worker.state == WorkerState.RUNNING:
            self._action_worker.cancel()
            self._action_worker = None
        await _leave_and_close(self.conn)
        await self._return_to_opening()

    async def _close_and_return_to_opening(self) -> None:
        with contextlib.suppress(OSError, ConnectionError):
            await self.conn.close()
        await self._return_to_opening()

    async def _return_to_opening(self) -> None:
        _pop_to_opening(_battle_app(self))


class MatchEndScreen(Screen[None]):
    """Winner / Abandoned presentation with frozen Match time; Enter → opening."""

    BINDINGS = [
        Binding("enter", "continue", "Continue", show=False),
    ]

    def __init__(
        self, *, role: Role, end: MatchEnd, match_time: str
    ) -> None:
        super().__init__()
        self.role = role
        self.end = end
        self.match_time = match_time

    def compose(self) -> ComposeResult:
        label = "Host" if self.role == "host" else "Guest"
        with Vertical(id="match-end"):
            yield Static(f"{label} · Match over · Match time {self.match_time}", id="info")
            yield Static(self._body_markup(), id="body")
            yield Static("Press Enter to return to Host / Join / Exit.", id="status")

    def _body_markup(self) -> str:
        if self.end.outcome == MatchOutcome.ABANDONED:
            outcome = "Match Abandoned."
        elif self.end.outcome == MatchOutcome.WINNER:
            if self.end.winner == self.role:
                outcome = "You win!"
            else:
                winner = "Host" if self.end.winner == "host" else "Guest"
                outcome = f"Winner: {winner}."
        else:
            outcome = f"Match {self.end.outcome}."
        return f"{outcome}\nMatch time {self.match_time}"

    def info_text(self) -> str:
        return str(self.query_one("#info", Static).content)

    def body_text(self) -> str:
        return str(self.query_one("#body", Static).content)

    def set_status(self, message: str) -> None:
        self.query_one("#status", Static).update(message)

    def action_continue(self) -> None:
        _pop_to_opening(_battle_app(self))


class BattleShApp(App[None]):
    """Player Textual app. Relay URL and grace are CLI-only constructor args."""

    TITLE = "battle.sh"
    # Exit + two-step Ctrl+C only; suppress Textual's ctrl+q instant quit.
    BINDINGS = [
        Binding("ctrl+c", "quit_interrupt", "Quit", show=False, priority=True),
        Binding("ctrl+q", "suppress_quit", show=False, priority=True),
    ]

    def __init__(
        self,
        *,
        relay_url: str,
        grace_seconds: float,
        clock: Clock | None = None,
        placement_factory: Callable[[], Placement] | None = None,
    ) -> None:
        super().__init__()
        self.relay_url = relay_url
        self.grace_seconds = grace_seconds
        self._clock: Clock = clock if clock is not None else SystemClock()
        self.quit_arm = QuitArm(self._clock)
        self.placement_factory = (
            placement_factory if placement_factory is not None else random_placement
        )

    @property
    def clock(self) -> Clock:
        return self._clock

    def get_default_screen(self) -> OpeningScreen:
        return OpeningScreen()

    def show_placement(self, *, role: Role, conn: MatchConnection) -> None:
        """Guest has joined — start Match time and open the Placement screen."""
        match_started_at = self.clock.now()
        switch = cast(
            Callable[[Screen[None]], object],
            getattr(self, "switch_screen"),
        )
        switch(
            PlacementScreen(
                role=role,
                conn=conn,
                match_started_at=match_started_at,
                placement_factory=self.placement_factory,
            )
        )

    def show_combat(
        self,
        *,
        role: Role,
        conn: MatchConnection,
        placement: Placement,
        match_started_at: float,
    ) -> None:
        """Both Placements committed — open Aim / combat."""
        switch = cast(
            Callable[[Screen[None]], object],
            getattr(self, "switch_screen"),
        )
        switch(
            CombatScreen(
                role=role,
                conn=conn,
                placement=placement,
                match_started_at=match_started_at,
            )
        )

    def show_match_end(
        self, *, role: Role, end: MatchEnd, match_time: str
    ) -> None:
        """Frozen Match-time end presentation before returning to opening."""
        switch = cast(
            Callable[[Screen[None]], object],
            getattr(self, "switch_screen"),
        )
        switch(MatchEndScreen(role=role, end=end, match_time=match_time))

    def action_quit_interrupt(self) -> None:
        result = self.quit_arm.handle_interrupt()
        screen = self.screen
        if result == "warn":
            _set_screen_status(screen, QUIT_WARN)
            return
        _set_screen_status(screen, "")
        if isinstance(screen, PlacementScreen):
            self.run_worker(
                screen.confirm_quit(),
                name="placement_quit",
                group="placement",
                exclusive=True,
                exit_on_error=False,
            )
            return
        if isinstance(screen, CombatScreen):
            self.run_worker(
                screen.confirm_quit(),
                name="combat_quit",
                group="combat",
                exclusive=True,
                exit_on_error=False,
            )
            return
        if isinstance(screen, MatchEndScreen):
            _pop_to_opening(self)
            return
        self.exit()

    def action_suppress_quit(self) -> None:
        """No-op: `q` / ctrl+q must never quit the player app."""
        return


def _battle_app(screen: Screen[None]) -> BattleShApp:
    app = getattr(screen, "app")
    if not isinstance(app, BattleShApp):
        raise TypeError(f"expected BattleShApp, got {type(app)!r}")
    return app


async def _leave_and_close(conn: MatchConnection) -> bool:
    """Leave Match then close. False if leave failed while still connected."""
    try:
        await conn.leave_match()
    except (MatchConnectionError, OSError, ConnectionError):
        if conn.is_connected:
            return False
    with contextlib.suppress(OSError, ConnectionError):
        await conn.close()
    return True


def _set_screen_status(screen: object, message: str) -> None:
    setter = getattr(screen, "set_status", None)
    if callable(setter):
        setter(message)


def _static_plain(widget: Static, *, width: int) -> str:
    """Export a Static's content as plain terminal text (handles Rich renderables)."""
    content = widget.content
    if isinstance(content, str):
        return content
    console = Console(record=True, width=width, force_terminal=True)
    console.print(content)  # type: ignore[arg-type]
    return console.export_text()


def _pop_to_opening(app: BattleShApp) -> None:
    """Pop screens until the opening menu is current."""
    while not isinstance(app.screen, OpeningScreen) and len(app.screen_stack) > 1:
        app.pop_screen()
