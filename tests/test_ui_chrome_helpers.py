"""Theme persistence and Match-end / ship-progress helpers."""

from __future__ import annotations

from pathlib import Path

from battle_sh.networking.connection import MatchEnd
from battle_sh.networking.protocol import MatchOutcome
from battle_sh.rules.board import ShotResultKind
from battle_sh.rules.placement import Coordinate, Placement, coordinate
from battle_sh.ui.boards import (
    AIM_GLYPH,
    EMPTY_GLYPH,
    HIT_GLYPH,
    MISS_GLYPH,
    SUNK_GLYPH,
    own_board_renderable,
    tracking_board_renderable,
)
from battle_sh.ui.match_end_copy import match_end_detail, match_end_headline
from battle_sh.ui.ship_progress import enemy_ship_rows, your_ship_rows
from battle_sh.ui.theme_config import load_theme_name, save_theme_name
from rich.console import Console


def test_theme_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    assert load_theme_name(path=path) == "textual-dark"
    save_theme_name("dracula", path=path)
    assert load_theme_name(path=path) == "dracula"


def test_match_end_copy_win_loss_abandoned() -> None:
    win = MatchEnd(outcome=MatchOutcome.WINNER, winner="host")
    assert match_end_headline("host", win) == "You win"
    assert match_end_headline("guest", win) == "Opponent Won"
    abandoned = MatchEnd(outcome=MatchOutcome.ABANDONED, reason="left")
    assert match_end_headline("host", abandoned) == "Match Abandoned"
    assert match_end_detail("host", abandoned) == "You left"


def test_your_and_enemy_ship_progress_honest() -> None:
    placement = Placement(
        {
            "Carrier": frozenset(coordinate(c, 1) for c in "ABCDE"),
            "Battleship": frozenset(coordinate(c, 2) for c in "ABCD"),
            "Cruiser": frozenset(coordinate(c, 3) for c in "ABC"),
            "Submarine": frozenset(coordinate(c, 4) for c in "ABC"),
            "Destroyer": frozenset(coordinate(c, 5) for c in "AB"),
        }
    )
    marks: dict[Coordinate, ShotResultKind] = {
        coordinate("A", 5): "sunk",
        coordinate("B", 5): "sunk",
        coordinate("A", 1): "hit",
    }
    yours = {name: (progress, status) for name, progress, status in your_ship_rows(placement, marks)}
    assert yours["Destroyer"] == ("2/2", "sunk")
    assert yours["Carrier"] == ("1/5", "afloat")
    enemy = {
        name: (progress, status) for name, progress, status in enemy_ship_rows(["Destroyer"])
    }
    assert enemy["Destroyer"] == ("2/2", "sunk")
    assert enemy["Carrier"] == ("—/5", "unknown")


def test_board_glyphs_are_distinct() -> None:
    placement = Placement(
        {
            "Carrier": frozenset(coordinate(c, 1) for c in "ABCDE"),
            "Battleship": frozenset(coordinate(c, 2) for c in "ABCD"),
            "Cruiser": frozenset(coordinate(c, 3) for c in "ABC"),
            "Submarine": frozenset(coordinate(c, 4) for c in "ABC"),
            "Destroyer": frozenset(coordinate(c, 5) for c in "AB"),
        }
    )
    own_marks: dict[Coordinate, ShotResultKind] = {
        coordinate("J", 10): "miss",
        coordinate("A", 1): "hit",
        coordinate("A", 5): "sunk",
        coordinate("B", 5): "sunk",
    }
    console = Console(record=True, width=40, force_terminal=True)
    console.print(own_board_renderable(placement, own_marks))
    own_text = console.export_text()
    assert EMPTY_GLYPH in own_text
    assert MISS_GLYPH in own_text
    assert HIT_GLYPH in own_text
    assert SUNK_GLYPH in own_text

    console2 = Console(record=True, width=40, force_terminal=True)
    console2.print(
        tracking_board_renderable({}, frozenset(), aim=coordinate("E", 5))
    )
    assert AIM_GLYPH in console2.export_text()


def test_compact_own_board_is_narrower_than_default() -> None:
    placement = Placement(
        {
            "Carrier": frozenset(coordinate(c, 1) for c in "ABCDE"),
            "Battleship": frozenset(coordinate(c, 2) for c in "ABCD"),
            "Cruiser": frozenset(coordinate(c, 3) for c in "ABC"),
            "Submarine": frozenset(coordinate(c, 4) for c in "ABC"),
            "Destroyer": frozenset(coordinate(c, 5) for c in "AB"),
        }
    )
    full = Console(record=True, width=40, force_terminal=True)
    full.print(own_board_renderable(placement, {}))
    compact = Console(record=True, width=40, force_terminal=True)
    compact.print(own_board_renderable(placement, {}, compact=True))
    full_lines = [line.rstrip() for line in full.export_text().splitlines() if line.strip()]
    compact_lines = [
        line.rstrip() for line in compact.export_text().splitlines() if line.strip()
    ]
    assert max(len(line) for line in compact_lines) < max(len(line) for line in full_lines)
    assert "10" in compact.export_text()
    assert "Your fleet" in compact.export_text()