"""Read immediate keys without blocking the asyncio event loop.

The terminal key read (:func:`KeySource.read`) is synchronous and blocks until a
key arrives. Calling it directly from a coroutine would freeze the event loop,
which starves the WebSocket keepalive and eventually drops the Match. Reading on
a worker thread keeps the loop free to answer pings, while the periodic refresh
runs on the loop thread so all rich rendering stays single-threaded.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable, Callable

from rich.live import Live

from battle_sh.ui.keys import Key, KeySource


async def read_key_off_loop(
    keys: KeySource,
    *,
    live: Live | None = None,
    render: Callable[[], object] | None = None,
    refresh_interval: float = 1.0,
    async_on_tick: Callable[[], Awaitable[None]] | None = None,
) -> Key:
    """Await one key on a worker thread, refreshing ``live`` on the loop thread."""
    task: asyncio.Task[Key] = asyncio.ensure_future(asyncio.to_thread(keys.read))
    try:
        while True:
            done, _ = await asyncio.wait({task}, timeout=refresh_interval)
            if async_on_tick is not None:
                await async_on_tick()
            if live is not None and render is not None:
                live.update(render(), refresh=True)  # type: ignore[arg-type]
            if task in done:
                return task.result()
    finally:
        if not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
