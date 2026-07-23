"""Immediate-key Aim driven by an injectable KeySource."""

from __future__ import annotations

from collections.abc import Callable

from battle_sh.rules.placement import COLUMNS, ROWS, Coordinate, coordinate
from battle_sh.ui.clock import Clock
from battle_sh.ui.keys import Key, KeySource
from battle_sh.ui.placement_flow import QuitRequested
from battle_sh.ui.quit_arm import CTRL_C_WARN, QuitArm
from rich.console import Console
from rich.live import Live

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
_FIRE_KEYS = frozenset({"f", "enter", "space"})


def run_aim(
    keys: KeySource,
    *,
    fired: frozenset[Coordinate],
    start: Coordinate | None = None,
    on_message: Callable[[str], None] | None = None,
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
    aim = _initial_aim(start, fired)
    arm = QuitArm(clock) if clock is not None else None
    status = ""

    def emit(text: str) -> None:
        nonlocal status
        status = text
        if on_message is not None:
            on_message(text)

    def loop(live: Live | None) -> Coordinate:
        nonlocal aim
        while True:
            if arm is not None:
                arm.expire_if_due()
            if on_cursor is not None:
                on_cursor(aim)
            if live is not None and frame is not None:
                live.update(frame(aim, status), refresh=True)  # type: ignore[arg-type]
            key = keys.read()
            token = _key_token(key)

            if token == "q":
                raise QuitRequested
            if key.is_interrupt:
                if arm is None or arm.handle_interrupt() == "confirm":
                    raise QuitRequested
                emit(CTRL_C_WARN)
                continue
            if token in _FIRE_KEYS:
                if aim in fired:
                    emit("Already fired there.")
                    continue
                return aim
            if token in _MOVE_DELTA:
                delta = _MOVE_DELTA[token]
                nxt = _step_skipping_fired(aim, delta[0], delta[1], fired)
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


def _initial_aim(
    start: Coordinate | None, fired: frozenset[Coordinate]
) -> Coordinate:
    preferred = start if start is not None else coordinate("A", 1)
    if preferred not in fired:
        return preferred
    # Last Shot is spent — resume by scanning onward from there (wrap).
    cells = [coordinate(col, row) for row in ROWS for col in COLUMNS]
    start_idx = cells.index(preferred)
    for cell in cells[start_idx + 1 :] + cells[:start_idx]:
        if cell not in fired:
            return cell
    raise RuntimeError("No empty cells left to Aim")


def _step_skipping_fired(
    current: Coordinate,
    column_delta: int,
    row_delta: int,
    fired: frozenset[Coordinate],
) -> Coordinate | None:
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


def _key_token(key: Key) -> str:
    return key.name.lower()
