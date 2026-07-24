"""Fixed three-band Match UI shell (top | board+controls | bottom)."""

from __future__ import annotations

from dataclasses import dataclass

from battle_sh.rules.board import ShotResultKind
from battle_sh.rules.placement import Coordinate, Placement
from battle_sh.ui.boards import own_board_renderable, tracking_board_renderable
from rich.console import Group, RenderableType
from rich.layout import Layout
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

PLACEMENT_CONTROLS = """\
[bold]Placement[/]

  [bold]`1`-`5`[/]
  → select ship

  [bold]`tab` / `shift+tab`[/]
  → cycle

  [bold]`w`/`a`/`s`/`d` / arrows[/]
  → move

  [bold]`e` / `r`[/]
  → flip H↔V

  [bold]`t`[/]
  → new random

  [bold]`y`[/]
  → lock

  [bold]`Ctrl+C`[/]
  → quit
"""

AIM_CONTROLS = """\
[bold]Aim[/]

  [bold]`w`/`a`/`s`/`d` / arrows[/]
  → move

  [bold]`f` / `Enter` / `Space`[/]
  → fire

  [bold]`Ctrl+C`[/]
  → quit
"""

WAIT_CONTROLS = """\
[bold]Waiting[/]

  [bold]`Ctrl+C`[/]
  → quit
"""

_SPINNER = ("|", "/", "-", "\\")


@dataclass(frozen=True)
class CombatBoards:
    """Own + tracking Board state shared by combat Aim and wait frames."""

    placement: Placement
    own_marks: dict[Coordinate, ShotResultKind]
    tracking: dict[Coordinate, ShotResultKind]
    revealed: frozenset[Coordinate]


@dataclass(frozen=True)
class MatchStatus:
    """Real-time scoreboard/status shared across the Match UI frames."""

    role: str
    state: str
    turn: str
    your_ships_afloat: int
    your_ships_total: int
    enemy_ships_afloat: int
    enemy_ships_total: int
    your_hits: int
    enemy_hits: int
    total_cells: int
    you_connected: bool
    opponent_connected: bool
    synchronized: bool
    your_fleet: tuple[tuple[str, bool], ...] = ()
    enemy_sunk: tuple[str, ...] = ()


def _dot(connected: bool) -> str:
    return "[bold green]●[/]" if connected else "[bold red]○[/]"


def connection_line(status: MatchStatus) -> str:
    """Compact link/turn/state markup line shared by every frame's info band."""
    sync = "[green]in sync[/]" if status.synchronized else "[yellow]syncing…[/]"
    return (
        f"Link: {_dot(status.you_connected)} You  "
        f"{_dot(status.opponent_connected)} Opponent  ·  {sync}  ·  "
        f"Turn: [bold]{status.turn}[/]"
    )


def scoreboard_renderable(status: MatchStatus) -> RenderableType:
    """Compact live indicators: ships, hits, connection, and fleet detail."""
    grid = Table.grid(padding=(0, 1))
    grid.add_column(justify="left")
    grid.add_column(justify="right")
    grid.add_column(justify="right")
    grid.add_row("", "[bold]You[/]", "[bold]Enemy[/]")
    grid.add_row(
        "Ships afloat",
        f"{status.your_ships_afloat}/{status.your_ships_total}",
        f"{status.enemy_ships_afloat}/{status.enemy_ships_total}",
    )
    grid.add_row(
        "Hits",
        f"{status.your_hits}/{status.total_cells}",
        f"{status.enemy_hits}/{status.total_cells}",
    )

    fleet_lines: list[str] = ["[bold]Your fleet[/]"]
    for name, afloat in status.your_fleet:
        marker = "[green]afloat[/]" if afloat else "[red]SUNK[/]"
        fleet_lines.append(f" {name:<11}{marker}")
    enemy_sunk = ", ".join(status.enemy_sunk) if status.enemy_sunk else "none yet"

    return Group(
        Text.from_markup(f"[bold]State[/] {status.state}"),
        Text(""),
        grid,
        Text(""),
        Text.from_markup("\n".join(fleet_lines)),
        Text(""),
        Text.from_markup(f"[bold]Enemy sunk[/]\n {enemy_sunk}"),
    )


def sidebar_scoreboard_renderable(status: MatchStatus) -> RenderableType:
    """Short scoreboard for the combat sidebar (leaves room for controls)."""
    sunk = sum(1 for _, afloat in status.your_fleet if not afloat)
    enemy_sunk = ", ".join(status.enemy_sunk) if status.enemy_sunk else "none"
    return Text.from_markup(
        "\n".join(
            [
                f"[bold]State[/] {status.state}",
                f"Ships [bold]{status.your_ships_afloat}[/]/"
                f"{status.your_ships_total}  vs  "
                f"[bold]{status.enemy_ships_afloat}[/]/{status.enemy_ships_total}",
                f"Hits  [bold]{status.your_hits}[/]/{status.total_cells}  vs  "
                f"[bold]{status.enemy_hits}[/]/{status.total_cells}",
                f"Sunk you:{sunk}  enemy:{enemy_sunk}",
            ]
        )
    )


def _three_band(
    *,
    top: RenderableType,
    middle_left: RenderableType,
    middle_right: RenderableType,
    bottom: RenderableType,
    top_size: int = 3,
    right_size: int = 28,
    right_title: str = "controls",
) -> Layout:
    layout = Layout()
    layout.split_column(
        Layout(Panel(top, title="info", padding=(0, 1)), name="top", size=top_size),
        Layout(name="middle", ratio=1),
        Layout(Panel(bottom, title="status", padding=(0, 1)), name="bottom", size=3),
    )
    layout["middle"].split_row(
        Layout(Panel(middle_left, title="board", padding=(0, 1)), name="board", ratio=3),
        Layout(
            Panel(middle_right, title=right_title, padding=(0, 1)),
            name="controls",
            size=right_size,
        ),
    )
    return layout


def placement_frame(
    *,
    placement: Placement,
    selected: str | None,
    status: str = "",
    top_info: str = "Phase: Placement",
) -> RenderableType:
    """Compose the Placement three-band view (pure; no Live)."""
    board = own_board_renderable(placement, {}, selected=selected)
    selected_line = (
        f"Selected: [bold yellow]{selected}[/]"
        if selected
        else "No ship selected — press [bold]1-5[/] or [bold]tab[/]."
    )
    board_body: RenderableType = Group(board, Text.from_markup(selected_line))
    return _three_band(
        top=Text(top_info),
        middle_left=board_body,
        middle_right=Text.from_markup(PLACEMENT_CONTROLS),
        right_size=32,
        bottom=Text(status or " "),
    )


def lobby_frame(
    *,
    role: str,
    invite: str,
    status: str = "Waiting for Guest…",
    status_info: MatchStatus | None = None,
) -> RenderableType:
    """Host lobby: waiting for Guest; Match time has not started."""
    headline = Text(f"{role} · Lobby — waiting for Guest (Invite {invite})")
    top: RenderableType = (
        Group(headline, Text.from_markup(connection_line(status_info)))
        if status_info is not None
        else headline
    )
    body = Text(
        "Share the Invite with your opponent.\nMatch time starts when they join."
    )
    return _three_band(
        top=top,
        top_size=4 if status_info is not None else 3,
        middle_left=body,
        middle_right=Text.from_markup(WAIT_CONTROLS),
        bottom=Text(status or " "),
    )


def wait_frame(
    *,
    role: str,
    phase: str,
    match_time: str,
    spinner_frame: int = 0,
    status: str = "Waiting…",
    board: RenderableType | None = None,
    status_info: MatchStatus | None = None,
) -> RenderableType:
    """Wait chrome with Match time and spinner; only quit keys in controls."""
    spin = _SPINNER[spinner_frame % len(_SPINNER)]
    headline = Text(f"{role} · {phase} · Match time {match_time}  {spin}")
    top: RenderableType = (
        Group(headline, Text.from_markup(connection_line(status_info)))
        if status_info is not None
        else headline
    )
    middle = board if board is not None else Text("Boards stay visible while you wait.")
    return _three_band(
        top=top,
        top_size=4 if status_info is not None else 3,
        middle_left=middle,
        middle_right=Text.from_markup(WAIT_CONTROLS),
        bottom=Text(status or " "),
    )


def _combat_info_top(
    headline: str, status_info: MatchStatus | None
) -> RenderableType:
    if status_info is None:
        return Text(headline)
    return Group(
        Text(headline),
        Text.from_markup(connection_line(status_info)),
    )


def _combat_boards(
    boards: CombatBoards, *, aim: Coordinate | None = None
) -> RenderableType:
    """Own fleet stacked above tracking/Aim so the middle band stays tall enough."""
    return Group(
        own_board_renderable(boards.placement, boards.own_marks),
        Text(""),
        tracking_board_renderable(boards.tracking, boards.revealed, aim=aim),
    )


def _combat_sidebar(
    status_info: MatchStatus | None, controls: str
) -> RenderableType:
    """Keymap first so stacked controls stay visible; scoreboard below."""
    controls_text = Text.from_markup(controls)
    if status_info is None:
        return controls_text
    return Group(
        controls_text,
        Text(""),
        sidebar_scoreboard_renderable(status_info),
    )


def combat_frame(
    *,
    role: str,
    match_time: str,
    boards: CombatBoards,
    aim: Coordinate,
    status: str = "",
    status_info: MatchStatus | None = None,
) -> RenderableType:
    """Your turn: own + Aim boards stacked; scoreboard + controls in the sidebar."""
    return _three_band(
        top=_combat_info_top(
            f"{role} · Aim · Match time {match_time}", status_info
        ),
        top_size=4 if status_info is not None else 3,
        middle_left=_combat_boards(boards, aim=aim),
        middle_right=_combat_sidebar(status_info, AIM_CONTROLS),
        right_size=32,
        bottom=Text(status or " "),
    )


def combat_wait_frame(
    *,
    role: str,
    match_time: str,
    boards: CombatBoards,
    spinner_frame: int = 0,
    status: str = "Waiting for opponent…",
    status_info: MatchStatus | None = None,
) -> RenderableType:
    """Opponent's turn: same board stack; wait controls in the sidebar."""
    spin = _SPINNER[spinner_frame % len(_SPINNER)]
    status_line = f"{spin} {status}" if status else spin
    return _three_band(
        top=_combat_info_top(
            f"{role} · Waiting · Match time {match_time}", status_info
        ),
        top_size=4 if status_info is not None else 3,
        middle_left=_combat_boards(boards),
        middle_right=_combat_sidebar(status_info, WAIT_CONTROLS),
        right_size=32,
        bottom=Text(status_line),
    )
