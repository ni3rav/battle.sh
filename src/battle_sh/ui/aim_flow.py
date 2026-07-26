"""Immediate-key Aim driven by an injectable KeySource (key-rule seam)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Literal

from battle_sh.rules.placement import COLUMNS, ROWS, Coordinate, coordinate
from battle_sh.ui.clock import Clock
from battle_sh.ui.keys import MOVE_DELTA, Key, KeySource, key_token
from battle_sh.ui.placement_flow import QuitRequested
from battle_sh.ui.quit_arm import QUIT_WARN, QuitArm

_FIRE_KEYS = frozenset({"f", "enter", "space"})

_AimAction = Literal["continue", "fire", "quit"]


def apply_aim_key(
    key: Key,
    aim: Coordinate,
    status: str,
    *,
    fired: frozenset[Coordinate],
    arm: QuitArm | None,
) -> tuple[Coordinate, str, _AimAction]:
    """Pure per-key Aim transition shared by drivers and the Textual screen."""
    token = key_token(key)
    if key.is_interrupt:
        if arm is None or arm.handle_interrupt() == "confirm":
            return aim, status, "quit"
        return aim, QUIT_WARN, "continue"
    if token in _FIRE_KEYS:
        if aim in fired:
            return aim, "Already fired there.", "continue"
        return aim, status, "fire"
    if token in MOVE_DELTA:
        delta = MOVE_DELTA[token]
        nxt = step_skipping_fired(aim, delta[0], delta[1], fired)
        if nxt is not None:
            return nxt, status, "continue"
    return aim, status, "continue"


def run_aim(
    keys: KeySource,
    *,
    fired: frozenset[Coordinate],
    start: Coordinate | None = None,
    on_cursor: Callable[[Coordinate], None] | None = None,
    clock: Clock | None = None,
) -> Coordinate:
    """Scripted Aim via immediate keys until the Player fires (key-rule tests)."""
    aim = initial_aim(start, fired)
    arm = QuitArm(clock) if clock is not None else None
    status = ""
    while True:
        if arm is not None:
            arm.expire_if_due()
        if on_cursor is not None:
            on_cursor(aim)
        key = keys.read()
        aim, status, action = apply_aim_key(
            key, aim, status, fired=fired, arm=arm
        )
        if action == "quit":
            raise QuitRequested
        if action == "fire":
            return aim


def initial_aim(
    start: Coordinate | None, fired: frozenset[Coordinate]
) -> Coordinate:
    """Cursor for a new Aim: ``start`` if empty, else next empty after it (wrap)."""
    preferred = start if start is not None else coordinate("A", 1)
    if preferred not in fired:
        return preferred
    cells = [coordinate(col, row) for row in ROWS for col in COLUMNS]
    start_idx = cells.index(preferred)
    for cell in cells[start_idx + 1 :] + cells[:start_idx]:
        if cell not in fired:
            return cell
    raise RuntimeError("No empty cells left to Aim")


def step_skipping_fired(
    current: Coordinate,
    column_delta: int,
    row_delta: int,
    fired: frozenset[Coordinate],
) -> Coordinate | None:
    """One Aim step in a cardinal direction, skipping already-fired cells."""
    col_i = COLUMNS.index(current.column)
    row = current.row
    while True:
        col_i += column_delta
        row += row_delta
        if col_i < 0 or col_i >= len(COLUMNS) or row not in ROWS:
            return None
        cell = coordinate(COLUMNS[col_i], row)
        if cell not in fired:
            return cell
