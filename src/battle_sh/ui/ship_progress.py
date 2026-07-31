"""Per-ship progress rows for Combat sidebar tables (honest enemy data)."""

from __future__ import annotations

from battle_sh.rules.board import ShotResultKind
from battle_sh.rules.placement import (
    STANDARD_FLEET_LENGTHS,
    Coordinate,
    Placement,
)

ShipRow = tuple[str, str, str]  # name, progress, status


def your_ship_rows(
    placement: Placement, own_marks: dict[Coordinate, ShotResultKind]
) -> tuple[ShipRow, ...]:
    """Your fleet: hits/length and afloat/sunk from incoming marks."""
    rows: list[ShipRow] = []
    for name, length in STANDARD_FLEET_LENGTHS.items():
        cells = placement.ships[name]
        hits = sum(1 for c in cells if own_marks.get(c) in ("hit", "sunk"))
        if hits >= length:
            rows.append((name, f"{length}/{length}", "sunk"))
        else:
            rows.append((name, f"{hits}/{length}", "afloat"))
    return tuple(rows)


def enemy_ship_rows(enemy_sunk: tuple[str, ...] | list[str]) -> tuple[ShipRow, ...]:
    """Enemy fleet: full progress only after sink; otherwise unknown."""
    sunk = set(enemy_sunk)
    rows: list[ShipRow] = []
    for name, length in STANDARD_FLEET_LENGTHS.items():
        if name in sunk:
            rows.append((name, f"{length}/{length}", "sunk"))
        else:
            rows.append((name, f"—/{length}", "unknown"))
    return tuple(rows)
