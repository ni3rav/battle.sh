"""Real-time status indicators: scoreboard, connection, turn, and match state."""

from __future__ import annotations

from battle_sh.rules.placement import Placement, coordinate
from battle_sh.ui.shell import (
    CombatBoards,
    MatchStatus,
    combat_frame,
    combat_wait_frame,
    lobby_frame,
    scoreboard_renderable,
    wait_frame,
)
from rich.console import Console


def _placement() -> Placement:
    return Placement(
        {
            "Carrier": frozenset(coordinate(c, 1) for c in "ABCDE"),
            "Battleship": frozenset(coordinate(c, 2) for c in "ABCD"),
            "Cruiser": frozenset(coordinate(c, 3) for c in "ABC"),
            "Submarine": frozenset(coordinate(c, 4) for c in "ABC"),
            "Destroyer": frozenset(coordinate(c, 5) for c in "AB"),
        }
    )


def _export(frame: object, *, width: int = 80, height: int = 24) -> str:
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


def test_combat_frame_status_shows_indicators_and_keeps_controls() -> None:
    boards = CombatBoards(
        placement=_placement(),
        own_marks={coordinate("A", 2): "sunk"},
        tracking={coordinate("F", 6): "hit"},
        revealed=frozenset(),
    )
    text = _export(
        combat_frame(
            role="Host",
            match_time="1:23",
            boards=boards,
            aim=coordinate("C", 5),
            status="Your turn — Aim and fire.",
            status_info=_status(turn="You"),
        )
    )
    # Turn / connection / state indicators.
    assert "Turn: You" in text
    assert "in sync" in text
    assert "State" in text
    assert "You" in text and "Opponent" in text
    # Compact scoreboard + controls visible at typical terminal size.
    assert "Ships" in text
    assert "fire" in text.lower()
    assert "ctrl+c" in text.lower()
    assert "→ quit" in text
    assert "lock" not in text.lower()


def test_combat_wait_frame_status_marks_opponent_turn() -> None:
    text = _export(
        combat_wait_frame(
            role="Guest",
            match_time="2:05",
            boards=CombatBoards(
                placement=_placement(),
                own_marks={},
                tracking={},
                revealed=frozenset(),
            ),
            spinner_frame=1,
            status="Waiting for opponent…",
            status_info=_status(turn="Opponent"),
        )
    )
    assert "Turn: Opponent" in text
    assert "Waiting" in text
    assert "Ships" in text
    assert "ctrl+c" in text.lower()
    assert "→ quit" in text
    assert "fire" not in text.lower()
    assert "lock" not in text.lower()


def test_disconnected_opponent_shows_open_dot() -> None:
    text = _export(
        lobby_frame(
            role="Host",
            invite="alpha-bravo-charlie-delta",
            status_info=_status(state="Lobby", turn="—", opp=False),
        )
    )
    assert "Link:" in text
    assert "○" in text  # opponent not connected yet
    assert "●" in text  # host connected


def test_wait_frame_status_shows_connection_line() -> None:
    text = _export(
        wait_frame(
            role="Guest",
            phase="Waiting for opponent Placement",
            match_time="0:30",
            status_info=_status(state="Placement", turn="—"),
        )
    )
    assert "Link:" in text
    assert "Match time 0:30" in text
