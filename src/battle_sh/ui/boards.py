"""rich Board and Tracking Board rendering (color-coded hit/miss/sunk)."""

from __future__ import annotations

from battle_sh.rules.board import ShotResultKind
from battle_sh.rules.placement import COLUMNS, ROWS, Coordinate, Placement
from rich.console import Console, Group, RenderableType
from rich.table import Table
from rich.text import Text


def _mark_style(kind: ShotResultKind | None, *, ship: bool) -> str:
    if kind == "miss":
        return "bold blue"
    if kind == "hit":
        return "bold red"
    if kind == "sunk":
        return "bold magenta"
    if ship:
        return "bold green"
    return "dim"


def _cell_glyph(
    coord: Coordinate,
    *,
    ships: frozenset[Coordinate],
    marks: dict[Coordinate, ShotResultKind],
    show_ships: bool,
) -> Text:
    kind = marks.get(coord)
    on_ship = coord in ships
    if kind == "miss":
        glyph = "o"
    elif kind in ("hit", "sunk"):
        glyph = "X"
    elif show_ships and on_ship:
        glyph = "#"
    else:
        glyph = "."
    return Text(glyph, style=_mark_style(kind, ship=show_ships and on_ship))


def render_board(
    title: str,
    *,
    ships: frozenset[Coordinate],
    marks: dict[Coordinate, ShotResultKind],
    show_ships: bool,
) -> Table:
    table = Table(title=title, show_header=True, box=None, pad_edge=False)
    table.add_column(" ", justify="right")
    for col in COLUMNS:
        table.add_column(col, justify="center", width=2)
    for row in ROWS:
        cells = [
            _cell_glyph(
                Coordinate(col, row),
                ships=ships,
                marks=marks,
                show_ships=show_ships,
            )
            for col in COLUMNS
        ]
        table.add_row(str(row), *cells)
    return table


def own_board_renderable(
    placement: Placement,
    marks: dict[Coordinate, ShotResultKind],
) -> Table:
    ships = frozenset(c for cells in placement.ships.values() for c in cells)
    return render_board("Your Board", ships=ships, marks=marks, show_ships=True)


def tracking_board_renderable(
    marks: dict[Coordinate, ShotResultKind],
    revealed: frozenset[Coordinate],
) -> Table:
    return render_board(
        "Tracking Board",
        ships=revealed,
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
        Text(""),
        tracking_board_renderable(tracking_marks, revealed),
    )
    console.print(group)
