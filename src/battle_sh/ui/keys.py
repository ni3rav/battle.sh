"""Key tokens shared by Placement/Aim rules and the Textual screens."""

from __future__ import annotations

from dataclasses import dataclass


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
