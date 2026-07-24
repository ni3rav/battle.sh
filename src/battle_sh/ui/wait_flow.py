"""Wait loops that honor only q / two-step Ctrl+C while an awaitable runs."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import TypeVar

from battle_sh.ui.clock import Clock
from battle_sh.ui.keys import KeySource
from battle_sh.ui.placement_flow import QuitRequested
from battle_sh.ui.quit_arm import QUIT_WARN, QuitArm

T = TypeVar("T")


async def wait_honoring_quit(
    awaitable: Awaitable[T],
    *,
    keys: KeySource,
    clock: Clock,
    on_message: Callable[[str], None] | None = None,
    on_tick: Callable[[], None] | None = None,
    poll_timeout: float = 0.05,
) -> T:
    """Await ``awaitable`` while accepting only ``q`` / Ctrl+C to Abandon.

    Both quit keys share a two-step confirm (``QuitArm``): first warns, second
    within the arm window raises ``QuitRequested``.
    """
    arm = QuitArm(clock)
    task = asyncio.ensure_future(awaitable)
    try:
        while not task.done():
            if on_tick is not None:
                on_tick()
            arm.expire_if_due()
            key = keys.try_read(poll_timeout)
            if key is not None:
                token = key.name.lower()
                if token == "q" or key.is_interrupt:
                    if arm.handle_interrupt() == "confirm":
                        raise QuitRequested
                    if on_message is not None:
                        on_message(QUIT_WARN)
                # Non-quit keys from a TTY poll are ignored while waiting.
            try:
                return await asyncio.wait_for(asyncio.shield(task), timeout=poll_timeout)
            except TimeoutError:
                continue
        return await task
    except QuitRequested:
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass
        raise
