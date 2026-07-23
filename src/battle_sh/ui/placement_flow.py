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
from battle_sh.ui.keys import Key, KeySource
from battle_sh.ui.shell import placement_frame
from rich.console import Console
from rich.live import Live

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


def run_placement(
    keys: KeySource,
    *,
    console: Console | None = None,
    on_message: Callable[[str], None] | None = None,
    placement_factory: Callable[[], Placement] | None = None,
    rng: random.Random | None = None,
) -> Placement:
    """Interactive Placement via immediate keys until the Player locks.

    With a ``console``, redraws a fixed three-band Live frame in place.
    Without one, only KeySource + ``on_message`` drive the session (tests).
    """
    factory = placement_factory or (lambda: random_placement(rng))
    placement = factory()
    selected: str | None = None
    status = ""

    def emit(text: str) -> None:
        nonlocal status
        status = text
        if on_message is not None:
            on_message(text)

    def frame():
        return placement_frame(
            placement=placement,
            selected=selected,
            status=status,
        )

    def loop(live: Live | None) -> Placement:
        nonlocal placement, selected
        while True:
            if live is not None:
                live.update(frame(), refresh=True)
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

    if console is None:
        return loop(None)

    with Live(
        frame(),
        console=console,
        auto_refresh=False,
        transient=False,
    ) as live:
        return loop(live)


def _key_token(key: Key) -> str:
    if key.name == "shift+tab":
        return "shift+tab"
    return key.name.lower()


def _cycle_ship(selected: str | None, *, step: int) -> str:
    if selected is None or selected not in _SHIP_ORDER:
        return _SHIP_ORDER[0 if step > 0 else -1]
    idx = _SHIP_ORDER.index(selected)
    return _SHIP_ORDER[(idx + step) % len(_SHIP_ORDER)]
