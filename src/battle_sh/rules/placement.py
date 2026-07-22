"""Placement validity and Placement Commitment for the Standard Fleet."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass


COLUMNS = "ABCDEFGHIJ"
ROWS = range(1, 11)

STANDARD_FLEET_LENGTHS: dict[str, int] = {
    "Carrier": 5,
    "Battleship": 4,
    "Cruiser": 3,
    "Submarine": 3,
    "Destroyer": 2,
}


class IllegalPlacementError(Exception):
    """Raised when a Placement cannot be locked under classic rules."""


@dataclass(frozen=True, order=True)
class Coordinate:
    column: str
    row: int

    def __str__(self) -> str:
        return f"{self.column}{self.row}"


def coordinate(column: str, row: int) -> Coordinate:
    if column not in COLUMNS:
        raise ValueError(f"Column must be A–J, got {column!r}")
    if row not in ROWS:
        raise ValueError(f"Row must be 1–10, got {row!r}")
    return Coordinate(column=column, row=row)


@dataclass(frozen=True)
class Placement:
    ships: dict[str, frozenset[Coordinate]]


def _cells_are_orthogonal_run(cells: frozenset[Coordinate], length: int) -> bool:
    if len(cells) != length:
        return False
    ordered = sorted(cells)
    columns = {c.column for c in ordered}
    rows = {c.row for c in ordered}
    if len(columns) == 1 and len(rows) == length:
        row_nums = [c.row for c in ordered]
        return row_nums == list(range(row_nums[0], row_nums[0] + length))
    if len(rows) == 1 and len(columns) == length:
        col_idxs = [COLUMNS.index(c.column) for c in ordered]
        return col_idxs == list(range(col_idxs[0], col_idxs[0] + length))
    return False


def validate_placement(placement: Placement) -> None:
    if set(placement.ships) != set(STANDARD_FLEET_LENGTHS):
        raise IllegalPlacementError("Placement must include exactly the Standard Fleet")

    occupied: set[Coordinate] = set()
    for name, length in STANDARD_FLEET_LENGTHS.items():
        cells = placement.ships[name]
        for cell in cells:
            if cell.column not in COLUMNS or cell.row not in ROWS:
                raise IllegalPlacementError(
                    f"{name} has Coordinate off the Board: {cell}"
                )
        if not _cells_are_orthogonal_run(cells, length):
            raise IllegalPlacementError(
                f"{name} must occupy {length} contiguous orthogonal cells"
            )
        if occupied & cells:
            raise IllegalPlacementError("Ships must not overlap")
        occupied |= set(cells)


def placement_commitment(placement: Placement) -> str:
    """SHA-256 hex digest of a canonical Placement encoding."""
    validate_placement(placement)
    canonical = {
        name: sorted(str(c) for c in placement.ships[name])
        for name in sorted(placement.ships)
    }
    payload = json.dumps(canonical, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()
