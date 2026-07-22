"""Own-Board Shot resolution (split authority — never runs on the Relay)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from battle_sh.rules.placement import (
    COLUMNS,
    ROWS,
    Coordinate,
    Placement,
    coordinate,
    validate_placement,
)

ShotResultKind = Literal["miss", "hit", "sunk"]


class IllegalShotError(Exception):
    """Raised for Coordinates that are off-board or otherwise illegal."""


class DuplicateShotError(Exception):
    """Raised when a Coordinate has already been fired."""


def parse_coordinate(text: str) -> Coordinate:
    raw = text.strip().upper()
    if len(raw) < 2:
        raise IllegalShotError(f"Illegal Coordinate: {text!r}")
    column, row_text = raw[0], raw[1:]
    if column not in COLUMNS or not row_text.isdigit():
        raise IllegalShotError(f"Illegal Coordinate: {text!r}")
    row = int(row_text)
    if row not in ROWS:
        raise IllegalShotError(f"Illegal Coordinate: {text!r}")
    return coordinate(column, row)


@dataclass(frozen=True)
class ShotAnswer:
    coordinate: Coordinate
    result: ShotResultKind
    ship: str | None = None

    @property
    def coordinate_text(self) -> str:
        return str(self.coordinate)


class Board:
    """One Player's Board: Placement plus record of incoming Shots."""

    def __init__(self, placement: Placement) -> None:
        validate_placement(placement)
        self._placement = placement
        self._remaining: dict[str, set[Coordinate]] = {
            name: set(cells) for name, cells in placement.ships.items()
        }
        self._incoming: set[Coordinate] = set()

    @property
    def placement(self) -> Placement:
        return self._placement

    @property
    def fleet_destroyed(self) -> bool:
        return not self._remaining

    def ship_cells(self, name: str) -> frozenset[Coordinate]:
        return self._placement.ships[name]

    def resolve_incoming(self, coord: Coordinate) -> ShotAnswer:
        if coord in self._incoming:
            raise DuplicateShotError(f"Already fired at {coord}")
        self._incoming.add(coord)
        for name, cells in list(self._remaining.items()):
            if coord in cells:
                cells.remove(coord)
                if not cells:
                    del self._remaining[name]
                    return ShotAnswer(coordinate=coord, result="sunk", ship=name)
                return ShotAnswer(coordinate=coord, result="hit")
        return ShotAnswer(coordinate=coord, result="miss")
