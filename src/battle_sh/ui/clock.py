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
