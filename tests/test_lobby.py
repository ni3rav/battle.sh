"""In-app Host / Join lobby over Relay (Textual Pilot + session seams)."""

from __future__ import annotations

import re

import pytest

from battle_sh.networking.connection import MatchConnection, MatchConnectionError
from battle_sh.networking.relay import start_relay
from battle_sh.ui.textual_app import (
    JoinScreen,
    OpeningScreen,
    PlacementScreen,
)
from textual_helpers import host_to_waiting, make_app, wait_until


@pytest.mark.asyncio
async def test_host_from_opening_creates_match_and_shows_invite() -> None:
    async with start_relay() as relay_url:
        app = make_app(relay_url)
        async with app.run_test() as pilot:
            waiting = await host_to_waiting(pilot, app)
            invite = waiting.displayed_invite()
            assert invite is not None
            assert re.fullmatch(r"[a-z]+(?:-[a-z]+){3}", invite)


@pytest.mark.asyncio
async def test_back_on_host_waiting_returns_to_opening_and_invalidates_invite() -> None:
    async with start_relay() as relay_url:
        app = make_app(relay_url)
        async with app.run_test() as pilot:
            waiting = await host_to_waiting(pilot, app)
            invite = waiting.displayed_invite()
            assert invite is not None
            await pilot.press("enter")  # Back
            await wait_until(pilot, lambda: isinstance(app.screen, OpeningScreen))
            assert isinstance(app.screen, OpeningScreen)

        guest = await MatchConnection.connect(relay_url)
        try:
            with pytest.raises(MatchConnectionError) as exc_info:
                await guest.join_match(invite)
            assert exc_info.value.code == "unknown_invite"
        finally:
            await guest.close()


@pytest.mark.asyncio
async def test_back_on_join_returns_to_opening() -> None:
    async with start_relay() as relay_url:
        app = make_app(relay_url)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("down", "enter")  # Join
            await wait_until(pilot, lambda: isinstance(app.screen, JoinScreen))
            await pilot.press("escape")  # Back
            await wait_until(pilot, lambda: isinstance(app.screen, OpeningScreen))
            assert isinstance(app.screen, OpeningScreen)


@pytest.mark.asyncio
async def test_join_missing_invite_shows_error_with_back() -> None:
    async with start_relay() as relay_url:
        app = make_app(relay_url)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("down", "enter")  # Join
            await wait_until(pilot, lambda: isinstance(app.screen, JoinScreen))
            await pilot.press("tab", "enter")  # focus Join option, submit empty
            await wait_until(
                pilot,
                lambda: isinstance(app.screen, JoinScreen)
                and "Invite is required" in app.screen.status_text(),
            )
            assert isinstance(app.screen, JoinScreen)
            await pilot.press("escape")
            await wait_until(pilot, lambda: isinstance(app.screen, OpeningScreen))


@pytest.mark.asyncio
async def test_join_rejected_invite_shows_error_with_back() -> None:
    async with start_relay() as relay_url:
        app = make_app(relay_url)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("down", "enter")  # Join
            await wait_until(pilot, lambda: isinstance(app.screen, JoinScreen))
            await pilot.press(*list("not-a-real-invite-zzzz"))
            await pilot.press("enter")  # submit via Input
            await wait_until(
                pilot,
                lambda: isinstance(app.screen, JoinScreen)
                and "Could not Join" in app.screen.status_text(),
            )
            assert isinstance(app.screen, JoinScreen)
            await pilot.press("escape")
            await wait_until(pilot, lambda: isinstance(app.screen, OpeningScreen))


@pytest.mark.asyncio
async def test_host_and_guest_connect_via_in_app_lobby_to_placement() -> None:
    """Session/Relay seam: opening → Host/Join → Placement on both sides."""
    async with start_relay() as relay_url:
        host_app = make_app(relay_url)
        guest_app = make_app(relay_url)
        async with host_app.run_test() as host_pilot:
            waiting = await host_to_waiting(host_pilot, host_app)
            invite = waiting.displayed_invite()
            assert invite is not None

            async with guest_app.run_test() as guest_pilot:
                await guest_pilot.pause()
                await guest_pilot.press("down", "enter")  # Join
                await wait_until(
                    guest_pilot, lambda: isinstance(guest_app.screen, JoinScreen)
                )
                await guest_pilot.press(*list(invite))
                await guest_pilot.press("enter")
                await wait_until(
                    guest_pilot,
                    lambda: isinstance(guest_app.screen, PlacementScreen),
                )
                await wait_until(
                    host_pilot,
                    lambda: isinstance(host_app.screen, PlacementScreen),
                )
                assert isinstance(host_app.screen, PlacementScreen)
                assert isinstance(guest_app.screen, PlacementScreen)
                assert host_app.screen.role == "host"
                assert guest_app.screen.role == "guest"
