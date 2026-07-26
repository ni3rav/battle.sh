"""Placement phase in Textual: three-band screen, keys, lock/wait, quit, Match time."""

from __future__ import annotations

from collections.abc import Callable

import pytest
from textual.pilot import Pilot

from battle_sh.networking.connection import MatchConnection
from battle_sh.networking.relay import start_relay
from battle_sh.rules.placement import Placement, coordinate
from battle_sh.ui.clock import FakeClock
from battle_sh.ui.textual_app import (
    BattleShApp,
    HostWaitingScreen,
    JoinScreen,
    OpeningScreen,
    PlacementScreen,
    ReadyForCombatScreen,
)


def _fixed_placement() -> Placement:
    return Placement(
        {
            "Carrier": frozenset(coordinate(c, 1) for c in "ABCDE"),
            "Battleship": frozenset(coordinate(c, 2) for c in "ABCD"),
            "Cruiser": frozenset(coordinate(c, 3) for c in "ABC"),
            "Submarine": frozenset(coordinate(c, 4) for c in "ABC"),
            "Destroyer": frozenset(coordinate(c, 5) for c in "AB"),
        }
    )


def _app(
    relay_url: str,
    clock: FakeClock | None = None,
    *,
    placement_factory: Callable[[], Placement] | None = None,
) -> BattleShApp:
    return BattleShApp(
        relay_url=relay_url,
        grace_seconds=10.0,
        clock=clock if clock is not None else FakeClock(),
        placement_factory=placement_factory,
    )


async def _wait_until(
    pilot: Pilot[None], predicate: Callable[[], bool], *, attempts: int = 80
) -> None:
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
async def test_placement_screen_has_three_bands_and_placement_controls() -> None:
    async with start_relay() as relay_url:
        host_app = _app(relay_url, placement_factory=_fixed_placement)
        guest_app = _app(relay_url, placement_factory=_fixed_placement)
        async with host_app.run_test(size=(120, 40)) as host_pilot:
            waiting = await _host_to_waiting(host_pilot, host_app)
            invite = waiting.displayed_invite()
            assert invite is not None

            async with guest_app.run_test(size=(120, 40)) as guest_pilot:
                await guest_pilot.pause()
                await guest_pilot.press("down", "enter")
                await _wait_until(
                    guest_pilot, lambda: isinstance(guest_app.screen, JoinScreen)
                )
                await guest_pilot.press(*list(invite))
                await guest_pilot.press("enter")
                await _wait_until(
                    guest_pilot,
                    lambda: isinstance(guest_app.screen, PlacementScreen),
                )
                await _wait_until(
                    host_pilot,
                    lambda: isinstance(host_app.screen, PlacementScreen),
                )
                screen = host_app.screen
                assert isinstance(screen, PlacementScreen)
                assert "Placement" in screen.info_text()
                assert "Match time" in screen.info_text()
                assert "Your fleet" in screen.board_text() or "C" in screen.board_text()
                controls = screen.controls_text()
                assert "→ select ship" in controls
                assert "→ lock" in controls
                assert "`y`" in controls
                assert "→ quit" in controls
                assert "fire" not in controls.lower()
                assert screen.status_text() is not None


@pytest.mark.asyncio
async def test_match_time_starts_only_after_guest_joins_not_in_host_lobby() -> None:
    clock = FakeClock(start=100.0)
    async with start_relay() as relay_url:
        host_app = _app(relay_url, clock, placement_factory=_fixed_placement)
        guest_app = _app(relay_url, clock, placement_factory=_fixed_placement)
        async with host_app.run_test(size=(120, 40)) as host_pilot:
            waiting = await _host_to_waiting(host_pilot, host_app)
            invite = waiting.displayed_invite()
            assert invite is not None
            # Solo Host lobby: no Match time on the waiting screen.
            body = str(host_app.screen.query_one("#body").render())
            assert "Match time starts when they join" in body
            clock.advance(30.0)

            async with guest_app.run_test(size=(120, 40)) as guest_pilot:
                await guest_pilot.pause()
                await guest_pilot.press("down", "enter")
                await _wait_until(
                    guest_pilot, lambda: isinstance(guest_app.screen, JoinScreen)
                )
                await guest_pilot.press(*list(invite))
                await guest_pilot.press("enter")
                await _wait_until(
                    guest_pilot,
                    lambda: isinstance(guest_app.screen, PlacementScreen),
                )
                await _wait_until(
                    host_pilot,
                    lambda: isinstance(host_app.screen, PlacementScreen),
                )
                host_screen = host_app.screen
                assert isinstance(host_screen, PlacementScreen)
                # Match clock starts at join, not 30s earlier during lobby wait.
                assert "Match time 0:00" in host_screen.info_text()
                clock.advance(65.0)
                host_screen.refresh_match_time()
                assert "Match time 1:05" in host_screen.info_text()


@pytest.mark.asyncio
async def test_lock_commits_and_both_wait_then_both_ready() -> None:
    async with start_relay() as relay_url:
        host_app = _app(relay_url, placement_factory=_fixed_placement)
        guest_app = _app(relay_url, placement_factory=_fixed_placement)
        async with host_app.run_test(size=(120, 40)) as host_pilot:
            waiting = await _host_to_waiting(host_pilot, host_app)
            invite = waiting.displayed_invite()
            assert invite is not None

            async with guest_app.run_test(size=(120, 40)) as guest_pilot:
                await guest_pilot.pause()
                await guest_pilot.press("down", "enter")
                await _wait_until(
                    guest_pilot, lambda: isinstance(guest_app.screen, JoinScreen)
                )
                await guest_pilot.press(*list(invite))
                await guest_pilot.press("enter")
                await _wait_until(
                    guest_pilot,
                    lambda: isinstance(guest_app.screen, PlacementScreen),
                )
                await _wait_until(
                    host_pilot,
                    lambda: isinstance(host_app.screen, PlacementScreen),
                )

                # Host locks first → waiting for opponent commitment (spinner/wait).
                await host_pilot.press("y")
                await _wait_until(
                    host_pilot,
                    lambda: isinstance(host_app.screen, PlacementScreen)
                    and host_app.screen.is_waiting_for_opponent(),
                )
                host_screen = host_app.screen
                assert isinstance(host_screen, PlacementScreen)
                assert "Waiting" in host_screen.info_text()
                assert "→ quit" in host_screen.controls_text()
                assert "→ lock" not in host_screen.controls_text()

                # Guest locks → both commitments present → ready-for-combat stub.
                await guest_pilot.press("y")
                await _wait_until(
                    host_pilot,
                    lambda: isinstance(host_app.screen, ReadyForCombatScreen),
                )
                await _wait_until(
                    guest_pilot,
                    lambda: isinstance(guest_app.screen, ReadyForCombatScreen),
                )


@pytest.mark.asyncio
async def test_no_back_during_placement_and_q_does_not_quit() -> None:
    async with start_relay() as relay_url:
        host_app = _app(relay_url, placement_factory=_fixed_placement)
        guest_app = _app(relay_url, placement_factory=_fixed_placement)
        async with host_app.run_test(size=(120, 40)) as host_pilot:
            waiting = await _host_to_waiting(host_pilot, host_app)
            invite = waiting.displayed_invite()
            assert invite is not None

            async with guest_app.run_test(size=(120, 40)) as guest_pilot:
                await guest_pilot.pause()
                await guest_pilot.press("down", "enter")
                await _wait_until(
                    guest_pilot, lambda: isinstance(guest_app.screen, JoinScreen)
                )
                await guest_pilot.press(*list(invite))
                await guest_pilot.press("enter")
                await _wait_until(
                    guest_pilot,
                    lambda: isinstance(guest_app.screen, PlacementScreen),
                )
                await _wait_until(
                    host_pilot,
                    lambda: isinstance(host_app.screen, PlacementScreen),
                )

                await host_pilot.press("escape")
                await host_pilot.pause()
                assert isinstance(host_app.screen, PlacementScreen)

                await host_pilot.press("q")
                await host_pilot.pause()
                assert host_app.is_running
                assert isinstance(host_app.screen, PlacementScreen)


@pytest.mark.asyncio
async def test_two_step_ctrl_c_during_placement_abandons_for_both() -> None:
    clock = FakeClock(start=0.0)
    async with start_relay() as relay_url:
        host_app = _app(relay_url, clock, placement_factory=_fixed_placement)
        guest_conn: MatchConnection | None = None
        try:
            async with host_app.run_test(size=(120, 40)) as host_pilot:
                waiting = await _host_to_waiting(host_pilot, host_app)
                invite = waiting.displayed_invite()
                assert invite is not None

                guest_conn = await MatchConnection.connect(relay_url)
                await guest_conn.join_match(invite)
                await _wait_until(
                    host_pilot,
                    lambda: isinstance(host_app.screen, PlacementScreen),
                )

                await host_pilot.press("ctrl+c")
                await host_pilot.pause()
                assert host_app.is_running
                host_screen = host_app.screen
                assert isinstance(host_screen, PlacementScreen)
                assert "Press Ctrl+C again" in host_screen.status_text()

                clock.advance(1.0)
                await host_pilot.press("ctrl+c")
                await _wait_until(
                    host_pilot,
                    lambda: not host_app.is_running
                    or isinstance(host_app.screen, OpeningScreen),
                    attempts=100,
                )

                end = await guest_conn.wait_for_match_end()
                assert end.outcome == "abandoned"
                assert end.reason == "left"
        finally:
            if guest_conn is not None:
                await guest_conn.close()
