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
from battle_sh.ui.clock import Clock
from battle_sh.ui.keys import MOVE_DELTA, KeySource, key_token
from battle_sh.ui.quit_arm import CTRL_C_WARN, QuitArm
from battle_sh.ui.shell import placement_frame
from rich.console import Console
from rich.live import Live

_SHIP_ORDER = tuple(STANDARD_FLEET_LENGTHS)
_SHIP_BY_INDEX = {str(i): name for i, name in enumerate(_SHIP_ORDER, start=1)}


class QuitRequested(Exception):
    """Player asked to leave the Match (q)."""


def run_placement(
    keys: KeySource,
    *,
    console: Console | None = None,
    on_message: Callable[[str], None] | None = None,
    placement_factory: Callable[[], Placement] | None = None,
    rng: random.Random | None = None,
    top_info: Callable[[], str] | None = None,
    clock: Clock | None = None,
) -> Placement:
    """Interactive Placement via immediate keys until the Player locks.

    With a ``console``, redraws a fixed three-band Live frame in place.
    Without one, only KeySource + ``on_message`` drive the session (tests).
    """
    factory = placement_factory or (lambda: random_placement(rng))
    placement = factory()
    selected: str | None = None
    status = ""
    arm = QuitArm(clock) if clock is not None else None

    def emit(text: str) -> None:
        nonlocal status
        status = text
        if on_message is not None:
            on_message(text)

    def frame():
        info = top_info() if top_info is not None else "Phase: Placement"
        return placement_frame(
            placement=placement,
            selected=selected,
            status=status,
            top_info=info,
        )

    def loop(live: Live | None) -> Placement:
        nonlocal placement, selected
        while True:
            if arm is not None:
                arm.expire_if_due()
            if live is not None:
                live.update(frame(), refresh=True)
            key = keys.read()
            token = key_token(key)

            if token == "q":
                raise QuitRequested
            if key.is_interrupt:
                if arm is None or arm.handle_interrupt() == "confirm":
                    raise QuitRequested
                emit(CTRL_C_WARN)
                continue
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
            if token in MOVE_DELTA:
                if selected is None:
                    emit("Select a ship first (1-5).")
                    continue
                delta = MOVE_DELTA[token]
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

    tick_clock = top_info is not None
    with Live(
        console=console,
        auto_refresh=tick_clock,
        refresh_per_second=1,
        transient=False,
        get_renderable=frame,
    ) as live:
        return loop(live)


def _cycle_ship(selected: str | None, *, step: int) -> str:
    if selected is None or selected not in _SHIP_ORDER:
        return _SHIP_ORDER[0 if step > 0 else -1]
    idx = _SHIP_ORDER.index(selected)
    return _SHIP_ORDER[(idx + step) % len(_SHIP_ORDER)]
