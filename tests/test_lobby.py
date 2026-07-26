"""In-app Host / Join lobby over Relay (Textual Pilot + session seams)."""

from __future__ import annotations

import re
from collections.abc import Callable

import pytest
from textual.pilot import Pilot

from battle_sh.networking.connection import MatchConnection, MatchConnectionError
from battle_sh.networking.relay import start_relay
from battle_sh.ui.clock import FakeClock
from battle_sh.ui.textual_app import (
    BattleShApp,
    HostWaitingScreen,
    JoinScreen,
    OpeningScreen,
    ReadyForPlacementScreen,
)


def _app(relay_url: str, clock: FakeClock | None = None) -> BattleShApp:
    return BattleShApp(
        relay_url=relay_url,
        grace_seconds=10.0,
        clock=clock if clock is not None else FakeClock(),
    )


async def _wait_until(
    pilot: Pilot[None], predicate: Callable[[], bool], *, attempts: int = 80
) -> None:
    """Poll the Textual pilot until predicate() is true."""
    for _ in range(attempts):
        if predicate():
            return
        await pilot.pause(0.05)
    raise AssertionError("condition not met in time")


async def _host_to_waiting(
    pilot: Pilot[None], app: BattleShApp
) -> HostWaitingScreen:
    await pilot.pause()
    await pilot.press("enter")  # Host
    await _wait_until(
        pilot,
        lambda: isinstance(app.screen, HostWaitingScreen)
        and app.screen.displayed_invite() is not None,
    )
    assert isinstance(app.screen, HostWaitingScreen)
    return app.screen


@pytest.mark.asyncio
async def test_host_from_opening_creates_match_and_shows_invite() -> None:
    async with start_relay() as relay_url:
        app = _app(relay_url)
        async with app.run_test() as pilot:
            waiting = await _host_to_waiting(pilot, app)
            invite = waiting.displayed_invite()
            assert invite is not None
            assert re.fullmatch(r"[a-z]+(?:-[a-z]+){3}", invite)


@pytest.mark.asyncio
async def test_back_on_host_waiting_returns_to_opening_and_invalidates_invite() -> None:
    async with start_relay() as relay_url:
        app = _app(relay_url)
        async with app.run_test() as pilot:
            waiting = await _host_to_waiting(pilot, app)
            invite = waiting.displayed_invite()
            assert invite is not None
            await pilot.press("enter")  # Back
            await _wait_until(pilot, lambda: isinstance(app.screen, OpeningScreen))
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
        app = _app(relay_url)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("down", "enter")  # Join
            await _wait_until(pilot, lambda: isinstance(app.screen, JoinScreen))
            await pilot.press("escape")  # Back
            await _wait_until(pilot, lambda: isinstance(app.screen, OpeningScreen))
            assert isinstance(app.screen, OpeningScreen)


@pytest.mark.asyncio
async def test_join_missing_invite_shows_error_with_back() -> None:
    async with start_relay() as relay_url:
        app = _app(relay_url)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("down", "enter")  # Join
            await _wait_until(pilot, lambda: isinstance(app.screen, JoinScreen))
            await pilot.press("tab", "enter")  # focus Join option, submit empty
            await _wait_until(
                pilot,
                lambda: isinstance(app.screen, JoinScreen)
                and "Invite is required" in app.screen.status_text(),
            )
            assert isinstance(app.screen, JoinScreen)
            await pilot.press("escape")
            await _wait_until(pilot, lambda: isinstance(app.screen, OpeningScreen))


@pytest.mark.asyncio
async def test_join_rejected_invite_shows_error_with_back() -> None:
    async with start_relay() as relay_url:
        app = _app(relay_url)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("down", "enter")  # Join
            await _wait_until(pilot, lambda: isinstance(app.screen, JoinScreen))
            await pilot.press(*list("not-a-real-invite-zzzz"))
            await pilot.press("enter")  # submit via Input
            await _wait_until(
                pilot,
                lambda: isinstance(app.screen, JoinScreen)
                and "Could not Join" in app.screen.status_text(),
            )
            assert isinstance(app.screen, JoinScreen)
            await pilot.press("escape")
            await _wait_until(pilot, lambda: isinstance(app.screen, OpeningScreen))


@pytest.mark.asyncio
async def test_host_and_guest_connect_via_in_app_lobby_to_ready_for_placement() -> None:
    """Session/Relay seam: opening → Host/Join → Ready for Placement on both sides."""
    async with start_relay() as relay_url:
        host_app = _app(relay_url)
        guest_app = _app(relay_url)
        async with host_app.run_test() as host_pilot:
            waiting = await _host_to_waiting(host_pilot, host_app)
            invite = waiting.displayed_invite()
            assert invite is not None

            async with guest_app.run_test() as guest_pilot:
                await guest_pilot.pause()
                await guest_pilot.press("down", "enter")  # Join
                await _wait_until(
                    guest_pilot, lambda: isinstance(guest_app.screen, JoinScreen)
                )
                await guest_pilot.press(*list(invite))
                await guest_pilot.press("enter")
                await _wait_until(
                    guest_pilot,
                    lambda: isinstance(guest_app.screen, ReadyForPlacementScreen),
                )
                await _wait_until(
                    host_pilot,
                    lambda: isinstance(host_app.screen, ReadyForPlacementScreen),
                )
                assert isinstance(host_app.screen, ReadyForPlacementScreen)
                assert isinstance(guest_app.screen, ReadyForPlacementScreen)
                assert host_app.screen.role == "host"
                assert guest_app.screen.role == "guest"
