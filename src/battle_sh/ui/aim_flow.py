"""Immediate-key Aim driven by an injectable KeySource."""

from __future__ import annotations

from collections.abc import Callable

from battle_sh.rules.placement import COLUMNS, ROWS, Coordinate, coordinate
from battle_sh.ui.clock import Clock
from battle_sh.ui.keys import MOVE_DELTA, KeySource, key_token
from battle_sh.ui.placement_flow import QuitRequested
from battle_sh.ui.quit_arm import CTRL_C_WARN, QuitArm
from rich.console import Console
from rich.live import Live

_FIRE_KEYS = frozenset({"f", "enter", "space"})


def run_aim(
    keys: KeySource,
    *,
    fired: frozenset[Coordinate],
    start: Coordinate | None = None,
    on_cursor: Callable[[Coordinate], None] | None = None,
    clock: Clock | None = None,
    console: Console | None = None,
    frame: Callable[[Coordinate, str], object] | None = None,
) -> Coordinate:
    """Interactive Aim via immediate keys until the Player fires.

    Cursor starts at ``start`` (last Shot) or A1, skipping already-fired
    cells. Movement skips spent Coordinates. Fire with ``f`` / Enter / Space.

    With ``console`` and ``frame``, redraws a Live combat view in place.
    """
    aim = initial_aim(start, fired)
    arm = QuitArm(clock) if clock is not None else None
    status = ""

    def loop(live: Live | None) -> Coordinate:
        nonlocal aim, status
        while True:
            if arm is not None:
                arm.expire_if_due()
            if on_cursor is not None:
                on_cursor(aim)
            if live is not None and frame is not None:
                live.update(frame(aim, status), refresh=True)  # type: ignore[arg-type]
            key = keys.read()
            token = key_token(key)

            if token == "q":
                raise QuitRequested
            if key.is_interrupt:
                if arm is None or arm.handle_interrupt() == "confirm":
                    raise QuitRequested
                status = CTRL_C_WARN
                continue
            if token in _FIRE_KEYS:
                if aim in fired:
                    status = "Already fired there."
                    continue
                return aim
            if token in MOVE_DELTA:
                delta = MOVE_DELTA[token]
                nxt = step_skipping_fired(aim, delta[0], delta[1], fired)
                if nxt is not None:
                    aim = nxt
                continue

    if console is None or frame is None:
        return loop(None)

    tick_clock = clock is not None
    with Live(
        console=console,
        auto_refresh=tick_clock,
        refresh_per_second=1,
        transient=False,
        get_renderable=lambda: frame(aim, status),  # type: ignore[arg-type, return-value]
    ) as live:
        return loop(live)


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
