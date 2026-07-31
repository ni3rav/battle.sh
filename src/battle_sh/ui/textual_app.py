"""Textual player app: opening, themes, Host/Join lobby, Placement, Combat, QuitArm."""

from __future__ import annotations

import contextlib
from collections.abc import Callable
from typing import Literal, cast

from rich.console import Console, Group
from rich.text import Text
from textual import events
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Center, Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Input, OptionList, Rule, Static
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
from battle_sh.ui.boards import (
    BoardPalette,
    own_board_renderable,
    palette_from_colors,
    tracking_board_renderable,
)
from battle_sh.ui.chrome import (
    SPINNER,
    MatchStatus,
    connection_line,
)
from battle_sh.ui.clock import Clock, SystemClock, format_elapsed
from battle_sh.ui.combat import (
    apply_incoming_shot,
    apply_outgoing_shot,
    combat_match_status,
    format_shot_feedback,
)
from battle_sh.ui.key_help import (
    AIM_KEYS,
    PLACEMENT_KEYS,
    WAIT_KEYS,
    keys_table_renderable,
    stacked_sidebar,
)
from battle_sh.ui.keys import Key
from battle_sh.ui.match_end_copy import match_end_detail, match_end_headline
from battle_sh.ui.placement_flow import apply_placement_key
from battle_sh.ui.quit_arm import QUIT_WARN, QuitArm
from battle_sh.ui.ship_progress import enemy_ship_rows, your_ship_rows
from battle_sh.ui.ship_tables import ship_table_renderable
from battle_sh.ui.sigint import install_sigint, uninstall_sigint
from battle_sh.ui.theme_config import DEFAULT_THEME, load_theme_name, save_theme_name

# ASCII glyph for wide terminals; narrow terminals show BRAND_TITLE only.
BANNER = (
    "░██                      ░██       ░██    ░██                           ░██        \n"
    "░██                      ░██       ░██    ░██                           ░██        \n"
    "░████████   ░██████   ░████████ ░████████ ░██  ░███████       ░███████  ░████████  \n"
    "░██    ░██       ░██     ░██       ░██    ░██ ░██    ░██     ░██        ░██    ░██ \n"
    "░██    ░██  ░███████     ░██       ░██    ░██ ░█████████      ░███████  ░██    ░██ \n"
    "░███   ░██ ░██   ░██     ░██       ░██    ░██ ░██                   ░██ ░██    ░██ \n"
    "░██░█████   ░█████░██     ░████     ░████ ░██  ░███████  ░██  ░███████  ░██    ░██ "
)
BRAND_TITLE = "battle.sh"
# Banner lines are ~88 cols; require a little padding so centering still fits.
BANNER_MIN_WIDTH = 92

OPTION_HOST = "host"
OPTION_JOIN = "join"
OPTION_THEME = "theme"
OPTION_EXIT = "exit"
OPTION_BACK = "back"
OPTION_SUBMIT_JOIN = "submit_join"
OPTION_LOBBY = "lobby"

_PlacementPhase = Literal["editing", "waiting"]
_CombatPhase = Literal["aiming", "waiting"]

SIDEBAR_CSS = """
    #sidebar {
        width: 44;
        padding: 0 1;
    }
"""

CENTERED_FRAME_CSS = """
    .centered-frame {
        width: 100%;
        height: auto;
        align-horizontal: center;
    }
    .centered-menu {
        width: 32;
        height: auto;
        text-align: center;
        padding: 0 1;
    }
    .centered-menu > .option-list--option {
        text-align: center;
    }
    .centered-menu:focus > .option-list--option-highlighted {
        text-align: center;
    }
"""


def _app_palette(app: App[None]) -> BoardPalette:
    theme = app.current_theme
    return palette_from_colors(
        primary=theme.primary or "#0178D4",
        success=theme.success or "#4EBF71",
        error=theme.error or "#ba3c5b",
        warning=theme.warning or "#ffa62b",
        accent=theme.accent or "#ffa62b",
        foreground=theme.foreground,
    )


def brand_renderable(*, width: int) -> Text:
    """Wide terminals get the ASCII glyph; narrow ones get just ``battle.sh``."""
    if width >= BANNER_MIN_WIDTH:
        return Text(BANNER)
    return Text(BRAND_TITLE, style="bold")


class OpeningScreen(Screen[None]):
    """Centered opening menu: Host, Join, Theme, Exit."""

    DEFAULT_CSS = CENTERED_FRAME_CSS + """
    OpeningScreen {
        align: center middle;
    }
    #opening {
        width: 100%;
        height: auto;
        padding: 1 2;
    }
    #brand {
        text-align: center;
        width: 100%;
        height: auto;
        padding-bottom: 1;
    }
    #status {
        width: 100%;
        height: 2;
        padding-top: 1;
        text-align: center;
    }
    """

    def compose(self) -> ComposeResult:
        with Vertical(id="opening"):
            yield Static(BRAND_TITLE, id="brand")
            yield Rule()
            with Center():
                yield OptionList(
                    Option(Text("Host", justify="center"), id=OPTION_HOST),
                    Option(Text("Join", justify="center"), id=OPTION_JOIN),
                    Option(Text("Theme", justify="center"), id=OPTION_THEME),
                    Option(Text("Exit", justify="center"), id=OPTION_EXIT),
                    id="menu",
                    classes="centered-menu",
                )
            yield Rule()
            yield Static("", id="status")

    def on_mount(self) -> None:
        self._refresh_brand()
        self.query_one("#menu", OptionList).focus()

    def on_resize(self, event: events.Resize) -> None:
        self._refresh_brand()

    def _refresh_brand(self) -> None:
        self.query_one("#brand", Static).update(
            brand_renderable(width=self.size.width)
        )

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
        if option_id == OPTION_THEME:
            app.push_screen(ThemeScreen())
            return


class ThemeScreen(Screen[None]):
    """Ghostty-style theme picker: list left, live Combat mock preview right."""

    BINDINGS = [
        Binding("escape", "back", "Back", show=False),
    ]

    DEFAULT_CSS = """
    ThemeScreen {
        layout: vertical;
    }
    #theme-headline {
        height: 3;
        padding: 0 1;
        text-align: center;
    }
    #theme-body {
        height: 1fr;
        layout: horizontal;
    }
    #theme-list {
        width: 28;
        padding: 0 1;
    }
    #theme-preview {
        width: 1fr;
        padding: 0 1;
    }
    #status {
        height: 2;
        padding: 0 1;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self._saved_theme = DEFAULT_THEME
        self._previewing: str | None = None
        self._theme_signal_subscribed = False

    def compose(self) -> ComposeResult:
        with Vertical(id="theme"):
            yield Static("Theme · browse and preview", id="theme-headline")
            yield Rule()
            with Horizontal(id="theme-body"):
                yield OptionList(id="theme-list")
                with VerticalScroll(id="theme-preview-scroll"):
                    yield Static("", id="theme-preview")
            yield Rule()
            yield Static("", id="status")

    def on_mount(self) -> None:
        app = _battle_app(self)
        self._saved_theme = app.theme
        names = sorted(app.available_themes)
        option_list = self.query_one("#theme-list", OptionList)
        for name in names:
            option_list.add_option(Option(name, id=name))
        if self._saved_theme in names:
            option_list.highlighted = names.index(self._saved_theme)
        option_list.focus()
        # Re-render the mock Combat preview whenever Textual finishes applying
        # theme CSS variables so board colors track the live chrome.
        app.theme_changed_signal.subscribe(
            self, self._on_theme_changed, immediate=True
        )
        self._theme_signal_subscribed = True
        self._apply_preview(self._saved_theme, force=True)
        self.set_status(f"Previewing: {app.theme}  ·  Enter to save · Esc to cancel")

    def on_unmount(self) -> None:
        if not self._theme_signal_subscribed:
            return
        with contextlib.suppress(Exception):
            _battle_app(self).theme_changed_signal.unsubscribe(self)
        self._theme_signal_subscribed = False

    def set_status(self, message: str) -> None:
        self.query_one("#status", Static).update(message)

    def on_option_list_option_highlighted(
        self, event: OptionList.OptionHighlighted
    ) -> None:
        theme_id = event.option.id
        if theme_id is None:
            return
        self._apply_preview(str(theme_id))

    def on_option_list_option_selected(
        self, event: OptionList.OptionSelected
    ) -> None:
        theme_id = event.option.id
        if theme_id is None:
            return
        name = str(theme_id)
        app = _battle_app(self)
        app.theme = name
        save_theme_name(name)
        self._saved_theme = name
        self.set_status(f"Theme saved: {name}")
        _battle_app(self).pop_screen()

    def action_back(self) -> None:
        app = _battle_app(self)
        app.theme = self._saved_theme
        app.pop_screen()

    def _on_theme_changed(self, theme: object) -> None:
        """Textual finished switching themes — refresh board palette preview."""
        name = getattr(theme, "name", None)
        if isinstance(name, str) and name:
            self._previewing = name
        self._refresh_preview_content()
        self.refresh()

    def _apply_preview(self, theme_name: str, *, force: bool = False) -> None:
        app = _battle_app(self)
        if theme_name not in app.available_themes:
            return
        if not force and self._previewing == theme_name and app.theme == theme_name:
            return
        self._previewing = theme_name
        # Apply immediately so OptionList/chrome restyle as the user browses.
        app.theme = theme_name
        self._refresh_preview_content()
        self.set_status(f"Previewing: {theme_name}  ·  Enter to save · Esc to cancel")

    def _refresh_preview_content(self) -> None:
        self.query_one("#theme-preview", Static).update(self._preview_renderable())

    def _preview_renderable(self) -> Group:
        from battle_sh.rules.placement import coordinate

        palette = _app_palette(_battle_app(self))
        placement = Placement(
            {
                "Carrier": frozenset(coordinate(c, 1) for c in "ABCDE"),
                "Battleship": frozenset(coordinate(c, 2) for c in "ABCD"),
                "Cruiser": frozenset(coordinate(c, 3) for c in "ABC"),
                "Submarine": frozenset(coordinate(c, 4) for c in "ABC"),
                "Destroyer": frozenset(coordinate(c, 5) for c in "AB"),
            }
        )
        own_marks: dict[Coordinate, ShotResultKind] = {
            coordinate("A", 1): "hit",
            coordinate("B", 5): "sunk",
            coordinate("A", 5): "sunk",
            coordinate("J", 10): "miss",
        }
        tracking: dict[Coordinate, ShotResultKind] = {
            coordinate("C", 3): "hit",
            coordinate("D", 7): "miss",
            coordinate("A", 8): "sunk",
            coordinate("B", 8): "sunk",
        }
        revealed = frozenset({coordinate("A", 8), coordinate("B", 8)})
        your_rows = your_ship_rows(placement, own_marks)
        enemy_rows = enemy_ship_rows(("Destroyer",))
        return Group(
            Text.from_markup(f"[bold]Preview[/] · {_battle_app(self).theme}"),
            Text(""),
            own_board_renderable(placement, own_marks, palette=palette),
            Text(""),
            tracking_board_renderable(
                tracking, revealed, aim=coordinate("E", 5), palette=palette
            ),
            Text(""),
            stacked_sidebar(
                keys_table_renderable(AIM_KEYS, title="Keys"),
                ship_table_renderable(your_rows, title="Your ships"),
                ship_table_renderable(enemy_rows, title="Enemy ships"),
            ),
        )


class HostWaitingScreen(Screen[None]):
    """Host lobby: create Match, show Invite, wait for Guest; Back cancels."""

    BINDINGS = [
        Binding("escape", "back", "Back", show=False),
    ]

    DEFAULT_CSS = CENTERED_FRAME_CSS + """
    HostWaitingScreen {
        align: center middle;
    }
    #host-waiting {
        width: 100%;
        height: auto;
        padding: 1 2;
    }
    #headline, #body, #status {
        width: 100%;
        text-align: center;
    }
    #invite-row {
        height: 1;
        align: center middle;
    }
    #invite {
        width: auto;
        text-align: center;
    }
    #copy-btn {
        width: auto;
        min-width: 10;
        height: 1;
        margin: 0 0 0 1;
        border: none;
        padding: 0 1;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self._invite: str | None = None
        self._conn: MatchConnection | None = None
        self._worker: Worker[None] | None = None

    def compose(self) -> ComposeResult:
        with Vertical(id="host-waiting"):
            yield Static("Host · Lobby — waiting for Guest", id="headline")
            yield Rule()
            with Center():
                with Horizontal(id="invite-row"):
                    yield Static("Creating Match…", id="invite")
                    yield Button(Text("[copy]"), id="copy-btn", disabled=True)
            yield Static(
                "Share the Invite with your opponent.\n"
                "Match time starts when they join.",
                id="body",
            )
            yield Rule()
            with Center():
                yield OptionList(
                    Option(Text("Back", justify="center"), id=OPTION_BACK),
                    id="menu",
                    classes="centered-menu",
                )
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
            self.query_one("#copy-btn", Button).disabled = False
            self.set_status("Waiting for Guest…")
            await conn.wait_for_player_joined()
            self._conn = None
            app.show_placement(role="host", conn=conn)
        except WorkerCancelled:
            return
        except (MatchConnectionError, OSError, ConnectionError) as exc:
            self.set_status(f"Could not Host: {exc}")
            return

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id != "copy-btn":
            return
        invite = self._invite
        if invite is None:
            return
        btn = self.query_one("#copy-btn", Button)
        try:
            _battle_app(self).copy_to_clipboard(invite)
            btn.label = Text("[done]")
            self.set_timer(2.0, self._reset_copy_btn)
        except Exception:
            btn.label = Text("[copy]")

    def _reset_copy_btn(self) -> None:
        try:
            self.query_one("#copy-btn", Button).label = Text("[copy]")
        except Exception:
            pass

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

    DEFAULT_CSS = CENTERED_FRAME_CSS + """
    JoinScreen {
        align: center middle;
    }
    #join {
        width: 100%;
        height: auto;
        padding: 1 2;
    }
    #headline, #status {
        width: 100%;
        text-align: center;
    }
    #invite-input {
        width: 32;
        text-align: center;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self._conn: MatchConnection | None = None

    def compose(self) -> ComposeResult:
        with Vertical(id="join"):
            yield Static("Join · paste Invite", id="headline")
            yield Rule()
            with Center():
                yield Input(placeholder="Invite phrase", id="invite-input")
            with Center():
                yield OptionList(
                    Option(Text("Join", justify="center"), id=OPTION_SUBMIT_JOIN),
                    Option(Text("Back", justify="center"), id=OPTION_BACK),
                    id="menu",
                    classes="centered-menu",
                )
            yield Rule()
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

    DEFAULT_CSS = f"""
    PlacementScreen {{
        layout: vertical;
    }}
    #info {{
        height: 3;
        padding: 0 1;
        text-align: center;
    }}
    #middle {{
        height: 1fr;
        layout: horizontal;
    }}
    #board-panel {{
        width: 1fr;
        padding: 0 1;
        align: center middle;
    }}
    #board {{
        width: auto;
        height: auto;
    }}
    {SIDEBAR_CSS}
    #status {{
        height: 3;
        padding: 0 1;
        text-align: center;
    }}
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
            yield Rule()
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
                yield Rule(orientation="vertical")
                yield Static(
                    keys_table_renderable(PLACEMENT_KEYS, title="Keys"),
                    id="sidebar",
                )
            yield Rule()
            yield Static(" ", id="status")

    def on_mount(self) -> None:
        self._refresh_info()
        self._refresh_board()
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
        """Sidebar text currently shown (kbd table)."""
        return _static_plain(self.query_one("#sidebar", Static), width=48)

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

    def _palette(self) -> BoardPalette:
        return _app_palette(_battle_app(self))

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
            own_board_renderable(
                self._placement, {}, selected=self._selected, palette=self._palette()
            )
        )
        selected_line = (
            f"Selected: {self._selected}"
            if self._selected
            else "No ship selected — press 1-5 or tab."
        )
        self.query_one("#selected-line", Static).update(selected_line)

    def _enter_waiting(self) -> None:
        self._phase = "waiting"
        self.query_one("#sidebar", Static).update(
            keys_table_renderable(WAIT_KEYS, title="Keys")
        )
        self.set_status("Waiting for opponent to lock…")
        self._refresh_info()

    def on_key(self, event: events.Key) -> None:
        if self._phase == "waiting":
            return
        if event.key in {"ctrl+c", "ctrl+q"}:
            return
        key = Key(event.key)
        placement, selected, action, message = apply_placement_key(
            key,
            self._placement,
            self._selected,
            factory=self._factory,
            arm=None,
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
        try:
            while self._phase == "editing":
                end = await self.conn.poll_incoming(timeout=0.05)
                if end is not None:
                    await self._show_abandoned_end(end)
                    return
        except WorkerCancelled:
            return
        except (MatchConnectionError, OSError, ConnectionError):
            return

    async def confirm_quit(self) -> None:
        if self._watch_worker is not None and self._watch_worker.state == WorkerState.RUNNING:
            self._watch_worker.cancel()
        self._watch_worker = None
        match_time = format_elapsed(
            _battle_app(self).clock.now() - self._match_started_at
        )
        await _leave_and_close(self.conn)
        _battle_app(self).show_match_end(
            role=self.role,
            end=MatchEnd(outcome=MatchOutcome.ABANDONED, reason="left"),
            match_time=match_time,
        )

    async def _show_abandoned_end(self, end: MatchEnd) -> None:
        match_time = format_elapsed(
            _battle_app(self).clock.now() - self._match_started_at
        )
        with contextlib.suppress(OSError, ConnectionError):
            await self.conn.close()
        _battle_app(self).show_match_end(
            role=self.role, end=end, match_time=match_time
        )

    async def _close_and_return_to_opening(self) -> None:
        with contextlib.suppress(OSError, ConnectionError):
            await self.conn.close()
        await self._return_to_opening()

    async def _return_to_opening(self) -> None:
        _pop_to_opening(_battle_app(self))


class CombatScreen(Screen[None]):
    """Combat phase: Aim / off-turn wait, exact keys, boards + ship tables."""

    DEFAULT_CSS = f"""
    CombatScreen {{
        layout: vertical;
    }}
    #info {{
        height: 4;
        padding: 0 1;
        text-align: center;
    }}
    #middle {{
        height: 1fr;
        layout: horizontal;
    }}
    #board-panel {{
        width: 1fr;
        padding: 0 1;
        align: center middle;
    }}
    #board {{
        width: auto;
        height: auto;
    }}
    {SIDEBAR_CSS}
    #status {{
        height: 3;
        padding: 0 1;
        text-align: center;
    }}
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
            yield Rule()
            with Horizontal(id="middle"):
                with Vertical(id="board-panel"):
                    yield Static("", id="board")
                yield Rule(orientation="vertical")
                yield Static("", id="sidebar")
            yield Rule()
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
        return _static_plain(self.query_one("#sidebar", Static), width=48)

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

    def _palette(self) -> BoardPalette:
        return _app_palette(_battle_app(self))

    def _refresh_all(self) -> None:
        self._refresh_info()
        self._refresh_board()
        self._refresh_controls()
        self._refresh_status()

    def _refresh_status(self) -> None:
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
        palette = self._palette()
        self.query_one("#board", Static).update(
            Group(
                own_board_renderable(
                    self._placement, self._own_marks, palette=palette
                ),
                Text(""),
                tracking_board_renderable(
                    self._tracking,
                    frozenset(self._revealed),
                    aim=aim,
                    palette=palette,
                ),
            )
        )

    def _refresh_controls(self) -> None:
        keys = AIM_KEYS if self._phase == "aiming" else WAIT_KEYS
        your_rows = your_ship_rows(self._placement, self._own_marks)
        enemy_rows = enemy_ship_rows(self._enemy_sunk)
        self.query_one("#sidebar", Static).update(
            stacked_sidebar(
                keys_table_renderable(keys, title="Keys"),
                ship_table_renderable(your_rows, title="Your ships"),
                ship_table_renderable(enemy_rows, title="Enemy ships"),
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
        except (
            MatchConnectionError,
            OSError,
            ConnectionError,
            RevealVerificationError,
        ) as exc:
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
        except (
            MatchConnectionError,
            OSError,
            ConnectionError,
            RevealVerificationError,
        ) as exc:
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
        match_time = self._freeze_match_time()
        await _leave_and_close(self.conn)
        _battle_app(self).show_match_end(
            role=self.role,
            end=MatchEnd(outcome=MatchOutcome.ABANDONED, reason="left"),
            match_time=match_time,
        )

    async def _close_and_return_to_opening(self) -> None:
        with contextlib.suppress(OSError, ConnectionError):
            await self.conn.close()
        await self._return_to_opening()

    async def _return_to_opening(self) -> None:
        _pop_to_opening(_battle_app(self))


class MatchEndScreen(Screen[None]):
    """Outcome + match time with Lobby / Exit actions."""

    DEFAULT_CSS = CENTERED_FRAME_CSS + """
    MatchEndScreen {
        align: center middle;
    }
    #match-end {
        width: 100%;
        height: auto;
        padding: 1 2;
    }
    #info, #body, #status {
        width: 100%;
        text-align: center;
    }
    """

    def __init__(
        self, *, role: Role, end: MatchEnd, match_time: str
    ) -> None:
        super().__init__()
        self.role = role
        self.end = end
        self.match_time = match_time

    def compose(self) -> ComposeResult:
        with Vertical(id="match-end"):
            yield Static(self._info_line(), id="info")
            yield Rule()
            yield Static(self._body_markup(), id="body")
            yield Rule()
            with Center():
                yield OptionList(
                    Option(Text("Lobby", justify="center"), id=OPTION_LOBBY),
                    Option(Text("Exit", justify="center"), id=OPTION_EXIT),
                    id="menu",
                    classes="centered-menu",
                )
            yield Static("", id="status")

    def on_mount(self) -> None:
        self.query_one("#menu", OptionList).focus()

    def _info_line(self) -> str:
        label = "Host" if self.role == "host" else "Guest"
        return f"{label} · Match over · Match time {self.match_time}"

    def _body_markup(self) -> str:
        role = cast(Role, self.role)
        headline = match_end_headline(role, self.end)
        detail = match_end_detail(role, self.end)
        lines = [headline, f"Match time {self.match_time}"]
        if detail:
            lines.insert(1, detail)
        return "\n".join(lines)

    def info_text(self) -> str:
        return str(self.query_one("#info", Static).content)

    def body_text(self) -> str:
        return str(self.query_one("#body", Static).content)

    def set_status(self, message: str) -> None:
        self.query_one("#status", Static).update(message)

    def on_option_list_option_selected(
        self, event: OptionList.OptionSelected
    ) -> None:
        option_id = event.option.id
        if option_id == OPTION_LOBBY:
            _pop_to_opening(_battle_app(self))
            return
        if option_id == OPTION_EXIT:
            _battle_app(self).exit()


class BattleShApp(App[None]):
    """Player Textual app. Relay URL and grace are CLI-only constructor args."""

    TITLE = "battle.sh"
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
        theme_name: str | None = None,
    ) -> None:
        super().__init__()
        self.relay_url = relay_url
        self.grace_seconds = grace_seconds
        self._clock: Clock = clock if clock is not None else SystemClock()
        self.quit_arm = QuitArm(self._clock)
        self.placement_factory = (
            placement_factory if placement_factory is not None else random_placement
        )
        self._sigint_installed = False
        self._initial_theme = (
            theme_name if theme_name is not None else load_theme_name()
        )

    @property
    def clock(self) -> Clock:
        return self._clock

    def get_default_screen(self) -> OpeningScreen:
        return OpeningScreen()

    def on_mount(self) -> None:
        """Apply persisted theme and route OS SIGINT into QuitArm."""
        if self._initial_theme in self.available_themes:
            self.theme = self._initial_theme
        else:
            self.theme = DEFAULT_THEME
        self._sigint_installed = install_sigint(self.action_quit_interrupt)

    def on_unmount(self) -> None:
        if not self._sigint_installed:
            return
        uninstall_sigint()
        self._sigint_installed = False

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
        if isinstance(screen, ThemeScreen):
            screen.action_back()
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
