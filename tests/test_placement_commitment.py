"""Match-over-Relay seam: Placement lock + Commitment exchange."""

from __future__ import annotations

import pytest

from battle_sh.networking.connection import MatchConnection, NotReadyToFireError
from battle_sh.networking.relay import start_relay
from battle_sh.rules.placement import (
    Coordinate,
    IllegalPlacementError,
    Placement,
    coordinate,
)


def _legal_placement_a() -> Placement:
    """Known-good Standard Fleet with adjacent Ships (classic adjacency allowed)."""
    return Placement(
        {
            "Carrier": frozenset(coordinate(c, 1) for c in "ABCDE"),
            "Battleship": frozenset(coordinate(c, 2) for c in "ABCD"),
            "Cruiser": frozenset(coordinate(c, 3) for c in "ABC"),
            "Submarine": frozenset(coordinate(c, 4) for c in "ABC"),
            "Destroyer": frozenset(coordinate(c, 5) for c in "AB"),
        }
    )


def _legal_placement_b() -> Placement:
    """Second known-good layout, distinct from A."""
    return Placement(
        {
            "Carrier": frozenset(coordinate("J", r) for r in range(1, 6)),
            "Battleship": frozenset(coordinate("H", r) for r in range(1, 5)),
            "Cruiser": frozenset(coordinate("F", r) for r in range(1, 4)),
            "Submarine": frozenset(coordinate("D", r) for r in range(1, 4)),
            "Destroyer": frozenset(coordinate("B", r) for r in range(1, 3)),
        }
    )


def _overlapping_illegal() -> Placement:
    return Placement(
        {
            "Carrier": frozenset(coordinate(c, 1) for c in "ABCDE"),
            "Battleship": frozenset(coordinate(c, 1) for c in "FGHI"),
            "Cruiser": frozenset(coordinate(c, 1) for c in "ABC"),
            "Submarine": frozenset(coordinate(c, 3) for c in "ABC"),
            "Destroyer": frozenset(coordinate(c, 5) for c in "AB"),
        }
    )


def _diagonal_illegal() -> Placement:
    return Placement(
        {
            "Carrier": frozenset(
                {
                    Coordinate("A", 1),
                    Coordinate("B", 2),
                    Coordinate("C", 3),
                    Coordinate("D", 4),
                    Coordinate("E", 5),
                }
            ),
            "Battleship": frozenset(coordinate(c, 7) for c in "ABCD"),
            "Cruiser": frozenset(coordinate(c, 9) for c in "ABC"),
            "Submarine": frozenset(coordinate("J", r) for r in range(1, 4)),
            "Destroyer": frozenset(coordinate("H", r) for r in range(1, 3)),
        }
    )


async def test_players_lock_legal_placements_and_exchange_commitments() -> None:
    async with start_relay() as relay_url:
        host = await MatchConnection.connect(relay_url)
        guest = await MatchConnection.connect(relay_url)
        try:
            invite = await host.create_match()
            await guest.join_match(invite)
            await host.wait_for_player_joined()

            host_commitment = await host.lock_placement(_legal_placement_a())
            guest_commitment = await guest.lock_placement(_legal_placement_b())
            await host.wait_for_opponent_commitment()
            await guest.wait_for_opponent_commitment()

            assert isinstance(host_commitment, str)
            assert len(host_commitment) == 64
            assert host_commitment != guest_commitment
            assert host.opponent_commitment == guest_commitment
            assert guest.opponent_commitment == host_commitment
            assert host.ready_to_fire is True
            assert guest.ready_to_fire is True
        finally:
            await guest.close()
            await host.close()


async def test_illegal_placement_cannot_be_locked() -> None:
    async with start_relay() as relay_url:
        host = await MatchConnection.connect(relay_url)
        guest = await MatchConnection.connect(relay_url)
        try:
            invite = await host.create_match()
            await guest.join_match(invite)
            await host.wait_for_player_joined()

            with pytest.raises(IllegalPlacementError):
                await host.lock_placement(_overlapping_illegal())
            with pytest.raises(IllegalPlacementError):
                await host.lock_placement(_diagonal_illegal())
            assert host.ready_to_fire is False
            assert host.opponent_commitment is None
        finally:
            await guest.close()
            await host.close()


async def test_firing_blocked_until_both_commitments_exchanged() -> None:
    async with start_relay() as relay_url:
        host = await MatchConnection.connect(relay_url)
        guest = await MatchConnection.connect(relay_url)
        try:
            invite = await host.create_match()
            await guest.join_match(invite)
            await host.wait_for_player_joined()

            with pytest.raises(NotReadyToFireError):
                await host.fire_shot("B7")

            await host.lock_placement(_legal_placement_a())
            with pytest.raises(NotReadyToFireError):
                await host.fire_shot("B7")

            await guest.lock_placement(_legal_placement_b())
            await host.wait_for_opponent_commitment()
            await guest.wait_for_opponent_commitment()

            await host.fire_shot("B7")
        finally:
            await guest.close()
            await host.close()
