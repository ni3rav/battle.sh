"""Match-over-Relay seam: grace reconnect and Abandoned Matches."""

from __future__ import annotations

import asyncio
import contextlib

import pytest

from battle_sh.networking.connection import (
    MatchConnection,
    MatchConnectionError,
)
from battle_sh.networking.protocol import MatchOutcome
from battle_sh.networking.relay import start_relay
from battle_sh.rules.placement import Placement, coordinate


def _legal_placement_a() -> Placement:
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
    return Placement(
        {
            "Carrier": frozenset(coordinate("J", r) for r in range(1, 6)),
            "Battleship": frozenset(coordinate("H", r) for r in range(1, 5)),
            "Cruiser": frozenset(coordinate("F", r) for r in range(1, 4)),
            "Submarine": frozenset(coordinate("D", r) for r in range(1, 4)),
            "Destroyer": frozenset(coordinate("B", r) for r in range(1, 3)),
        }
    )


async def test_disconnect_then_reconnect_within_grace_resumes_same_match() -> None:
    grace = 0.5
    async with start_relay(grace_seconds=grace) as relay_url:
        host = await MatchConnection.connect(relay_url, grace_seconds=grace)
        guest = await MatchConnection.connect(relay_url, grace_seconds=grace)
        try:
            invite = await host.create_match()
            await guest.join_match(invite)
            await host.wait_for_player_joined()
            guest_role = guest.role

            await guest.close()

            guest = await MatchConnection.connect(relay_url, grace_seconds=grace)
            await guest.reconnect_match(invite, guest_role)

            assert guest.invite == invite
            assert guest.role == guest_role

            host_commitment = await host.lock_placement(_legal_placement_a())
            guest_commitment = await guest.lock_placement(_legal_placement_b())
            await host.wait_for_opponent_commitment()
            await guest.wait_for_opponent_commitment()

            assert host.opponent_commitment == guest_commitment
            assert guest.opponent_commitment == host_commitment
            assert host.ready_to_fire is True
            assert guest.ready_to_fire is True
        finally:
            await guest.close()
            await host.close()


async def test_disconnect_beyond_grace_ends_match_as_abandoned() -> None:
    grace = 0.15
    async with start_relay(grace_seconds=grace) as relay_url:
        host = await MatchConnection.connect(relay_url, grace_seconds=grace)
        guest = await MatchConnection.connect(relay_url, grace_seconds=grace)
        try:
            invite = await host.create_match()
            await guest.join_match(invite)
            await host.wait_for_player_joined()

            await guest.close()
            end = await host.wait_for_match_end()

            assert end.outcome == MatchOutcome.ABANDONED
            assert end.outcome != MatchOutcome.WINNER
            assert end.winner is None

            with pytest.raises(MatchConnectionError) as exc_info:
                late = await MatchConnection.connect(relay_url, grace_seconds=grace)
                try:
                    await late.reconnect_match(invite, "guest")
                finally:
                    await late.close()
            assert exc_info.value.code == "unknown_invite"
        finally:
            await host.close()


async def test_relay_unreachable_beyond_grace_ends_match_as_abandoned() -> None:
    grace = 0.15
    relay_cm = start_relay(grace_seconds=grace)
    relay_url = await relay_cm.__aenter__()
    host = await MatchConnection.connect(relay_url, grace_seconds=grace)
    guest = await MatchConnection.connect(relay_url, grace_seconds=grace)
    try:
        invite = await host.create_match()
        await guest.join_match(invite)
        await host.wait_for_player_joined()

        await relay_cm.__aexit__(None, None, None)

        host_end, guest_end = await asyncio.gather(
            host.wait_for_match_end(),
            guest.wait_for_match_end(),
        )
        assert host_end.outcome == MatchOutcome.ABANDONED
        assert guest_end.outcome == MatchOutcome.ABANDONED
        assert host_end.outcome != MatchOutcome.WINNER
        assert host_end.winner is None
        assert guest_end.winner is None
    finally:
        with contextlib.suppress(Exception):
            await guest.close()
        with contextlib.suppress(Exception):
            await host.close()
