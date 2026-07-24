"""Combat three-band frame: opponent Aim wide, own Board compact, phase controls."""

from __future__ import annotations

from battle_sh.rules.board import ShotResultKind
from battle_sh.rules.placement import Coordinate, Placement, coordinate
from battle_sh.ui.shell import CombatBoards, combat_frame, combat_wait_frame
from rich.console import Console


def _fixed_placement() -> Placement:
    return Placement(
        {
            "Carrier": frozenset(coordinate(c, 1) for c in "ABCDE"),
            "Battleship": frozenset(coordinate(c, 2) for c in "ABCD"),
            "Cruiser": frozenset(coordinate(c, 3) for c in "ABC"),
            "Submarine": frozenset(coordinate(c, 4) for c in "ABC"),
            "Destroyer": frozenset(coordinate(c, 5) for c in "AB"),
        }
    )


def _boards(
    *,
    own_marks: dict[Coordinate, ShotResultKind] | None = None,
    tracking: dict[Coordinate, ShotResultKind] | None = None,
) -> CombatBoards:
    return CombatBoards(
        placement=_fixed_placement(),
        own_marks=own_marks or {},
        tracking=tracking or {},
        revealed=frozenset(),
    )


def _export(frame: object) -> str:
    # Tall enough for stacked Aim controls above the compact scoreboard.
    console = Console(record=True, width=80, height=36, force_terminal=True)
    console.print(frame)  # type: ignore[arg-type]
    return console.export_text()


def test_combat_frame_opponent_wide_own_compact_aim_controls() -> None:
    boards = _boards(
        tracking={coordinate("B", 7): "miss"},
        own_marks={coordinate("A", 1): "hit"},
    )
    text = _export(
        combat_frame(
            role="Host",
            match_time="0:42",
            boards=boards,
            aim=coordinate("C", 5),
            status="Your turn",
        )
    )
    assert "Host" in text
    assert "Match time 0:42" in text
    assert "Your turn" in text or "Aim" in text
    assert "Opponent — Aim" in text
    assert "Your fleet" in text
    lower = text.lower()
    assert "fire" in lower
    assert "w/a/s/d" in lower or "wasd" in lower or "move" in lower
    assert "ctrl+c" in lower
    assert "→ quit" in text
    assert "→ fire" in text
    assert "→ move" in text
    assert "`f`" in text or "`Ctrl+C`" in text
    assert "q /" not in lower and "q/" not in lower
    assert "lock" not in lower


def test_combat_wait_frame_spinner_and_quit_keys_only() -> None:
    text = _export(
        combat_wait_frame(
            role="Guest",
            match_time="1:05",
            boards=_boards(),
            spinner_frame=1,
            status="Waiting for opponent…",
        )
    )
    assert "Match time 1:05" in text
    assert "Waiting" in text
    assert "/" in text  # spinner_frame=1 → "/"
    lower = text.lower()
    assert "ctrl+c" in lower
    assert "→ quit" in text
    assert "fire" not in lower
    assert "lock" not in lower
    assert "q /" not in lower and "q/" not in lower
