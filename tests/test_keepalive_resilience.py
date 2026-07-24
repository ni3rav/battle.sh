"""Regression tests for the WebSocket keepalive ping-timeout disconnect.

The Match dropped with ``1011 keepalive ping timeout`` because the UI read keys
with a blocking call on the asyncio event loop, so the client could not answer
the Relay's keepalive pings while a Player was thinking. These tests pin the fix:
key reads happen off the loop, so the loop keeps servicing keepalive.
"""

from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import Generator
from contextlib import contextmanager

import pytest

from battle_sh.networking import connection as connection_mod
from battle_sh.networking import relay as relay_mod
from battle_sh.networking.connection import MatchConnection
from battle_sh.networking.protocol import MsgType
from battle_sh.networking.relay import start_relay
from battle_sh.rules.placement import Placement, coordinate
from battle_sh.ui.aim_flow import run_aim_async
from battle_sh.ui.keys import Key, KeySource
from battle_sh.ui.placement_flow import run_placement_async


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
    """Run the Relay on its own event loop/thread so its keepalive is independent.

    An in-process Relay shares the client's event loop, so blocking that loop
    would freeze both ends and never fire a timeout. A separate loop lets the
    Relay actually time out a client that stops answering pings.
    """
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


class _GatedKeySource:
    """KeySource whose ``read`` blocks the calling thread until released."""

    def __init__(self, key: Key, gate: threading.Event) -> None:
        self._key = key
        self._gate = gate

    def read(self) -> Key:
        self._gate.wait(2.0)
        return self._key

    def try_read(self, timeout: float = 0.0) -> Key | None:
        return None


class _DelayFirstReadKeySource:
    """Blocks the first ``read`` by ``delay`` seconds to mimic a thinking Player."""

    def __init__(self, keys: list[str], *, delay: float) -> None:
        self._keys = list(keys)
        self._delay = delay
        self._delayed = False
        self._index = 0

    def read(self) -> Key:
        if not self._delayed:
            self._delayed = True
            time.sleep(self._delay)
        key = self._keys[self._index]
        self._index += 1
        return Key(key)

    def try_read(self, timeout: float = 0.0) -> Key | None:
        return None


async def test_run_aim_async_does_not_block_the_event_loop() -> None:
    """While a key read is pending, other coroutines keep making progress."""
    gate = threading.Event()
    keys: KeySource = _GatedKeySource(Key("f"), gate)

    ticks = 0

    async def heartbeat() -> None:
        nonlocal ticks
        for _ in range(5):
            await asyncio.sleep(0.02)
            ticks += 1

    aim_task = asyncio.create_task(
        run_aim_async(keys, fired=frozenset())
    )
    await heartbeat()

    # The loop ran the heartbeat to completion even though the key read is still
    # blocked — a blocking on-loop read would have frozen it at zero ticks.
    assert ticks == 5
    assert not aim_task.done()

    gate.set()
    aim = await asyncio.wait_for(aim_task, timeout=2.0)
    assert aim == coordinate("A", 1)


async def test_run_placement_async_does_not_block_the_event_loop() -> None:
    gate = threading.Event()
    keys: KeySource = _GatedKeySource(Key("y"), gate)

    ticks = 0

    async def heartbeat() -> None:
        nonlocal ticks
        for _ in range(5):
            await asyncio.sleep(0.02)
            ticks += 1

    task = asyncio.create_task(
        run_placement_async(keys, placement_factory=_placement_a)
    )
    await heartbeat()

    assert ticks == 5
    assert not task.done()

    gate.set()
    placement = await asyncio.wait_for(task, timeout=2.0)
    assert placement == _placement_a()


async def test_slow_turn_does_not_trigger_keepalive_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A slow (blocking) Placement no longer drops the Relay connection.

    With an aggressive keepalive and the Relay on its own loop, a turn that idles
    far longer than the ping timeout would previously be closed with 1011.
    Because key reads run off the loop, the client keeps answering pings and the
    connection survives an end-to-end slow turn.
    """
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

            # "Think" for 1.5s (7.5x the ping timeout) while arranging ships. The
            # read blocks a worker thread, not the event loop, so the client keeps
            # answering the Relay's pings.
            slow_keys = _DelayFirstReadKeySource(["y"], delay=1.5)
            placement = await run_placement_async(
                slow_keys, placement_factory=_placement_a
            )

            # If the slow turn had starved the loop, the Relay (separate loop)
            # would have closed this connection and lock_placement would raise.
            await host.lock_placement(placement)
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
