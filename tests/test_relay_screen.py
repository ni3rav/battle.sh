"""In-app Relay URL: Opening menu, Save/Back, validation, status line."""

from __future__ import annotations

import pytest
from textual.widgets import Input

from battle_sh.ui.clock import FakeClock
from battle_sh.ui.textual_app import (
    BattleShApp,
    OpeningScreen,
    RelayScreen,
    normalize_relay_url,
)


def _app(relay_url: str = "ws://127.0.0.1:8765") -> BattleShApp:
    return BattleShApp(
        relay_url=relay_url,
        grace_seconds=10.0,
        clock=FakeClock(),
    )


def test_normalize_relay_url_accepts_ws_and_wss_and_strips() -> None:
    assert normalize_relay_url("  ws://127.0.0.1:8765  ") == "ws://127.0.0.1:8765"
    assert normalize_relay_url("wss://relay.example.com") == "wss://relay.example.com"
    assert normalize_relay_url("http://example.com") is None
    assert normalize_relay_url("") is None
    assert normalize_relay_url("   ") is None


@pytest.mark.asyncio
async def test_opening_shows_relay_url_and_relay_is_first_menu_item() -> None:
    app = _app("ws://127.0.0.1:8765")
    async with app.run_test() as pilot:
        await pilot.pause()
        assert isinstance(app.screen, OpeningScreen)
        assert "Relay: ws://127.0.0.1:8765" in app.screen.status_text()
        await pilot.press("enter")  # Relay first
        await pilot.pause()
        assert isinstance(app.screen, RelayScreen)


@pytest.mark.asyncio
async def test_relay_save_updates_url_pops_and_opening_shows_it() -> None:
    app = _app("ws://127.0.0.1:8765")
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert isinstance(app.screen, RelayScreen)
        relay_input = app.screen.query_one("#relay-input", Input)
        relay_input.value = "  wss://relay.example.com/path  "
        await pilot.press("enter")  # Input submit → Save
        await pilot.pause()
        assert isinstance(app.screen, OpeningScreen)
        assert app.relay_url == "wss://relay.example.com/path"
        assert "Relay: wss://relay.example.com/path" in app.screen.status_text()


@pytest.mark.asyncio
async def test_relay_save_rejects_non_websocket_scheme() -> None:
    app = _app()
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert isinstance(app.screen, RelayScreen)
        app.screen.query_one("#relay-input", Input).value = "http://nope.example"
        await pilot.press("enter")
        await pilot.pause()
        assert isinstance(app.screen, RelayScreen)
        assert "ws://" in app.screen.status_text().lower()
        assert app.relay_url == "ws://127.0.0.1:8765"


@pytest.mark.asyncio
async def test_relay_back_and_escape_discard_edits() -> None:
    app = _app("ws://127.0.0.1:8765")
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert isinstance(app.screen, RelayScreen)
        app.screen.query_one("#relay-input", Input).value = "wss://should-not-apply"
        await pilot.press("escape")
        await pilot.pause()
        assert isinstance(app.screen, OpeningScreen)
        assert app.relay_url == "ws://127.0.0.1:8765"

        await pilot.press("enter")
        await pilot.pause()
        assert isinstance(app.screen, RelayScreen)
        app.screen.query_one("#relay-input", Input).value = "wss://also-no"
        await pilot.press("tab", "down", "enter")  # Back option
        await pilot.pause()
        assert isinstance(app.screen, OpeningScreen)
        assert app.relay_url == "ws://127.0.0.1:8765"
