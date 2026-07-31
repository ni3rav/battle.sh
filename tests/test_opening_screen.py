"""Opening screen: brand title, Host/Join/Theme/Exit, QuitArm, q never quits."""

from __future__ import annotations

import pytest

from battle_sh.ui.clock import FakeClock
from battle_sh.ui.textual_app import BRAND_TITLE, BattleShApp, ThemeScreen


def _app(clock: FakeClock | None = None) -> BattleShApp:
    return BattleShApp(
        relay_url="ws://127.0.0.1:8765",
        grace_seconds=10.0,
        clock=clock if clock is not None else FakeClock(),
    )


def test_brand_title_is_short_centered_name() -> None:
    assert BRAND_TITLE == "battle.sh"


@pytest.mark.asyncio
async def test_opening_menu_exit_via_keys() -> None:
    """Opening lists Host / Join / Theme / Exit; Exit leaves."""
    app = _app()
    async with app.run_test() as pilot:
        await pilot.pause()
        # Exit is fourth.
        await pilot.press("down", "down", "down", "enter")
        await pilot.pause()
    assert not app.is_running


@pytest.mark.asyncio
async def test_exit_leaves_the_app() -> None:
    app = _app()
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("down", "down", "down", "enter")
        await pilot.pause()
    assert not app.is_running


@pytest.mark.asyncio
async def test_theme_opens_picker_screen() -> None:
    app = _app()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await pilot.press("down", "down", "enter")  # Theme
        await pilot.pause()
        assert isinstance(app.screen, ThemeScreen)


@pytest.mark.asyncio
async def test_two_step_ctrl_c_quits_on_opening_screen() -> None:
    clock = FakeClock(start=0.0)
    app = _app(clock)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("ctrl+c")
        await pilot.pause()
        assert app.is_running
        clock.advance(1.0)
        await pilot.press("ctrl+c")
        await pilot.pause()
    assert not app.is_running


@pytest.mark.asyncio
async def test_q_does_not_quit_on_opening_screen() -> None:
    app = _app()
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("q")
        await pilot.pause()
        assert app.is_running
        await pilot.press("ctrl+q")
        await pilot.pause()
        assert app.is_running
