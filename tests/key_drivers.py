"""Test-only drivers: scripted keys looping ``apply_*_key`` (key-rule seam)."""

from __future__ import annotations

from collections import deque
from collections.abc import Callable, Iterable

from battle_sh.rules.placement import Coordinate, Placement, random_placement
from battle_sh.ui.aim_flow import apply_aim_key, initial_aim
from battle_sh.ui.clock import Clock
from battle_sh.ui.keys import INTERRUPT, Key
from battle_sh.ui.placement_flow import QuitRequested, apply_placement_key
from battle_sh.ui.quit_arm import QuitArm


class ScriptedKeySource:
    """Yields a predetermined key sequence without a terminal."""

    def __init__(
        self, keys: Iterable[Key | str], *, poll_all: bool = False
    ) -> None:
        self._keys: deque[Key] = deque(
            key if isinstance(key, Key) else Key(key) for key in keys
        )
        self._poll_all = poll_all

    def read(self) -> Key:
        if not self._keys:
            raise EOFError("No scripted key left")
        return self._keys.popleft()

    def try_read(self, timeout: float = 0.0) -> Key | None:
        del timeout
        if not self._keys:
            return None
        front = self._keys[0]
        if self._poll_all or front.is_interrupt:
            return self._keys.popleft()
        return None


def run_aim(
    keys: ScriptedKeySource,
    *,
    fired: frozenset[Coordinate],
    start: Coordinate | None = None,
    on_cursor: Callable[[Coordinate], None] | None = None,
    clock: Clock | None = None,
) -> Coordinate:
    """Drive ``apply_aim_key`` until fire or quit (key-rule tests)."""
    aim = initial_aim(start, fired)
    arm = QuitArm(clock) if clock is not None else None
    status = ""
    while True:
        if arm is not None:
            arm.expire_if_due()
        if on_cursor is not None:
            on_cursor(aim)
        aim, status, action = apply_aim_key(
            keys.read(), aim, status, fired=fired, arm=arm
        )
        if action == "quit":
            raise QuitRequested
        if action == "fire":
            return aim


def run_placement(
    keys: ScriptedKeySource,
    *,
    on_message: Callable[[str], None] | None = None,
    placement_factory: Callable[[], Placement] | None = None,
    clock: Clock | None = None,
) -> Placement:
    """Drive ``apply_placement_key`` until lock or quit (key-rule tests)."""
    factory = placement_factory or random_placement
    placement = factory()
    selected: str | None = None
    arm = QuitArm(clock) if clock is not None else None
    while True:
        if arm is not None:
            arm.expire_if_due()
        placement, selected, action, message = apply_placement_key(
            keys.read(),
            placement,
            selected,
            factory=factory,
            arm=arm,
        )
        if message is not None and on_message is not None:
            on_message(message)
        if action == "quit":
            raise QuitRequested
        if action == "lock":
            return placement


__all__ = [
    "INTERRUPT",
    "Key",
    "ScriptedKeySource",
    "run_aim",
    "run_placement",
]
