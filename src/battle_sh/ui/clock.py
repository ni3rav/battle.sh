"""Injectable clock for Match elapsed time and timed Ctrl+C arming."""

from __future__ import annotations

import time
from typing import Protocol


class Clock(Protocol):
    """Supplies monotonic \"now\" for Match UI timing."""

    def now(self) -> float: ...


class SystemClock:
    """Production clock backed by ``time.monotonic``."""

    def now(self) -> float:
        return time.monotonic()


class FakeClock:
    """Test double: deterministic time that only moves when advanced."""

    def __init__(self, start: float = 0.0) -> None:
        self._now = start

    def now(self) -> float:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += seconds


def format_elapsed(seconds: float) -> str:
    """Format Match elapsed time as ``m:ss`` (or ``h:mm:ss`` when needed)."""
    total = max(0, int(seconds))
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"
