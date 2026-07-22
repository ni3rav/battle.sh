"""Match-over-Relay seam: create / join / reject paths."""

from __future__ import annotations

import re

import pytest

from battle_sh.networking.connection import MatchConnection, MatchConnectionError
from battle_sh.networking.relay import start_relay


async def test_host_creates_match_and_receives_high_entropy_invite() -> None:
    async with start_relay() as relay_url:
        host = await MatchConnection.connect(relay_url)
        try:
            invite = await host.create_match()
            assert isinstance(invite, str)
            assert re.fullmatch(r"[A-Za-z0-9_-]{22,}", invite)
        finally:
            await host.close()


async def test_guest_joins_match_with_invite() -> None:
    async with start_relay() as relay_url:
        host = await MatchConnection.connect(relay_url)
        guest = await MatchConnection.connect(relay_url)
        try:
            invite = await host.create_match()
            await guest.join_match(invite)
            await host.wait_for_player_joined()
        finally:
            await guest.close()
            await host.close()


async def test_third_joiner_is_rejected_with_clear_error() -> None:
    async with start_relay() as relay_url:
        host = await MatchConnection.connect(relay_url)
        guest = await MatchConnection.connect(relay_url)
        third = await MatchConnection.connect(relay_url)
        try:
            invite = await host.create_match()
            await guest.join_match(invite)
            await host.wait_for_player_joined()
            with pytest.raises(MatchConnectionError) as exc_info:
                await third.join_match(invite)
            assert exc_info.value.code == "match_full"
            assert exc_info.value.message
        finally:
            await third.close()
            await guest.close()
            await host.close()


async def test_unknown_invite_fails_clearly() -> None:
    async with start_relay() as relay_url:
        guest = await MatchConnection.connect(relay_url)
        try:
            with pytest.raises(MatchConnectionError) as exc_info:
                await guest.join_match("not-a-real-invite-zzzz")
            assert exc_info.value.code == "unknown_invite"
            assert exc_info.value.message
        finally:
            await guest.close()


async def test_malformed_invite_fails_clearly() -> None:
    async with start_relay() as relay_url:
        guest = await MatchConnection.connect(relay_url)
        try:
            with pytest.raises(MatchConnectionError) as exc_info:
                await guest.join_match("")
            assert exc_info.value.code == "malformed_invite"
            assert exc_info.value.message
        finally:
            await guest.close()
