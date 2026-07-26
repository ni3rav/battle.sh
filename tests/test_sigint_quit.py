"""SIGINT must feed the same QuitArm path as typed Ctrl+C."""

from __future__ import annotations

import asyncio
import signal
from typing import Any

import pytest

from battle_sh.ui.clock import FakeClock
from battle_sh.ui.quit_arm import QUIT_WARN
from battle_sh.ui.textual_app import BattleShApp, OpeningScreen


@pytest.mark.asyncio
async def test_sigint_feeds_quit_arm_same_as_ctrl_c(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registered: dict[str, Any] = {}
    loop = asyncio.get_running_loop()

    def fake_add(sig: int, callback: Any) -> None:
        assert sig == signal.SIGINT
        registered["callback"] = callback

    def fake_remove(sig: int) -> None:
        registered["removed"] = sig

    monkeypatch.setattr(loop, "add_signal_handler", fake_add)
    monkeypatch.setattr(loop, "remove_signal_handler", fake_remove)

    clock = FakeClock(start=0.0)
    app = BattleShApp(
        relay_url="ws://127.0.0.1:8765",
        grace_seconds=10.0,
        clock=clock,
    )
    async with app.run_test() as pilot:
        await pilot.pause()
        assert "callback" in registered
        assert not app.quit_arm.is_armed

        registered["callback"]()
        await pilot.pause()
        assert app.quit_arm.is_armed
        assert isinstance(app.screen, OpeningScreen)
        assert app.is_running

        clock.advance(1.0)
        registered["callback"]()
        await pilot.pause()

    assert not app.is_running
    assert registered.get("removed") == signal.SIGINT


@pytest.mark.asyncio
async def test_sigint_warn_copy_matches_ctrl_c_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registered: dict[str, Any] = {}
    loop = asyncio.get_running_loop()

    def fake_add(_sig: int, callback: Any) -> None:
        registered["callback"] = callback

    def fake_remove(_sig: int) -> None:
        return None

    monkeypatch.setattr(loop, "add_signal_handler", fake_add)
    monkeypatch.setattr(loop, "remove_signal_handler", fake_remove)

    app = BattleShApp(
        relay_url="ws://127.0.0.1:8765",
        grace_seconds=10.0,
        clock=FakeClock(),
    )
    async with app.run_test() as pilot:
        await pilot.pause()
        registered["callback"]()
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, OpeningScreen)
        status = getattr(screen, "query_one")("#status").content
        assert QUIT_WARN in str(status)
