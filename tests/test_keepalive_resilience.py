"""Regression tests for WebSocket keepalive while a Match is idle.

The old Rich Live path blocked the asyncio loop with on-loop key reads, so the
client stopped answering Relay pings during Placement/Aim. Textual keys are
handled on the app loop; these tests pin that an idle connected client still
survives aggressive keepalive, and that the Relay survives a vanishing peer.
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Generator
from contextlib import contextmanager

import pytest

from battle_sh.networking import connection as connection_mod
from battle_sh.networking import relay as relay_mod
from battle_sh.networking.connection import MatchConnection
from battle_sh.networking.protocol import MsgType
from battle_sh.networking.relay import start_relay
from battle_sh.rules.placement import Placement, coordinate


def _placement_a() -> Placement:
    return Placement(
        {
            "Carrier": frozenset(coordinate(c, 10) for c in "ABCDE"),
            "Battleship": frozenset(coordinate(c, 9) for c in "ABCD"),
            "Cruiser": frozenset(coordinate(c, 8) for c in "ABC"),
            "Submarine": frozenset(coordinate(c, 7) for c in "ABC"),
            "Destroyer": frozenset(coordinate("A", r) for r in (1, 2)),
        }
    )


def _placement_b() -> Placement:
    return Placement(
        {
            "Carrier": frozenset(coordinate(c, 1) for c in "ABCDE"),
            "Battleship": frozenset(coordinate(c, 2) for c in "ABCD"),
            "Cruiser": frozenset(coordinate(c, 3) for c in "ABC"),
            "Submarine": frozenset(coordinate(c, 4) for c in "ABC"),
            "Destroyer": frozenset(coordinate("J", r) for r in (10, 9)),
        }
    )


@contextmanager
def _relay_in_background_thread() -> Generator[str, None, None]:
    """Run the Relay on its own event loop/thread so its keepalive is independent."""
    loop = asyncio.new_event_loop()
    ready = threading.Event()
    url_holder: dict[str, str] = {}
    stop_holder: dict[str, asyncio.Event] = {}

    async def _serve() -> None:
        stop = asyncio.Event()
        stop_holder["stop"] = stop
        async with start_relay("127.0.0.1", 0) as url:
            url_holder["url"] = url
            ready.set()
            await stop.wait()

    def _run() -> None:
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(_serve())
            pending = asyncio.all_tasks(loop)
            for task in pending:
                task.cancel()
            loop.run_until_complete(
                asyncio.gather(*pending, return_exceptions=True)
            )
        finally:
            loop.close()

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    assert ready.wait(5.0), "Relay thread failed to start"
    try:
        yield url_holder["url"]
    finally:
        loop.call_soon_threadsafe(stop_holder["stop"].set)
        thread.join(5.0)


async def test_idle_match_does_not_trigger_keepalive_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An idle connected client still answers pings through a long think pause."""
    for module in (relay_mod, connection_mod):
        monkeypatch.setattr(module, "KEEPALIVE_PING_INTERVAL", 0.2)
        monkeypatch.setattr(module, "KEEPALIVE_PING_TIMEOUT", 0.2)

    with _relay_in_background_thread() as relay_url:
        host = await MatchConnection.connect(relay_url)
        guest = await MatchConnection.connect(relay_url)
        try:
            invite = await host.create_match()
            await guest.join_match(invite)
            await host.wait_for_player_joined()

            # Think far longer than the ping timeout; the loop must stay alive.
            await asyncio.sleep(1.5)

            await host.lock_placement(_placement_a())
            await guest.lock_placement(_placement_b())
            await host.wait_for_opponent_commitment()
            await guest.wait_for_opponent_commitment()
            assert host.ready_to_fire
        finally:
            await guest.close()
            await host.close()


async def test_relay_survives_client_vanishing_mid_exchange() -> None:
    """A client that closes while the Relay is replying must not crash serving."""
    async with start_relay() as relay_url:
        gone = await MatchConnection.connect(relay_url)
        await gone.create_match()
        # Send a message that makes the Relay reply, then close before it can.
        await gone._send(  # pyright: ignore[reportPrivateUsage]
            {"type": MsgType.SHOT, "coordinate": "A1"}
        )
        await gone.close()
        await asyncio.sleep(0.1)

        # The Relay must remain healthy for new Matches.
        survivor = await MatchConnection.connect(relay_url)
        try:
            invite = await survivor.create_match()
            assert invite
        finally:
            await survivor.close()
