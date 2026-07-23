"""Match-over-Relay seam: play Shots through to Winner with Reveals."""

from __future__ import annotations

import asyncio

import pytest

from battle_sh.networking.connection import (
    DuplicateShotError,
    IllegalShotError,
    MatchConnection,
    NotYourTurnError,
    RevealVerificationError,
    ShotReport,
)
from battle_sh.networking.protocol import MatchOutcome
from battle_sh.networking.relay import start_relay
from battle_sh.rules.board import Board
from battle_sh.rules.placement import Placement, coordinate


def _placement_a() -> Placement:
    """Host Fleet: Destroyer on A1-A2 — easy to sink in tests."""
    return Placement(
        {
            "Carrier": frozenset(coordinate(c, 10) for c in "ABCDE"),
            "Battleship": frozenset(coordinate(c, 9) for c in "ABCD"),
            "Cruiser": frozenset(coordinate(c, 8) for c in "ABC"),
            "Submarine": frozenset(coordinate(c, 7) for c in "ABC"),
            "Destroyer": frozenset(coordinate("A", r) for r in (1, 2)),
        }
    )


def _placement_b() -> Placement:
    """Guest Fleet: Destroyer on J10-J9."""
    return Placement(
        {
            "Carrier": frozenset(coordinate(c, 1) for c in "ABCDE"),
            "Battleship": frozenset(coordinate(c, 2) for c in "ABCD"),
            "Cruiser": frozenset(coordinate(c, 3) for c in "ABC"),
            "Submarine": frozenset(coordinate(c, 4) for c in "ABC"),
            "Destroyer": frozenset(coordinate("J", r) for r in (10, 9)),
        }
    )


async def _ready_match(
    relay_url: str,
) -> tuple[MatchConnection, MatchConnection]:
    host = await MatchConnection.connect(relay_url)
    guest = await MatchConnection.connect(relay_url)
    invite = await host.create_match()
    await guest.join_match(invite)
    await host.wait_for_player_joined()
    await host.lock_placement(_placement_a())
    await guest.lock_placement(_placement_b())
    await host.wait_for_opponent_commitment()
    await guest.wait_for_opponent_commitment()
    return host, guest


async def test_host_fires_first_shot_and_receives_miss() -> None:
    async with start_relay() as relay_url:
        host, guest = await _ready_match(relay_url)
        try:
            async def guest_answers() -> None:
                await guest.serve_opponent_shot()

            guest_task = asyncio.create_task(guest_answers())
            answer = await host.fire_shot("E5")
            await guest_task

            assert answer.result == "miss"
            assert answer.ship is None
            assert answer.coordinate == "E5"
        finally:
            await guest.close()
            await host.close()


async def test_illegal_and_duplicate_shots_are_rejected() -> None:
    async with start_relay() as relay_url:
        host, guest = await _ready_match(relay_url)
        try:
            with pytest.raises(IllegalShotError):
                await host.fire_shot("Z9")
            with pytest.raises(NotYourTurnError):
                await guest.fire_shot("A1")

            guest_task = asyncio.create_task(guest.serve_opponent_shot())
            first = await host.fire_shot("E5")
            await guest_task
            assert first.result == "miss"

            host_task = asyncio.create_task(host.serve_opponent_shot())
            await guest.fire_shot("E6")
            await host_task

            with pytest.raises(DuplicateShotError):
                await host.fire_shot("E5")
        finally:
            await guest.close()
            await host.close()


async def test_sink_reveals_ship_cells() -> None:
    async with start_relay() as relay_url:
        host, guest = await _ready_match(relay_url)
        try:
            guest_task = asyncio.create_task(guest.serve_opponent_shot())
            hit = await host.fire_shot("J10")
            await guest_task
            assert hit.result == "hit"

            host_task = asyncio.create_task(host.serve_opponent_shot())
            await guest.fire_shot("E5")
            await host_task

            guest_task = asyncio.create_task(guest.serve_opponent_shot())
            sunk = await host.fire_shot("J9")
            await guest_task

            assert sunk.result == "sunk"
            assert sunk.ship == "Destroyer"
            assert set(sunk.revealed_cells) == {"J9", "J10"}
            assert sunk.match_end is None
        finally:
            await guest.close()
            await host.close()


async def test_destroying_fleet_produces_winner_and_verifies_reveal() -> None:
    """Sink every Guest Ship; Host becomes Winner; Commitment verifies."""
    async with start_relay() as relay_url:
        host, guest = await _ready_match(relay_url)
        try:
            # Guest Destroyer J10,J9; then remaining ships in placement_b
            guest_targets = [
                "J10",
                "J9",
                "A1",
                "B1",
                "C1",
                "D1",
                "E1",  # Carrier
                "A2",
                "B2",
                "C2",
                "D2",  # Battleship
                "A3",
                "B3",
                "C3",  # Cruiser
                "A4",
                "B4",
                "C4",  # Submarine
            ]
            host_filler = [
                "E5",
                "E6",
                "E7",
                "E8",
                "E9",
                "F5",
                "F6",
                "F7",
                "F8",
                "F9",
                "G5",
                "G6",
                "G7",
                "G8",
                "G9",
                "H5",
            ]

            last: ShotReport | None = None
            for i, target in enumerate(guest_targets):
                guest_task = asyncio.create_task(guest.serve_opponent_shot())
                last = await host.fire_shot(target)
                await guest_task
                if last.match_end is not None:
                    break
                if i < len(host_filler):
                    host_task = asyncio.create_task(host.serve_opponent_shot())
                    await guest.fire_shot(host_filler[i])
                    await host_task

            assert last is not None
            assert last.match_end is not None
            assert last.match_end.outcome == MatchOutcome.WINNER
            assert last.match_end.winner == "host"
            assert last.verification_ok is True
            assert guest.match_end is not None
            assert guest.match_end.winner == "host"
        finally:
            await guest.close()
            await host.close()


async def test_commitment_mismatch_on_fleet_reveal_is_reported() -> None:
    """Defender Reveals a Fleet that does not match the sealed Commitment."""
    async with start_relay() as relay_url:
        host, guest = await _ready_match(relay_url)
        try:
            # Commitment was for placement_b; answer/reveal as placement_a instead.
            # Intentionally replace the defender board to force a Reveal mismatch.
            guest._board = Board(_placement_a())  # pyright: ignore[reportPrivateUsage]
            targets = [
                "A1",
                "A2",  # Destroyer
                "A10",
                "B10",
                "C10",
                "D10",
                "E10",  # Carrier
                "A9",
                "B9",
                "C9",
                "D9",  # Battleship
                "A8",
                "B8",
                "C8",  # Cruiser
                "A7",
                "B7",
                "C7",  # Submarine
            ]
            fillers = [f"E{n}" for n in range(5, 11)] + [
                f"F{n}" for n in range(5, 11)
            ] + [f"G{n}" for n in range(5, 10)]

            async def play_until_mismatch() -> None:
                for i, target in enumerate(targets):
                    guest_task = asyncio.create_task(guest.serve_opponent_shot())
                    report = await host.fire_shot(target)
                    await guest_task
                    assert report.match_end is None
                    host_task = asyncio.create_task(host.serve_opponent_shot())
                    await guest.fire_shot(fillers[i])
                    await host_task

            with pytest.raises(RevealVerificationError, match="Placement Commitment"):
                await play_until_mismatch()
        finally:
            await guest.close()
            await host.close()
