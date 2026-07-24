"""Relay notifies remaining Player on disconnect / leave / reconnect."""

from __future__ import annotations

import asyncio

import pytest

from battle_sh.networking.connection import MatchConnection, MatchConnectionError
from battle_sh.networking.protocol import MatchOutcome
from battle_sh.networking.relay import start_relay


async def test_unexpected_disconnect_notifies_remaining_with_grace_seconds() -> None:
    grace = 0.5
    async with start_relay(grace_seconds=grace) as relay_url:
        host = await MatchConnection.connect(relay_url, grace_seconds=grace)
        guest = await MatchConnection.connect(relay_url, grace_seconds=grace)
        try:
            invite = await host.create_match()
            await guest.join_match(invite)
            await host.wait_for_player_joined()

            await guest.close()

            notified = await host.wait_for_opponent_disconnected()
            assert notified == grace
            assert host.opponent_connected is False
        finally:
            await host.close()


async def test_reconnect_notifies_remaining_player() -> None:
    grace = 0.5
    async with start_relay(grace_seconds=grace) as relay_url:
        host = await MatchConnection.connect(relay_url, grace_seconds=grace)
        guest = await MatchConnection.connect(relay_url, grace_seconds=grace)
        try:
            invite = await host.create_match()
            await guest.join_match(invite)
            await host.wait_for_player_joined()
            guest_role = guest.role
            assert guest_role is not None

            await guest.close()
            await host.wait_for_opponent_disconnected()

            guest = await MatchConnection.connect(relay_url, grace_seconds=grace)
            await guest.reconnect_match(invite, guest_role)

            await host.wait_for_opponent_reconnected()
            assert host.opponent_connected is True
        finally:
            await guest.close()
            await host.close()


async def test_leave_match_abandons_immediately_as_left() -> None:
    grace = 5.0
    async with start_relay(grace_seconds=grace) as relay_url:
        host = await MatchConnection.connect(relay_url, grace_seconds=grace)
        guest = await MatchConnection.connect(relay_url, grace_seconds=grace)
        try:
            invite = await host.create_match()
            await guest.join_match(invite)
            await host.wait_for_player_joined()

            await guest.leave_match()

            end = await asyncio.wait_for(host.wait_for_match_end(), timeout=1.0)
            assert end.outcome == MatchOutcome.ABANDONED
            assert end.reason == "left"
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
