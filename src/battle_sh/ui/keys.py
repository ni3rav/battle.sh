"""Injectable immediate-key source for Match UI (no TTY required in tests)."""

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


class KeySource(Protocol):
    """Supplies immediate key events for Placement, Aim, and wait loops."""

    def read(self) -> Key: ...


class ScriptedKeySource:
    """Test double: yields a predetermined key sequence without a terminal."""

    def __init__(self, keys: Iterable[Key | str]) -> None:
        self._keys: deque[Key] = deque(
            key if isinstance(key, Key) else Key(key) for key in keys
        )

    def read(self) -> Key:
        if not self._keys:
            raise EOFError("No scripted key left")
        return self._keys.popleft()
