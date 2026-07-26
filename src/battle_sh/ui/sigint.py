"""Install OS SIGINT into a callback (same path as typed Ctrl+C / QuitArm)."""

from __future__ import annotations

import asyncio
import contextlib
import signal
from collections.abc import Callable


def install_sigint(callback: Callable[[], None]) -> bool:
    """Register ``callback`` for SIGINT. Returns True if installed."""
    try:
        asyncio.get_running_loop().add_signal_handler(signal.SIGINT, callback)
    except (NotImplementedError, RuntimeError, ValueError):
        return False
    return True


def uninstall_sigint() -> None:
    """Remove the SIGINT handler if one was installed on this loop."""
    with contextlib.suppress(NotImplementedError, RuntimeError, ValueError):
        asyncio.get_running_loop().remove_signal_handler(signal.SIGINT)
