"""SIGINT must feed QuitArm via TerminalKeySource, not cancel without leave."""

from __future__ import annotations

import asyncio
import signal
from typing import Any
from unittest.mock import AsyncMock

import pytest

from battle_sh.networking.connection import MatchConnection
from battle_sh.ui.keys import INTERRUPT, ScriptedKeySource, TerminalKeySource
from battle_sh.ui import play as play_mod


async def test_sigint_handler_queues_interrupt_on_terminal_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    keys = TerminalKeySource()
    registered: dict[str, Any] = {}
    loop = asyncio.get_running_loop()

    def fake_add(sig: int, callback: Any) -> None:
        assert sig == signal.SIGINT
        registered["callback"] = callback

    def fake_remove(sig: int) -> None:
        registered["removed"] = sig

    def stdin_not_ready(_timeout: float) -> bool:
        return False

    monkeypatch.setattr(loop, "add_signal_handler", fake_add)
    monkeypatch.setattr(loop, "remove_signal_handler", fake_remove)
    monkeypatch.setattr("battle_sh.ui.keys._stdin_ready", stdin_not_ready)

    with play_mod._sigint_as_key_interrupt(keys):  # pyright: ignore[reportPrivateUsage]
        assert "callback" in registered
        registered["callback"]()
        assert keys.try_read(0.0) == INTERRUPT

    assert registered.get("removed") == signal.SIGINT


async def test_sigint_context_skips_scripted_key_source() -> None:
    keys = ScriptedKeySource([])
    # Must not raise even though ScriptedKeySource has no signal wiring.
    with play_mod._sigint_as_key_interrupt(keys):  # pyright: ignore[reportPrivateUsage]
        pass


async def test_leave_on_quit_sends_leave_match() -> None:
    conn = AsyncMock(spec=MatchConnection)
    conn.leave_match = AsyncMock()
    await play_mod._leave_on_quit(conn)  # pyright: ignore[reportPrivateUsage]
    conn.leave_match.assert_awaited_once()
