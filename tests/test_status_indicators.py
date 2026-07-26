"""Scoreboard and connection-line chrome (Textual info/sidebar seam)."""

from __future__ import annotations

from battle_sh.ui.shell import MatchStatus, connection_line, scoreboard_renderable
from rich.console import Console


def _export(frame: object, *, width: int = 80, height: int = 36) -> str:
    console = Console(record=True, width=width, height=height, force_terminal=True)
    console.print(frame)  # type: ignore[arg-type]
    return console.export_text()


def _status(
    *,
    turn: str = "You",
    state: str = "Combat",
    you: bool = True,
    opp: bool = True,
    synced: bool = True,
) -> MatchStatus:
    return MatchStatus(
        role="Host",
        state=state,
        turn=turn,
        your_ships_afloat=4,
        your_ships_total=5,
        enemy_ships_afloat=3,
        enemy_ships_total=5,
        your_hits=7,
        enemy_hits=5,
        total_cells=17,
        you_connected=you,
        opponent_connected=opp,
        synchronized=synced,
        your_fleet=(
            ("Carrier", True),
            ("Battleship", False),
            ("Cruiser", True),
            ("Submarine", True),
            ("Destroyer", True),
        ),
        enemy_sunk=("Destroyer", "Cruiser"),
    )


def test_scoreboard_shows_ships_hits_and_fleet_detail() -> None:
    text = _export(scoreboard_renderable(_status()))
    assert "Ships afloat" in text
    assert "4/5" in text  # your ships afloat
    assert "3/5" in text  # enemy ships afloat
    assert "Hits" in text
    assert "7/17" in text
    assert "5/17" in text
    assert "Battleship" in text and "SUNK" in text
    assert "afloat" in text
    assert "Enemy sunk" in text
    assert "Destroyer" in text


def test_connection_line_marks_link_sync_and_turn() -> None:
    line = connection_line(_status(turn="You"))
    assert "Link:" in line
    assert "in sync" in line
    assert "Turn: [bold]You[/]" in line


def test_disconnected_opponent_shows_open_dot() -> None:
    line = connection_line(_status(state="Lobby", turn="—", opp=False))
    assert "Link:" in line
    assert "○" in line  # opponent not connected yet
    assert "●" in line  # host connected
