"""Textual player app: opening screen shell (Host / Join stubs, Exit, QuitArm)."""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import OptionList, Static
from textual.widgets.option_list import Option

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
        if option_id == OPTION_EXIT:
            app = getattr(self, "app")
            if not isinstance(app, BattleShApp):
                raise TypeError(f"expected BattleShApp, got {type(app)!r}")
            app.exit()
            return
        if option_id == OPTION_HOST:
            self.set_status("Host (not implemented yet)")
            return
        if option_id == OPTION_JOIN:
            self.set_status("Join (not implemented yet)")
            return


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

    def action_quit_interrupt(self) -> None:
        result = self.quit_arm.handle_interrupt()
        screen = self.screen
        if result == "warn":
            if isinstance(screen, OpeningScreen):
                screen.set_status(QUIT_WARN)
            return
        if isinstance(screen, OpeningScreen):
            screen.set_status("")
        self.exit()

    def action_suppress_quit(self) -> None:
        """No-op: `q` / ctrl+q must never quit the player app."""
        return
