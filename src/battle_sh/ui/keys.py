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
    """Supplies immediate key events for Placement, Aim, and wait loops."""

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
        # Default False keeps Placement/Aim keys available for read() during waits.
        self._poll_all = poll_all

    def read(self) -> Key:
        if not self._keys:
            raise EOFError("No scripted key left")
        return self._keys.popleft()

    def try_read(self, timeout: float = 0.0) -> Key | None:
        """Non-blocking poll for wait loops.

        By default, scripted sources only surface Ctrl+C here so
        Placement/Aim keys remain available for ``read()``. Pass
        ``poll_all=True`` to surface every key (Terminal-like) for tests that
        assert wait loops ignore non-quit input.
        """
        del timeout  # scripted source is non-blocking; empty means no key yet
        if not self._keys:
            return None
        front = self._keys[0]
        if self._poll_all or front.is_interrupt:
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


def _stdin_ready(timeout: float) -> bool:
    """True if stdin has a key waiting within ``timeout`` seconds.

    On Windows, ``select`` only accepts sockets (WinError 10038 on stdin), so
    we poll with ``msvcrt.kbhit`` instead.
    """
    import sys

    if sys.platform == "win32":
        import msvcrt
        import time

        if timeout <= 0:
            return bool(msvcrt.kbhit())
        deadline = time.monotonic() + timeout
        while True:
            if msvcrt.kbhit():
                return True
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            time.sleep(min(0.01, remaining))

    import select

    ready, _, _ = select.select([sys.stdin], [], [], timeout)
    return bool(ready)


class TerminalKeySource:
    """Production KeySource: reads raw terminal keys via readchar.

    ``request_interrupt`` lets the Match SIGINT handler inject Ctrl+C into the
    same QuitArm path used for typed ``\\x03``, without cancelling the asyncio
    task (which would skip ``leave_match``).
    """

    def __init__(self) -> None:
        self._interrupt_requested = False

    def request_interrupt(self) -> None:
        """Queue a Ctrl+C for the next ``read`` / ``try_read`` (SIGINT path)."""
        self._interrupt_requested = True

    def read(self) -> Key:
        while True:
            if self._interrupt_requested:
                self._interrupt_requested = False
                return INTERRUPT
            if _stdin_ready(0.05):
                return self._read_ready_key()

    def try_read(self, timeout: float = 0.0) -> Key | None:
        if self._interrupt_requested:
            self._interrupt_requested = False
            return INTERRUPT
        if not _stdin_ready(timeout):
            return None
        return self._read_ready_key()

    def _read_ready_key(self) -> Key:
        try:
            raw = readchar.readkey()
        except KeyboardInterrupt:
            # readchar raises on Ctrl+C; map into the KeySource quit path.
            return INTERRUPT
        name = _RAW_TO_NAME.get(raw)
        if name is not None:
            return Key(name)
        if len(raw) == 1 and raw.isprintable():
            return Key(raw.lower())
        return Key(raw)
