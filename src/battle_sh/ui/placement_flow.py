"""Keyboard-driven Placement: random default, re-roll, adjust, lock."""

from __future__ import annotations

import random
from collections.abc import Callable

from battle_sh.rules.placement import (
    STANDARD_FLEET_LENGTHS,
    IllegalPlacementError,
    Placement,
    random_placement,
    rotate_ship,
    translate_ship,
)
from battle_sh.ui.boards import SHIP_GLYPH, board_legend, own_board_renderable
from rich.console import Console

_SHIP_ORDER = tuple(STANDARD_FLEET_LENGTHS)
_SHIP_BY_LOWER = {name.lower(): name for name in STANDARD_FLEET_LENGTHS}
_SHIP_BY_INDEX = {str(i): name for i, name in enumerate(_SHIP_ORDER, start=1)}
_MOVE_DELTA = {
    "w": (0, -1),
    "a": (-1, 0),
    "x": (0, 1),
    "d": (1, 0),
    "up": (0, -1),
    "left": (-1, 0),
    "down": (0, 1),
    "right": (1, 0),
}

class QuitRequested(Exception):
    """Player asked to leave the Match (q / quit)."""


HELP = """Place your ships (a random layout is ready).

  r                 new random layout
  1-5  or  s <Ship> select a ship (see list below)
  w/a/x/d           move selected ship  (also: up / left / down / right)
  o                 rotate selected ship
  l                 lock this layout and continue
  q                 quit
  h                 show this help

Ships: """ + "  ".join(
    f"{i}={name}({length}/{SHIP_GLYPH[name]})"
    for i, (name, length) in enumerate(STANDARD_FLEET_LENGTHS.items(), start=1)
)


def _ship_list_line() -> str:
    return "  ".join(
        f"[{i}] {name} ({length})={SHIP_GLYPH[name]}"
        for i, (name, length) in enumerate(STANDARD_FLEET_LENGTHS.items(), start=1)
    )


def _resolve_ship(token: str) -> str | None:
    if token in _SHIP_BY_INDEX:
        return _SHIP_BY_INDEX[token]
    return _SHIP_BY_LOWER.get(token.lower())


def run_placement(
    console: Console,
    ask: Callable[[str], str],
    *,
    placement_factory: Callable[[], Placement] | None = None,
    rng: random.Random | None = None,
) -> Placement:
    """Interactive Placement until the Player locks a legal layout."""
    factory = placement_factory or (lambda: random_placement(rng))
    placement = factory()
    selected: str | None = None

    console.print(
        "Place your ships. A random layout is ready — lock it, re-roll, or adjust."
    )
    console.print(HELP)

    while True:
        console.print(own_board_renderable(placement, {}, selected=selected))
        console.print(board_legend(show_ships=True))
        console.print(_ship_list_line())
        if selected:
            console.print(
                f"Selected: [bold yellow]{selected}[/]  "
                f"— move [bold]w/a/x/d[/] (or up/left/down/right), "
                f"rotate [bold]o[/], lock [bold]l[/], quit [bold]q[/]"
            )
        else:
            console.print(
                "No ship selected — type [bold]1-5[/] (or [bold]s Carrier[/]), "
                "then move it. Ready? [bold]l[/] lock · [bold]q[/] quit."
            )
        raw = ask("Placement> ").strip()
        if not raw:
            continue
        parts = raw.split()
        cmd = parts[0].lower()

        if cmd in {"h", "help", "?"}:
            console.print(HELP)
            continue
        if cmd in {"q", "quit", "exit"}:
            raise QuitRequested
        if cmd in {"r", "reroll"}:
            placement = factory() if placement_factory else random_placement(rng)
            selected = None
            console.print("New random layout.")
            continue
        if cmd in _SHIP_BY_INDEX and len(parts) == 1:
            selected = _SHIP_BY_INDEX[cmd]
            console.print(f"Selected {selected}.")
            continue
        if cmd in {"s", "select"}:
            if len(parts) < 2:
                console.print("Usage: s <Ship>  or just 1-5")
                continue
            name = _resolve_ship(parts[1])
            if name is None:
                console.print(f"Unknown ship: {parts[1]!r} — try 1-5 or a name")
                continue
            selected = name
            console.print(f"Selected {selected}.")
            continue
        if cmd in {"l", "lock"}:
            return placement
        if cmd in {"o", "rotate"}:
            if selected is None:
                console.print("Select a ship first (1-5).")
                continue
            try:
                placement = rotate_ship(placement, selected)
            except IllegalPlacementError as exc:
                console.print(f"Can't rotate there: {exc}")
            continue
        if cmd in _MOVE_DELTA:
            if selected is None:
                console.print("Select a ship first (1-5).")
                continue
            delta = _MOVE_DELTA[cmd]
            try:
                placement = translate_ship(
                    placement,
                    selected,
                    column_delta=delta[0],
                    row_delta=delta[1],
                )
            except IllegalPlacementError as exc:
                console.print(f"Can't move there: {exc}")
            continue
        console.print(f"Unknown command: {raw!r} — type h for help")
