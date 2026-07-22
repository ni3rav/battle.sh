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
from battle_sh.ui.boards import own_board_renderable
from rich.console import Console


HELP = """Placement commands:
  r / reroll              new random Placement
  s <Ship>                select Ship (Carrier, Battleship, Cruiser, Submarine, Destroyer)
  w/a/x/d                 move selected Ship up/left/down/right
  o / rotate              rotate selected Ship around its bow
  l / lock                lock Placement and publish Placement Commitment
  h / help                show this help
"""

_SHIP_BY_LOWER = {name.lower(): name for name in STANDARD_FLEET_LENGTHS}


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

    while True:
        console.print(own_board_renderable(placement, {}))
        if selected:
            console.print(f"Selected: {selected}")
        else:
            console.print("No Ship selected (s <Ship>).")
        console.print("Commands: r, s <Ship>, w/a/x/d, o, l, h")
        raw = ask("Placement> ").strip()
        if not raw:
            continue
        parts = raw.split()
        cmd = parts[0].lower()

        if cmd in {"h", "help", "?"}:
            console.print(HELP)
            continue
        if cmd in {"r", "reroll"}:
            placement = factory() if placement_factory else random_placement(rng)
            selected = None
            console.print("Re-rolled Placement.")
            continue
        if cmd in {"s", "select"}:
            if len(parts) < 2:
                console.print("Usage: s <Ship>")
                continue
            name = _SHIP_BY_LOWER.get(parts[1].lower())
            if name is None:
                console.print(f"Unknown Ship: {parts[1]!r}")
                continue
            selected = name
            continue
        if cmd in {"l", "lock"}:
            return placement
        if cmd in {"o", "rotate"}:
            if selected is None:
                console.print("Select a Ship first (s <Ship>).")
                continue
            try:
                placement = rotate_ship(placement, selected)
            except IllegalPlacementError as exc:
                console.print(f"Illegal rotate: {exc}")
            continue
        if cmd in {"w", "a", "x", "d"}:
            if selected is None:
                console.print("Select a Ship first (s <Ship>).")
                continue
            delta = {"w": (0, -1), "a": (-1, 0), "x": (0, 1), "d": (1, 0)}[cmd]
            try:
                placement = translate_ship(
                    placement,
                    selected,
                    column_delta=delta[0],
                    row_delta=delta[1],
                )
            except IllegalPlacementError as exc:
                console.print(f"Illegal move: {exc}")
            continue
        console.print(f"Unknown command: {raw!r} (h for help)")
