"""Placement Commitment Reveal verification."""

from __future__ import annotations

from collections.abc import Sequence

from battle_sh.rules.board import ShotAnswer, parse_coordinate
from battle_sh.rules.placement import (
    STANDARD_FLEET_LENGTHS,
    Coordinate,
    Placement,
    placement_commitment,
)


class RevealVerificationError(Exception):
    """Raised when a Reveal disagrees with the Placement Commitment or Shot history."""


def placement_from_reveal(ships: dict[str, list[str]]) -> Placement:
    parsed: dict[str, frozenset[Coordinate]] = {}
    for name, cells in ships.items():
        parsed[name] = frozenset(parse_coordinate(cell) for cell in cells)
    return Placement(parsed)


def verify_ship_reveal(
    ship: str, cells: Sequence[str], answers: list[ShotAnswer]
) -> None:
    """Early check: sunk Ship Reveal size and consistency with prior Shot answers."""
    if ship not in STANDARD_FLEET_LENGTHS:
        raise RevealVerificationError(f"Unknown Ship in Reveal: {ship!r}")
    coords = {parse_coordinate(cell) for cell in cells}
    if len(coords) != STANDARD_FLEET_LENGTHS[ship]:
        raise RevealVerificationError(
            f"Reveal for {ship} must cover {STANDARD_FLEET_LENGTHS[ship]} cells"
        )
    for answer in answers:
        if answer.coordinate in coords and answer.result == "miss":
            raise RevealVerificationError(
                f"Ship Reveal for {ship} includes prior miss at {answer.coordinate}"
            )
    sunk = [a for a in answers if a.result == "sunk" and a.ship == ship]
    if sunk and sunk[-1].coordinate not in coords:
        raise RevealVerificationError(
            f"Sunk Coordinate for {ship} missing from Ship Reveal"
        )


def verify_fleet_reveal(placement: Placement, commitment: str) -> None:
    if placement_commitment(placement) != commitment:
        raise RevealVerificationError(
            "Full Placement Reveal does not match Placement Commitment"
        )


def verify_shot_answers_against_placement(
    placement: Placement, answers: list[ShotAnswer]
) -> None:
    occupied = {cell for cells in placement.ships.values() for cell in cells}
    ship_of = {
        cell: name for name, cells in placement.ships.items() for cell in cells
    }
    hits_by_ship: dict[str, set[Coordinate]] = {
        name: set() for name in placement.ships
    }
    for answer in answers:
        on_ship = answer.coordinate in occupied
        if answer.result == "miss":
            if on_ship:
                raise RevealVerificationError(
                    f"Miss at {answer.coordinate} lands on a revealed Ship"
                )
            continue
        if not on_ship:
            raise RevealVerificationError(
                f"{answer.result} at {answer.coordinate} is not on any revealed Ship"
            )
        name = ship_of[answer.coordinate]
        hits_by_ship[name].add(answer.coordinate)
        if answer.result == "sunk":
            if answer.ship != name:
                raise RevealVerificationError(
                    f"Sunk Ship identity {answer.ship!r} does not match {name!r}"
                )
            if hits_by_ship[name] != set(placement.ships[name]):
                raise RevealVerificationError(
                    f"Sunk Reveal for {name} does not cover every prior hit"
                )
