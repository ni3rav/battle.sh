"""Rules seam: random Placement and keyboard adjust helpers."""

from __future__ import annotations

import random

import pytest

from battle_sh.rules.placement import (
    IllegalPlacementError,
    Placement,
    coordinate,
    random_placement,
    rotate_ship,
    translate_ship,
    validate_placement,
)


def test_random_placement_is_always_legal() -> None:
    rng = random.Random(0)
    for _ in range(50):
        placement = random_placement(rng)
        validate_placement(placement)


def test_translate_ship_keeps_orientation_and_rejects_overlap() -> None:
    placement = Placement(
        {
            "Carrier": frozenset(coordinate(c, 1) for c in "ABCDE"),
            "Battleship": frozenset(coordinate(c, 2) for c in "ABCD"),
            "Cruiser": frozenset(coordinate(c, 3) for c in "ABC"),
            "Submarine": frozenset(coordinate(c, 4) for c in "ABC"),
            "Destroyer": frozenset(coordinate(c, 5) for c in "AB"),
        }
    )
    moved = translate_ship(placement, "Destroyer", column_delta=2, row_delta=0)
    assert moved.ships["Destroyer"] == frozenset(coordinate(c, 5) for c in "CD")
    validate_placement(moved)

    with pytest.raises(IllegalPlacementError):
        translate_ship(placement, "Destroyer", column_delta=0, row_delta=-1)


def test_rotate_ship_around_bow() -> None:
    placement = Placement(
        {
            "Carrier": frozenset(coordinate(c, 1) for c in "ABCDE"),
            "Battleship": frozenset(coordinate(c, 2) for c in "ABCD"),
            "Cruiser": frozenset(coordinate(c, 3) for c in "ABC"),
            "Submarine": frozenset(coordinate(c, 4) for c in "ABC"),
            "Destroyer": frozenset(coordinate(c, 5) for c in "AB"),
        }
    )
    # Destroyer on AB5 → vertical A5,A6 (clear of other Ships)
    rotated = rotate_ship(placement, "Destroyer")
    assert rotated.ships["Destroyer"] == frozenset(
        coordinate("A", r) for r in (5, 6)
    )
    validate_placement(rotated)

    # Carrier A1–E1 → A1–A5 overlaps Battleship on A2
    with pytest.raises(IllegalPlacementError):
        rotate_ship(placement, "Carrier")
