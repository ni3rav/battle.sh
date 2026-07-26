"""Injectable immediate-key source for Placement/Aim key-rule tests."""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class Key:
    """A single immediate key event.

    ``name`` is a stable token such as ``\"w\"``, ``\"up\"``, ``\"tab\"``,
    ``\"shift+tab\"``, ``\"enter\"``, ``\"space\"``, or ``\"ctrl+c\"``.
    """

    name: str

    @property
    def is_interrupt(self) -> bool:
        return self.name == "ctrl+c"


INTERRUPT = Key("ctrl+c")

# WASD + arrows → (column_delta, row_delta) for Placement and Aim movement.
MOVE_DELTA: dict[str, tuple[int, int]] = {
    "w": (0, -1),
    "a": (-1, 0),
    "s": (0, 1),
    "d": (1, 0),
    "up": (0, -1),
    "left": (-1, 0),
    "down": (0, 1),
    "right": (1, 0),
}


def key_token(key: Key) -> str:
    """Stable lowercase token for key handling (``shift+tab`` stays intact)."""
    return key.name.lower()


class KeySource(Protocol):
    """Supplies immediate key events for Placement and Aim key-rule tests."""

    def read(self) -> Key: ...

    def try_read(self, timeout: float = 0.0) -> Key | None: ...


class ScriptedKeySource:
    """Test double: yields a predetermined key sequence without a terminal."""

    def __init__(
        self, keys: Iterable[Key | str], *, poll_all: bool = False
    ) -> None:
        self._keys: deque[Key] = deque(
            key if isinstance(key, Key) else Key(key) for key in keys
        )
        # When True, try_read surfaces every key (for wait-loop ignore tests).
        # Default False keeps Placement/Aim keys available for read().
        self._poll_all = poll_all

    def read(self) -> Key:
        if not self._keys:
            raise EOFError("No scripted key left")
        return self._keys.popleft()

    def try_read(self, timeout: float = 0.0) -> Key | None:
        """Non-blocking poll.

        By default, scripted sources only surface Ctrl+C here so
        Placement/Aim keys remain available for ``read()``. Pass
        ``poll_all=True`` to surface every key for ignore-input tests.
        """
        del timeout  # scripted source is non-blocking; empty means no key yet
        if not self._keys:
            return None
        front = self._keys[0]
        if self._poll_all or front.is_interrupt:
            return self._keys.popleft()
        return None
