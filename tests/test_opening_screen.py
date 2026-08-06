"""Opening screen: brand title, Relay/Host/Join/Theme/Exit, QuitArm, q never quits."""

from __future__ import annotations

from pathlib import Path

import pytest
from rich.console import Console
from textual.widgets import Static

from battle_sh.ui.clock import FakeClock
from battle_sh.ui.textual_app import (
    BANNER,
    BANNER_MIN_WIDTH,
    BRAND_TITLE,
    BattleShApp,
    ThemeScreen,
    brand_renderable,
)


def _app(clock: FakeClock | None = None) -> BattleShApp:
    return BattleShApp(
        relay_url="ws://127.0.0.1:8765",
        grace_seconds=10.0,
        clock=clock if clock is not None else FakeClock(),
    )


def test_brand_title_is_short_centered_name() -> None:
    assert BRAND_TITLE == "battle.sh"


def test_brand_block_is_title_on_narrow_and_glyph_on_wide() -> None:
    narrow = brand_renderable(width=BANNER_MIN_WIDTH - 1)
    wide = brand_renderable(width=BANNER_MIN_WIDTH)
    assert str(narrow) == BRAND_TITLE
    assert "Terminal" not in str(narrow)
    assert str(wide) == BANNER
    assert "░██" in str(wide)


@pytest.mark.asyncio
async def test_opening_brand_follows_terminal_width() -> None:
    app = _app()
    async with app.run_test(size=(60, 24)) as pilot:
        await pilot.pause()
        brand = str(app.screen.query_one("#brand", Static).content)
        assert brand == BRAND_TITLE
    app2 = _app()
    async with app2.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        brand = str(app2.screen.query_one("#brand", Static).content)
        assert brand == BANNER


@pytest.mark.asyncio
async def test_opening_menu_exit_via_keys() -> None:
    """Opening lists Relay / Host / Join / Theme / Exit; Exit leaves."""
    app = _app()
    async with app.run_test() as pilot:
        await pilot.pause()
        # Exit is fifth.
        await pilot.press("down", "down", "down", "down", "enter")
        await pilot.pause()
    assert not app.is_running


@pytest.mark.asyncio
async def test_exit_leaves_the_app() -> None:
    app = _app()
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("down", "down", "down", "down", "enter")
        await pilot.pause()
    assert not app.is_running


@pytest.mark.asyncio
async def test_theme_opens_picker_screen() -> None:
    app = _app()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await pilot.press("down", "down", "down", "enter")  # Theme
        await pilot.pause()
        assert isinstance(app.screen, ThemeScreen)


@pytest.mark.asyncio
async def test_theme_preview_applies_live_while_browsing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    app = BattleShApp(
        relay_url="ws://127.0.0.1:8765",
        grace_seconds=10.0,
        clock=FakeClock(),
        theme_name="textual-dark",
    )
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.pause()
        await pilot.press("down", "down", "down", "enter")  # Theme
        await pilot.pause()
        assert isinstance(app.screen, ThemeScreen)
        start = app.theme
        # Browse down until the live theme changes.
        changed = False
        for _ in range(8):
            await pilot.press("down")
            await pilot.pause()
            if app.theme != start:
                changed = True
                break
        assert changed, f"theme stayed at {start!r} while browsing"
        content = app.screen.query_one("#theme-preview", Static).content
        console = Console(record=True, width=80, force_terminal=True)
        console.print(content)  # type: ignore[arg-type]
        preview = console.export_text()
        assert "Preview" in preview
        assert app.theme in preview
        # Esc restores the previously saved theme.
        await pilot.press("escape")
        await pilot.pause()
        assert app.theme == "textual-dark"


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
