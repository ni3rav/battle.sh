"""Three-band Placement frame: top | board+controls | bottom (not Live internals)."""

from __future__ import annotations

from battle_sh.rules.placement import Placement, coordinate
from battle_sh.ui.keys import ScriptedKeySource
from battle_sh.ui.placement_flow import run_placement
from battle_sh.ui.shell import placement_frame
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


def _export(frame: object) -> str:
    console = Console(record=True, width=100, height=28, force_terminal=True)
    console.print(frame)  # type: ignore[arg-type]
    return console.export_text()


def test_placement_frame_has_three_bands_with_board_and_controls() -> None:
    text = _export(
        placement_frame(
            placement=_fixed_placement(),
            selected="Destroyer",
            status="Can't move there.",
            top_info="Phase: Placement",
        )
    )
    assert "Phase: Placement" in text
    assert "Your fleet" in text
    assert "D" in text  # Destroyer glyph on board
    assert "Can't move there." in text
    # Placement-phase keys only (not fire / aim)
    assert "y" in text.lower() and "lock" in text.lower()
    assert "t" in text.lower() and "random" in text.lower()
    assert "w/a/s/d" in text.lower() or "wasd" in text.lower()
    assert "fire" not in text.lower()
    assert "shoot" not in text.lower()


def test_run_placement_with_console_keeps_keysource_behavior() -> None:
    """Live shell must not break scripted KeySource lock / status messages."""
    messages: list[str] = []
    console = Console(record=True, width=100, height=28, force_terminal=True)
    keys = ScriptedKeySource(["1", "w", "y"])
    before = _fixed_placement()
    placement = run_placement(
        keys,
        console=console,
        on_message=messages.append,
        placement_factory=_fixed_placement,
    )
    assert placement == before
    assert any(m == "Can't move there." for m in messages)
