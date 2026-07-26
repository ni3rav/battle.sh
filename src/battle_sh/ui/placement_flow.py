"""Immediate-key Placement driven by an injectable KeySource (key-rule seam)."""

from __future__ import annotations

import random
from collections.abc import Callable
from typing import Literal

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
from battle_sh.ui.keys import MOVE_DELTA, Key, KeySource, key_token
from battle_sh.ui.quit_arm import QUIT_WARN, QuitArm

_SHIP_ORDER = tuple(STANDARD_FLEET_LENGTHS)
_SHIP_BY_INDEX = {str(i): name for i, name in enumerate(_SHIP_ORDER, start=1)}

_PlacementAction = Literal["continue", "lock", "quit"]


class QuitRequested(Exception):
    """Player asked to leave the Match (Ctrl+C)."""


def apply_placement_key(
    key: Key,
    placement: Placement,
    selected: str | None,
    *,
    factory: Callable[[], Placement],
    arm: QuitArm | None,
) -> tuple[Placement, str | None, _PlacementAction, str | None]:
    """Pure per-key Placement transition shared by drivers and the Textual screen.

    Returns the next ``placement`` and ``selected``, the control ``action``, and
    an optional status ``message`` to emit.
    """
    token = key_token(key)
    if key.is_interrupt:
        if arm is None or arm.handle_interrupt() == "confirm":
            return placement, selected, "quit", None
        return placement, selected, "continue", QUIT_WARN
    if token == "y":
        validate_placement(placement)
        return placement, selected, "lock", None
    if token == "t":
        return factory(), None, "continue", "New random layout."
    if token in _SHIP_BY_INDEX:
        chosen = _SHIP_BY_INDEX[token]
        return placement, chosen, "continue", f"Selected {chosen}."
    if token == "tab":
        chosen = _cycle_ship(selected, step=1)
        return placement, chosen, "continue", f"Selected {chosen}."
    if token == "shift+tab":
        chosen = _cycle_ship(selected, step=-1)
        return placement, chosen, "continue", f"Selected {chosen}."
    if token in {"e", "r"}:
        if selected is None:
            return placement, selected, "continue", "Select a ship first (1-5)."
        try:
            return rotate_ship(placement, selected), selected, "continue", None
        except IllegalPlacementError:
            return placement, selected, "continue", "Can't rotate there."
    if token in MOVE_DELTA:
        if selected is None:
            return placement, selected, "continue", "Select a ship first (1-5)."
        delta = MOVE_DELTA[token]
        try:
            moved = translate_ship(
                placement, selected, column_delta=delta[0], row_delta=delta[1]
            )
            return moved, selected, "continue", None
        except IllegalPlacementError:
            return placement, selected, "continue", "Can't move there."
    return placement, selected, "continue", None


def run_placement(
    keys: KeySource,
    *,
    on_message: Callable[[str], None] | None = None,
    placement_factory: Callable[[], Placement] | None = None,
    rng: random.Random | None = None,
    clock: Clock | None = None,
) -> Placement:
    """Scripted Placement via immediate keys until lock (key-rule tests)."""
    factory = placement_factory or (lambda: random_placement(rng))
    placement = factory()
    selected: str | None = None
    arm = QuitArm(clock) if clock is not None else None

    while True:
        if arm is not None:
            arm.expire_if_due()
        key = keys.read()
        placement, selected, action, message = apply_placement_key(
            key,
            placement,
            selected,
            factory=factory,
            arm=arm,
        )
        if message is not None and on_message is not None:
            on_message(message)
        if action == "quit":
            raise QuitRequested
        if action == "lock":
            return placement


def _cycle_ship(selected: str | None, *, step: int) -> str:
    if selected is None or selected not in _SHIP_ORDER:
        return _SHIP_ORDER[0 if step > 0 else -1]
    idx = _SHIP_ORDER.index(selected)
    return _SHIP_ORDER[(idx + step) % len(_SHIP_ORDER)]
