"""Injectable immediate-key source for Match UI (no TTY required in tests)."""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol

import readchar


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

    def try_read(self, timeout: float = 0.0) -> Key | None: ...


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

    def try_read(self, timeout: float = 0.0) -> Key | None:
        """Non-blocking poll for wait loops.

        Scripted sources only surface ``q`` / Ctrl+C here so Placement/Aim
        keys remain available for ``read()``. Terminal sources return any
        ready key (callers ignore non-quit keys while waiting).
        """
        del timeout  # scripted source is non-blocking; empty means no key yet
        if not self._keys:
            return None
        front = self._keys[0]
        if front.name.lower() == "q" or front.is_interrupt:
            return self._keys.popleft()
        return None


_RAW_TO_NAME: dict[str, str] = {
    readchar.key.UP: "up",
    readchar.key.DOWN: "down",
    readchar.key.LEFT: "left",
    readchar.key.RIGHT: "right",
    readchar.key.TAB: "tab",
    # CSI Z — Shift+Tab (readchar.key.SHIFT_TAB; stubs omit it on some platforms)
    "\x1b[Z": "shift+tab",
    readchar.key.ENTER: "enter",
    readchar.key.CR: "enter",
    readchar.key.SPACE: "space",
    readchar.key.CTRL_C: "ctrl+c",
}


class TerminalKeySource:
    """Production KeySource: reads raw terminal keys via readchar."""

    def read(self) -> Key:
        raw = readchar.readkey()
        name = _RAW_TO_NAME.get(raw)
        if name is not None:
            return Key(name)
        if len(raw) == 1 and raw.isprintable():
            return Key(raw.lower())
        return Key(raw)

    def try_read(self, timeout: float = 0.0) -> Key | None:
        import select
        import sys

        ready, _, _ = select.select([sys.stdin], [], [], timeout)
        if not ready:
            return None
        return self.read()
