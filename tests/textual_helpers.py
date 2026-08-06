"""Shared Textual Pilot helpers for lobby / Placement session tests."""

from __future__ import annotations

from collections.abc import Callable

from textual.pilot import Pilot
from textual.widgets import OptionList

from battle_sh.rules.placement import Placement
from battle_sh.ui.clock import FakeClock
from battle_sh.ui.textual_app import BattleShApp, HostWaitingScreen, OpeningScreen


def make_app(
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


async def wait_until(
    pilot: Pilot[None], predicate: Callable[[], bool], *, attempts: int = 80
) -> None:
    """Poll the Textual pilot until predicate() is true."""
    for _ in range(attempts):
        if predicate():
            return
        await pilot.pause(0.05)
    raise AssertionError("condition not met in time")


async def host_to_waiting(
    pilot: Pilot[None], app: BattleShApp
) -> HostWaitingScreen:
    await pilot.pause()
    assert isinstance(app.screen, OpeningScreen)
    menu = app.screen.query_one("#menu", OptionList)
    # Relay is index 0; Host is 1. Highlight may still be on Host after a prior visit.
    menu.highlighted = 1
    menu.focus()
    await pilot.press("enter")
    await wait_until(
        pilot,
        lambda: isinstance(app.screen, HostWaitingScreen)
        and app.screen.displayed_invite() is not None,
    )
    assert isinstance(app.screen, HostWaitingScreen)
    return app.screen
