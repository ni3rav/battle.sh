"""Match UI chrome helpers: controls copy, status line, scoreboard."""

from __future__ import annotations

from dataclasses import dataclass

from rich.console import Group, RenderableType
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

SPINNER = ("|", "/", "-", "\\")


@dataclass(frozen=True)
class MatchStatus:
    """Real-time scoreboard/status shared across Match UI screens."""

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
    """Compact link/turn/state markup line for the info band."""
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
