"""poll_incoming observes MATCH_END without stealing other messages."""

from __future__ import annotations

from battle_sh.networking.connection import MatchConnection
from battle_sh.networking.protocol import MatchOutcome
from battle_sh.networking.relay import start_relay


async def test_poll_incoming_sees_leave_match_end() -> None:
    async with start_relay(grace_seconds=5.0) as relay_url:
        host = await MatchConnection.connect(relay_url, grace_seconds=5.0)
        guest = await MatchConnection.connect(relay_url, grace_seconds=5.0)
        try:
            invite = await host.create_match()
            await guest.join_match(invite)
            await host.wait_for_player_joined()

            await guest.leave_match()

            end = None
            for _ in range(50):
                end = await host.poll_incoming(timeout=0.05)
                if end is not None:
                    break
            assert end is not None
            assert end.outcome == MatchOutcome.ABANDONED
            assert end.reason == "left"
            assert host.match_end == end
        finally:
            await host.close()
            await guest.close()


async def test_poll_incoming_none_when_idle() -> None:
    async with start_relay(grace_seconds=0.5) as relay_url:
        host = await MatchConnection.connect(relay_url, grace_seconds=0.5)
        try:
            await host.create_match()
            assert await host.poll_incoming(timeout=0.05) is None
        finally:
            await host.close()
