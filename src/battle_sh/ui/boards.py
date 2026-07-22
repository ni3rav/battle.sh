"""rich Board and Tracking Board rendering (color-coded hit/miss/sunk)."""

from __future__ import annotations

from battle_sh.rules.board import ShotResultKind
from battle_sh.rules.placement import COLUMNS, ROWS, Coordinate, Placement
from rich.console import Console, Group, RenderableType
from rich.table import Table
from rich.text import Text

# Unique letters so each Ship is readable on the Board (Cruiser → R).
SHIP_GLYPH: dict[str, str] = {
    "Carrier": "C",
    "Battleship": "B",
    "Cruiser": "R",
    "Submarine": "S",
    "Destroyer": "D",
}


def board_legend(*, show_ships: bool = True) -> Text:
    parts: list[str] = []
    if show_ships:
        parts.append("[bold green]C B R S D[/] ships")
        parts.append("[bold yellow]yellow[/] selected")
    parts.extend(
        [
            "[dim].[/] empty",
            "[bold blue]o[/] miss",
            "[bold red]X[/] hit",
            "[bold magenta]X[/] sunk",
        ]
    )
    return Text.from_markup("  ".join(parts))


def _mark_style(
    kind: ShotResultKind | None, *, ship: bool, selected: bool = False
) -> str:
    if kind == "miss":
        return "bold blue"
    if kind == "hit":
        return "bold red"
    if kind == "sunk":
        return "bold magenta"
    if selected:
        return "bold yellow"
    if ship:
        return "bold green"
    return "dim"


def _cell_glyph(
    coord: Coordinate,
    *,
    ship_at: dict[Coordinate, str],
    marks: dict[Coordinate, ShotResultKind],
    show_ships: bool,
    selected: str | None,
) -> Text:
    kind = marks.get(coord)
    ship_name = ship_at.get(coord)
    if kind == "miss":
        glyph = "o"
    elif kind in ("hit", "sunk"):
        glyph = "X"
    elif show_ships and ship_name is not None:
        glyph = SHIP_GLYPH.get(ship_name, "#")
    else:
        glyph = "."
    return Text(
        glyph,
        style=_mark_style(
            kind,
            ship=show_ships and ship_name is not None,
            selected=selected is not None and ship_name == selected,
        ),
    )


def render_board(
    title: str,
    *,
    ship_at: dict[Coordinate, str],
    marks: dict[Coordinate, ShotResultKind],
    show_ships: bool,
    selected: str | None = None,
) -> Table:
    table = Table(title=title, show_header=True, box=None, pad_edge=False)
    table.add_column(" ", justify="right")
    for col in COLUMNS:
        table.add_column(col, justify="center", width=2)
    for row in ROWS:
        cells = [
            _cell_glyph(
                Coordinate(col, row),
                ship_at=ship_at,
                marks=marks,
                show_ships=show_ships,
                selected=selected,
            )
            for col in COLUMNS
        ]
        table.add_row(str(row), *cells)
    return table


def _ship_at_from_placement(placement: Placement) -> dict[Coordinate, str]:
    return {
        cell: name for name, cells in placement.ships.items() for cell in cells
    }


def own_board_renderable(
    placement: Placement,
    marks: dict[Coordinate, ShotResultKind],
    *,
    selected: str | None = None,
) -> Table:
    return render_board(
        "Your fleet",
        ship_at=_ship_at_from_placement(placement),
        marks=marks,
        show_ships=True,
        selected=selected,
    )


def tracking_board_renderable(
    marks: dict[Coordinate, ShotResultKind],
    revealed: frozenset[Coordinate],
) -> Table:
    # Revealed sunk cells are known occupied, but Ship names are not shown here.
    ship_at = {cell: "sunk" for cell in revealed}
    return render_board(
        "Opponent — your shots",
        ship_at=ship_at,
        marks=marks,
        show_ships=True,
    )


def render_match_boards(
    console: Console,
    placement: Placement,
    own_marks: dict[Coordinate, ShotResultKind],
    tracking_marks: dict[Coordinate, ShotResultKind],
    revealed: frozenset[Coordinate],
) -> None:
    group: RenderableType = Group(
        own_board_renderable(placement, own_marks),
        board_legend(show_ships=True),
        Text(""),
        tracking_board_renderable(tracking_marks, revealed),
    )
    console.print(group)
