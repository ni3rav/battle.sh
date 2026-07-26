"""Combat helpers: scoreboard status, shot marks, and feedback copy."""

from __future__ import annotations

from battle_sh.networking.connection import MatchConnection, ShotReport
from battle_sh.rules.board import ShotResultKind, parse_coordinate
from battle_sh.rules.placement import (
    STANDARD_FLEET_LENGTHS,
    Coordinate,
    Placement,
)
from battle_sh.ui.chrome import MatchStatus

FLEET_SIZE = len(STANDARD_FLEET_LENGTHS)
TOTAL_CELLS = sum(STANDARD_FLEET_LENGTHS.values())


def your_fleet_status(
    placement: Placement, own_marks: dict[Coordinate, ShotResultKind]
) -> tuple[int, tuple[tuple[str, bool], ...]]:
    """Per-ship afloat/sunk state for our own fleet from incoming hit marks."""
    afloat = 0
    fleet: list[tuple[str, bool]] = []
    for name in STANDARD_FLEET_LENGTHS:
        cells = placement.ships[name]
        hits = sum(1 for c in cells if own_marks.get(c) in ("hit", "sunk"))
        is_afloat = hits < len(cells)
        afloat += 1 if is_afloat else 0
        fleet.append((name, is_afloat))
    return afloat, tuple(fleet)


def count_hits(marks: dict[Coordinate, ShotResultKind]) -> int:
    return sum(1 for kind in marks.values() if kind in ("hit", "sunk"))


def combat_match_status(
    *,
    conn: MatchConnection,
    role: str,
    placement: Placement,
    own_marks: dict[Coordinate, ShotResultKind],
    tracking: dict[Coordinate, ShotResultKind],
    enemy_sunk_ships: list[str] | tuple[str, ...],
) -> MatchStatus:
    """Combat scoreboard/status for the Textual Combat screen."""
    your_afloat, your_fleet = your_fleet_status(placement, own_marks)
    over = conn.match_end is not None
    connected = conn.is_connected
    return MatchStatus(
        role=role,
        state="Match over" if over else "Combat",
        turn="You" if conn.my_turn else "Opponent",
        your_ships_afloat=your_afloat,
        your_ships_total=FLEET_SIZE,
        enemy_ships_afloat=FLEET_SIZE - len(enemy_sunk_ships),
        enemy_ships_total=FLEET_SIZE,
        your_hits=count_hits(tracking),
        enemy_hits=count_hits(own_marks),
        total_cells=TOTAL_CELLS,
        you_connected=connected,
        opponent_connected=connected and not over and conn.opponent_connected,
        synchronized=conn.ready_to_fire,
        your_fleet=your_fleet,
        enemy_sunk=tuple(enemy_sunk_ships),
    )


def apply_outgoing_shot(
    report: ShotReport,
    tracking: dict[Coordinate, ShotResultKind],
    revealed: set[Coordinate],
) -> None:
    coord = parse_coordinate(report.coordinate)
    kind: ShotResultKind = report.result  # type: ignore[assignment]
    tracking[coord] = kind
    for cell in report.revealed_cells:
        c = parse_coordinate(cell)
        revealed.add(c)
        tracking[c] = "sunk"


def apply_incoming_shot(
    report: ShotReport, own_marks: dict[Coordinate, ShotResultKind]
) -> None:
    coord = parse_coordinate(report.coordinate)
    kind: ShotResultKind = report.result  # type: ignore[assignment]
    own_marks[coord] = kind
    if report.result == "sunk":
        for cell in report.revealed_cells:
            own_marks[parse_coordinate(cell)] = "sunk"


def format_shot_feedback(report: ShotReport, *, outgoing: bool) -> str:
    cell = report.coordinate
    if outgoing:
        if report.result == "miss":
            return f"You shot {cell} — miss."
        if report.result == "hit":
            ship = f" ({report.ship})" if report.ship else ""
            return f"You shot {cell} — hit{ship}!"
        ship = report.ship or "ship"
        return f"You shot {cell} — sunk their {ship}!"
    if report.result == "miss":
        return f"Opponent shot {cell} — miss."
    if report.result == "hit":
        ship = f" ({report.ship})" if report.ship else ""
        return f"Opponent shot {cell} — hit{ship}!"
    ship = report.ship or "ship"
    return f"Opponent shot {cell} — they sank your {ship}!"
