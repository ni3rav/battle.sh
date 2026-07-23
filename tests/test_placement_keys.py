"""Placement via injectable KeySource (immediate keys, no line commands)."""

from __future__ import annotations

import pytest

from battle_sh.rules.placement import Placement, coordinate, validate_placement
from battle_sh.ui.keys import ScriptedKeySource
from battle_sh.ui.placement_flow import QuitRequested, run_placement


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


def test_y_locks_and_returns_legal_placement() -> None:
    keys = ScriptedKeySource(["y"])
    placement = run_placement(keys, placement_factory=_fixed_placement)
    validate_placement(placement)
    assert placement == _fixed_placement()


def test_q_raises_quit_requested() -> None:
    keys = ScriptedKeySource(["q"])
    with pytest.raises(QuitRequested):
        run_placement(keys, placement_factory=_fixed_placement)


def test_select_and_move_with_wasd() -> None:
    messages: list[str] = []
    keys = ScriptedKeySource(["5", "d", "d", "y"])
    placement = run_placement(
        keys,
        placement_factory=_fixed_placement,
        on_message=messages.append,
    )
    assert placement.ships["Destroyer"] == frozenset(coordinate(c, 5) for c in "CD")
    assert any("Selected Destroyer" in m for m in messages)


def test_rotate_with_e_and_r() -> None:
    keys = ScriptedKeySource(["5", "e", "y"])
    placement = run_placement(keys, placement_factory=_fixed_placement)
    assert placement.ships["Destroyer"] == frozenset(coordinate("A", r) for r in (5, 6))

    keys = ScriptedKeySource(["5", "r", "y"])
    placement = run_placement(keys, placement_factory=_fixed_placement)
    assert placement.ships["Destroyer"] == frozenset(coordinate("A", r) for r in (5, 6))


def test_tab_and_shift_tab_cycle_ship_selection() -> None:
    messages: list[str] = []
    keys = ScriptedKeySource(["tab", "tab", "shift+tab", "y"])
    run_placement(
        keys,
        placement_factory=_fixed_placement,
        on_message=messages.append,
    )
    selected = [m for m in messages if m.startswith("Selected ")]
    assert selected == [
        "Selected Carrier.",
        "Selected Battleship.",
        "Selected Carrier.",
    ]


def test_t_rerolls_placement() -> None:
    calls = {"n": 0}

    def factory() -> Placement:
        calls["n"] += 1
        if calls["n"] == 1:
            return _fixed_placement()
        return Placement(
            {
                **{n: c for n, c in _fixed_placement().ships.items()},
                "Destroyer": frozenset(coordinate(c, 5) for c in "CD"),
            }
        )

    keys = ScriptedKeySource(["t", "y"])
    placement = run_placement(keys, placement_factory=factory)
    assert calls["n"] == 2
    assert placement.ships["Destroyer"] == frozenset(coordinate(c, 5) for c in "CD")


def test_illegal_move_keeps_layout_and_surfaces_message() -> None:
    messages: list[str] = []
    before = _fixed_placement()
    keys = ScriptedKeySource(["1", "w", "y"])
    placement = run_placement(
        keys,
        placement_factory=_fixed_placement,
        on_message=messages.append,
    )
    assert placement == before
    assert any(m == "Can't move there." for m in messages)


def test_illegal_rotate_keeps_layout_and_surfaces_message() -> None:
    messages: list[str] = []
    before = _fixed_placement()
    keys = ScriptedKeySource(["1", "e", "y"])
    placement = run_placement(
        keys,
        placement_factory=_fixed_placement,
        on_message=messages.append,
    )
    assert placement == before
    assert any(m == "Can't rotate there." for m in messages)


def test_arrows_move_selected_ship() -> None:
    keys = ScriptedKeySource(["5", "right", "down", "y"])
    placement = run_placement(keys, placement_factory=_fixed_placement)
    assert placement.ships["Destroyer"] == frozenset(coordinate(c, 6) for c in "BC")
