"""Placement validity and Placement Commitment for the Standard Fleet."""

from __future__ import annotations

import hashlib
import json
import random
from dataclasses import dataclass
from typing import Literal


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


Orientation = Literal["H", "V"]


def ship_cells_from_bow(
    bow: Coordinate, length: int, orientation: Orientation
) -> frozenset[Coordinate]:
    if orientation == "H":
        start = COLUMNS.index(bow.column)
        if start + length > len(COLUMNS):
            raise IllegalPlacementError(f"Ship from {bow} runs off the Board")
        return frozenset(
            coordinate(COLUMNS[start + i], bow.row) for i in range(length)
        )
    if bow.row + length - 1 > 10:
        raise IllegalPlacementError(f"Ship from {bow} runs off the Board")
    return frozenset(coordinate(bow.column, bow.row + i) for i in range(length))


def ship_bow_and_orientation(
    cells: frozenset[Coordinate],
) -> tuple[Coordinate, Orientation]:
    ordered = sorted(cells)
    columns = {c.column for c in ordered}
    if len(columns) == 1:
        return ordered[0], "V"
    return ordered[0], "H"


def _replace_ship(placement: Placement, name: str, cells: frozenset[Coordinate]) -> Placement:
    ships = dict(placement.ships)
    ships[name] = cells
    updated = Placement(ships)
    validate_placement(updated)
    return updated


def translate_ship(
    placement: Placement, name: str, *, column_delta: int, row_delta: int
) -> Placement:
    """Move a Ship by column/row deltas, keeping orientation. Raises if illegal."""
    if name not in placement.ships:
        raise IllegalPlacementError(f"Unknown Ship: {name}")
    bow, orientation = ship_bow_and_orientation(placement.ships[name])
    new_col_idx = COLUMNS.index(bow.column) + column_delta
    new_row = bow.row + row_delta
    if new_col_idx < 0 or new_col_idx >= len(COLUMNS) or new_row not in ROWS:
        raise IllegalPlacementError(f"Moving {name} would leave the Board")
    new_bow = coordinate(COLUMNS[new_col_idx], new_row)
    length = STANDARD_FLEET_LENGTHS[name]
    return _replace_ship(
        placement, name, ship_cells_from_bow(new_bow, length, orientation)
    )


def rotate_ship(placement: Placement, name: str) -> Placement:
    """Rotate a Ship around its bow (H↔V). Raises if the result is illegal."""
    if name not in placement.ships:
        raise IllegalPlacementError(f"Unknown Ship: {name}")
    bow, orientation = ship_bow_and_orientation(placement.ships[name])
    flipped: Orientation = "V" if orientation == "H" else "H"
    length = STANDARD_FLEET_LENGTHS[name]
    return _replace_ship(
        placement, name, ship_cells_from_bow(bow, length, flipped)
    )


def random_placement(rng: random.Random | None = None) -> Placement:
    """Produce a legal random Standard Fleet Placement."""
    rng = rng or random.Random()
    names = sorted(
        STANDARD_FLEET_LENGTHS, key=lambda n: STANDARD_FLEET_LENGTHS[n], reverse=True
    )
    for _ in range(500):
        ships: dict[str, frozenset[Coordinate]] = {}
        occupied: set[Coordinate] = set()
        failed = False
        for name in names:
            length = STANDARD_FLEET_LENGTHS[name]
            candidates: list[frozenset[Coordinate]] = []
            for col in COLUMNS:
                for row in ROWS:
                    for orientation in ("H", "V"):
                        try:
                            cells = ship_cells_from_bow(
                                coordinate(col, row),
                                length,
                                orientation,
                            )
                        except IllegalPlacementError:
                            continue
                        if occupied & cells:
                            continue
                        candidates.append(cells)
            if not candidates:
                failed = True
                break
            chosen = rng.choice(candidates)
            ships[name] = chosen
            occupied |= set(chosen)
        if failed:
            continue
        placement = Placement(ships)
        validate_placement(placement)
        return placement
    raise RuntimeError("Could not generate a legal random Placement")
