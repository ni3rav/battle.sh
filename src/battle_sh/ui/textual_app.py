"""Textual player app: opening screen, in-app Host/Join lobby, QuitArm."""

from __future__ import annotations

import contextlib
from collections.abc import Callable
from typing import cast

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Input, OptionList, Static
from textual.widgets.option_list import Option
from textual.worker import Worker, WorkerCancelled, WorkerState

from battle_sh.networking.connection import MatchConnection, MatchConnectionError
from battle_sh.networking.protocol import Role
from battle_sh.ui.clock import Clock, SystemClock
from battle_sh.ui.quit_arm import QUIT_WARN, QuitArm

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
            app.show_ready_for_placement(role="host", conn=conn)
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
            app.show_ready_for_placement(role="guest", conn=conn)
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


class ReadyForPlacementScreen(Screen[None]):
    """Stub after lobby: both sides are connected and ready for Placement."""

    def __init__(self, *, role: Role, conn: MatchConnection) -> None:
        super().__init__()
        self.role = role
        self.conn = conn

    def compose(self) -> ComposeResult:
        label = "Host" if self.role == "host" else "Guest"
        with Vertical(id="ready-placement"):
            yield Static(f"{label} · Ready for Placement", id="headline")
            yield Static("Placement comes next.", id="body")
            yield Static("", id="status")


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
    ) -> None:
        super().__init__()
        self.relay_url = relay_url
        self.grace_seconds = grace_seconds
        self._clock: Clock = clock if clock is not None else SystemClock()
        self.quit_arm = QuitArm(self._clock)

    def get_default_screen(self) -> OpeningScreen:
        return OpeningScreen()

    def show_ready_for_placement(
        self, *, role: Role, conn: MatchConnection
    ) -> None:
        """Replace the current lobby screen with the Placement-ready stub."""
        # Textual types App.switch_screen as Screen[Unknown]; keep our call site typed.
        switch = cast(
            Callable[[Screen[None]], object],
            getattr(self, "switch_screen"),
        )
        switch(ReadyForPlacementScreen(role=role, conn=conn))

    def action_quit_interrupt(self) -> None:
        result = self.quit_arm.handle_interrupt()
        screen = self.screen
        if result == "warn":
            _set_screen_status(screen, QUIT_WARN)
            return
        _set_screen_status(screen, "")
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
