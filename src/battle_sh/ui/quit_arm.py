"""Two-step quit Abandon arming via an injectable Clock."""

from __future__ import annotations

from typing import Literal

from battle_sh.ui.clock import Clock

ArmResult = Literal["warn", "confirm"]

ARM_WINDOW_SECONDS = 3.0
QUIT_WARN = "Press Ctrl+C again to quit."


class QuitArm:
    """First Ctrl+C warns; second within ``window`` seconds confirms Abandon."""

    def __init__(
        self, clock: Clock, *, window: float = ARM_WINDOW_SECONDS
    ) -> None:
        self._clock = clock
        self._window = window
        self._until: float | None = None

    @property
    def is_armed(self) -> bool:
        return self._until is not None

    def expire_if_due(self) -> None:
        if self._until is not None and self._clock.now() >= self._until:
            self._until = None

    def handle_interrupt(self) -> ArmResult:
        """Arm or confirm a quit on Ctrl+C."""
        self.expire_if_due()
        if self._until is not None:
            self._until = None
            return "confirm"
        self._until = self._clock.now() + self._window
        return "warn"
