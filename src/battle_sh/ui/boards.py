"""rich Board and Tracking Board rendering (theme-aware glyphs)."""

from __future__ import annotations

from dataclasses import dataclass

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

EMPTY_GLYPH = "·"
MISS_GLYPH = "○"
HIT_GLYPH = "●"
SUNK_GLYPH = "■"
AIM_GLYPH = "╋"


@dataclass(frozen=True)
class BoardPalette:
    """Rich style strings for board cells (usually hex from a Textual Theme)."""

    empty: str = "dim"
    ship: str = "bold #4EBF71"
    selected: str = "bold #ffa62b"
    miss: str = "bold #0178D4"
    hit: str = "bold #ba3c5b"
    sunk: str = "bold #ffa62b"
    aim: str = "bold reverse #ffa62b"


DEFAULT_PALETTE = BoardPalette()


def palette_from_colors(
    *,
    primary: str,
    success: str,
    error: str,
    warning: str,
    accent: str,
    foreground: str | None = None,
) -> BoardPalette:
    """Build a BoardPalette from Textual Theme color tokens."""
    muted = f"dim {foreground}" if foreground else "dim"
    return BoardPalette(
        empty=muted,
        ship=f"bold {success}",
        selected=f"bold {accent}",
        miss=f"bold {primary}",
        hit=f"bold {error}",
        sunk=f"bold {warning}",
        aim=f"bold reverse {accent}",
    )


def board_legend(*, show_ships: bool = True, palette: BoardPalette = DEFAULT_PALETTE) -> Text:
    parts: list[str] = []
    if show_ships:
        parts.append(f"[{palette.ship}]C B R S D[/] ships")
        parts.append(f"[{palette.selected}]selected[/]")
    parts.extend(
        [
            f"[{palette.empty}]{EMPTY_GLYPH}[/] empty",
            f"[{palette.miss}]{MISS_GLYPH}[/] miss",
            f"[{palette.hit}]{HIT_GLYPH}[/] hit",
            f"[{palette.sunk}]{SUNK_GLYPH}[/] sunk",
        ]
    )
    return Text.from_markup("  ".join(parts))


def _mark_style(
    kind: ShotResultKind | None,
    *,
    ship: bool,
    selected: bool = False,
    palette: BoardPalette,
) -> str:
    if kind == "miss":
        return palette.miss
    if kind == "hit":
        return palette.hit
    if kind == "sunk":
        return palette.sunk
    if selected:
        return palette.selected
    if ship:
        return palette.ship
    return palette.empty


def _cell_glyph(
    coord: Coordinate,
    *,
    ship_at: dict[Coordinate, str],
    marks: dict[Coordinate, ShotResultKind],
    show_ships: bool,
    selected: str | None,
    aim: Coordinate | None = None,
    palette: BoardPalette = DEFAULT_PALETTE,
) -> Text:
    kind = marks.get(coord)
    ship_name = ship_at.get(coord)
    is_aim = aim is not None and coord == aim
    if kind == "miss":
        glyph = MISS_GLYPH
    elif kind == "hit":
        glyph = HIT_GLYPH
    elif kind == "sunk":
        glyph = SUNK_GLYPH
    elif show_ships and ship_name is not None:
        glyph = SHIP_GLYPH.get(ship_name, "#")
    elif is_aim:
        glyph = AIM_GLYPH
    else:
        glyph = EMPTY_GLYPH
    if is_aim:
        style = palette.aim
    else:
        style = _mark_style(
            kind,
            ship=show_ships and ship_name is not None,
            selected=selected is not None and ship_name == selected,
            palette=palette,
        )
    return Text(glyph, style=style)


def render_board(
    title: str,
    *,
    ship_at: dict[Coordinate, str],
    marks: dict[Coordinate, ShotResultKind],
    show_ships: bool,
    selected: str | None = None,
    aim: Coordinate | None = None,
    palette: BoardPalette = DEFAULT_PALETTE,
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
                aim=aim,
                palette=palette,
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
    palette: BoardPalette = DEFAULT_PALETTE,
) -> Table:
    return render_board(
        "Your fleet",
        ship_at=_ship_at_from_placement(placement),
        marks=marks,
        show_ships=True,
        selected=selected,
        palette=palette,
    )


def tracking_board_renderable(
    marks: dict[Coordinate, ShotResultKind],
    revealed: frozenset[Coordinate],
    *,
    aim: Coordinate | None = None,
    palette: BoardPalette = DEFAULT_PALETTE,
) -> Table:
    # Revealed sunk cells are known occupied, but Ship names are not shown here.
    ship_at = {cell: "sunk" for cell in revealed}
    title = "Opponent — Aim" if aim is not None else "Opponent — your shots"
    return render_board(
        title,
        ship_at=ship_at,
        marks=marks,
        show_ships=True,
        aim=aim,
        palette=palette,
    )


def render_match_boards(
    console: Console,
    placement: Placement,
    own_marks: dict[Coordinate, ShotResultKind],
    tracking_marks: dict[Coordinate, ShotResultKind],
    revealed: frozenset[Coordinate],
    *,
    palette: BoardPalette = DEFAULT_PALETTE,
) -> None:
    group: RenderableType = Group(
        own_board_renderable(placement, own_marks, palette=palette),
        board_legend(show_ships=True, palette=palette),
        Text(""),
        tracking_board_renderable(tracking_marks, revealed, palette=palette),
    )
    console.print(group)
