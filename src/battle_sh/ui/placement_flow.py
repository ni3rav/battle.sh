"""Immediate-key Placement driven by an injectable KeySource."""

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
    validate_placement,
)
from battle_sh.ui.boards import SHIP_GLYPH, board_legend, own_board_renderable
from battle_sh.ui.keys import Key, KeySource
from rich.console import Console

_SHIP_ORDER = tuple(STANDARD_FLEET_LENGTHS)
_SHIP_BY_INDEX = {str(i): name for i, name in enumerate(_SHIP_ORDER, start=1)}
_MOVE_DELTA = {
    "w": (0, -1),
    "a": (-1, 0),
    "s": (0, 1),
    "d": (1, 0),
    "up": (0, -1),
    "left": (-1, 0),
    "down": (0, 1),
    "right": (1, 0),
}


class QuitRequested(Exception):
    """Player asked to leave the Match (q)."""


HELP = """Place your ships (a random layout is ready).

  t                 new random layout
  1-5               select a ship
  tab / shift+tab   cycle ship selection
  w/a/s/d           move selected ship  (also: arrows)
  e / r             flip selected ship orientation
  y                 lock this layout and continue
  q                 quit
"""


def run_placement(
    keys: KeySource,
    *,
    console: Console | None = None,
    on_message: Callable[[str], None] | None = None,
    placement_factory: Callable[[], Placement] | None = None,
    rng: random.Random | None = None,
) -> Placement:
    """Interactive Placement via immediate keys until the Player locks."""
    factory = placement_factory or (lambda: random_placement(rng))
    placement = factory()
    selected: str | None = None

    def emit(text: str) -> None:
        if on_message is not None:
            on_message(text)
        elif console is not None:
            console.print(text)

    def redraw() -> None:
        if console is None:
            return
        console.print(own_board_renderable(placement, {}, selected=selected))
        console.print(board_legend(show_ships=True))
        console.print(
            "  ".join(
                f"[{i}] {name} ({length})={SHIP_GLYPH[name]}"
                for i, (name, length) in enumerate(
                    STANDARD_FLEET_LENGTHS.items(), start=1
                )
            )
        )
        if selected:
            console.print(f"Selected: [bold yellow]{selected}[/]")
        else:
            console.print("No ship selected — press [bold]1-5[/] or [bold]tab[/].")

    if console is not None:
        console.print(
            "Place your ships. A random layout is ready — lock it, re-roll, or adjust."
        )
        console.print(HELP)

    while True:
        redraw()
        key = keys.read()
        token = _key_token(key)

        if token == "q":
            raise QuitRequested
        if token == "y":
            validate_placement(placement)
            return placement
        if token == "t":
            placement = factory()
            selected = None
            emit("New random layout.")
            continue
        if token in _SHIP_BY_INDEX:
            selected = _SHIP_BY_INDEX[token]
            emit(f"Selected {selected}.")
            continue
        if token == "tab":
            selected = _cycle_ship(selected, step=1)
            emit(f"Selected {selected}.")
            continue
        if token == "shift+tab":
            selected = _cycle_ship(selected, step=-1)
            emit(f"Selected {selected}.")
            continue
        if token in {"e", "r"}:
            if selected is None:
                emit("Select a ship first (1-5).")
                continue
            try:
                placement = rotate_ship(placement, selected)
            except IllegalPlacementError:
                emit("Can't rotate there.")
            continue
        if token in _MOVE_DELTA:
            if selected is None:
                emit("Select a ship first (1-5).")
                continue
            delta = _MOVE_DELTA[token]
            try:
                placement = translate_ship(
                    placement,
                    selected,
                    column_delta=delta[0],
                    row_delta=delta[1],
                )
            except IllegalPlacementError:
                emit("Can't move there.")
            continue


def _key_token(key: Key) -> str:
    if key.name == "shift+tab":
        return "shift+tab"
    return key.name.lower()


def _cycle_ship(selected: str | None, *, step: int) -> str:
    if selected is None or selected not in _SHIP_ORDER:
        return _SHIP_ORDER[0 if step > 0 else -1]
    idx = _SHIP_ORDER.index(selected)
    return _SHIP_ORDER[(idx + step) % len(_SHIP_ORDER)]
