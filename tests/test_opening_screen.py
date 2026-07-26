"""Opening screen: banner, Host/Join/Exit, Exit quit, QuitArm, q never quits."""

from __future__ import annotations

import pytest

from battle_sh.ui.clock import FakeClock
from battle_sh.ui.textual_app import BANNER, BattleShApp

# Independent copy of the #20 Further Notes banner (glyph layout).
EXPECTED_BANNER = (
    '░██                      ░██       ░██    ░██                           ░██        \n'
    '░██                      ░██       ░██    ░██                           ░██        \n'
    '░████████   ░██████   ░████████ ░████████ ░██  ░███████       ░███████  ░████████  \n'
    '░██    ░██       ░██     ░██       ░██    ░██ ░██    ░██     ░██        ░██    ░██ \n'
    '░██    ░██  ░███████     ░██       ░██    ░██ ░█████████      ░███████  ░██    ░██ \n'
    '░███   ░██ ░██   ░██     ░██       ░██    ░██ ░██                   ░██ ░██    ░██ \n'
    '░██░█████   ░█████░██     ░████     ░████ ░██  ░███████  ░██  ░███████  ░██    ░██ '
)


def _app(clock: FakeClock | None = None) -> BattleShApp:
    return BattleShApp(
        relay_url="ws://127.0.0.1:8765",
        grace_seconds=10.0,
        clock=clock if clock is not None else FakeClock(),
    )


def test_banner_matches_issue_glyph_layout() -> None:
    assert BANNER == EXPECTED_BANNER


@pytest.mark.asyncio
async def test_opening_menu_host_join_exit_via_keys() -> None:
    app = _app()
    async with app.run_test() as pilot:
        await pilot.pause()
        # Host (default highlight)
        await pilot.press("enter")
        await pilot.pause()
        assert app.is_running
        # Join
        await pilot.press("down", "enter")
        await pilot.pause()
        assert app.is_running
        # Exit
        await pilot.press("down", "enter")
        await pilot.pause()
    assert not app.is_running


@pytest.mark.asyncio
async def test_exit_leaves_the_app() -> None:
    app = _app()
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("down", "down", "enter")
        await pilot.pause()
    assert not app.is_running


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
