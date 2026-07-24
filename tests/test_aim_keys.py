"""Aim via injectable KeySource (immediate keys, no Coordinate typing)."""

from __future__ import annotations

import pytest

from battle_sh.rules.placement import coordinate
from battle_sh.ui.aim_flow import run_aim
from battle_sh.ui.keys import ScriptedKeySource
from battle_sh.ui.placement_flow import QuitRequested


def test_f_fires_at_a1_when_no_prior_shot() -> None:
    keys = ScriptedKeySource(["f"])
    assert run_aim(keys, fired=frozenset()) == coordinate("A", 1)


def test_enter_and_space_also_fire() -> None:
    assert run_aim(ScriptedKeySource(["enter"]), fired=frozenset()) == coordinate(
        "A", 1
    )
    assert run_aim(ScriptedKeySource(["space"]), fired=frozenset()) == coordinate(
        "A", 1
    )


def test_wasd_and_arrows_move_aim() -> None:
    cursors: list[str] = []
    keys = ScriptedKeySource(["d", "d", "s", "f"])
    result = run_aim(
        keys,
        fired=frozenset(),
        on_cursor=lambda c: cursors.append(str(c)),
    )
    assert result == coordinate("C", 2)
    assert cursors[-1] == "C2"


def test_aim_skips_already_fired_cells() -> None:
    fired = frozenset({coordinate("B", 1), coordinate("C", 1)})
    cursors: list[str] = []
    keys = ScriptedKeySource(["d", "f"])
    result = run_aim(
        keys,
        fired=fired,
        on_cursor=lambda c: cursors.append(str(c)),
    )
    # From A1, right skips B1 and C1 → lands on D1
    assert result == coordinate("D", 1)
    assert "B1" not in cursors and "C1" not in cursors


def test_aim_resumes_from_last_shot() -> None:
    """Later turns start near the last Shot (that cell is already spent)."""
    last = coordinate("C", 5)
    keys = ScriptedKeySource(["f"])
    assert run_aim(
        keys,
        fired=frozenset({last}),
        start=last,
    ) == coordinate("D", 5)


def test_q_raises_quit_requested() -> None:
    with pytest.raises(QuitRequested):
        run_aim(ScriptedKeySource(["q"]), fired=frozenset())


def test_q_with_clock_requires_confirm() -> None:
    from battle_sh.ui.clock import FakeClock

    clock = FakeClock()
    with pytest.raises(QuitRequested):
        run_aim(ScriptedKeySource(["q", "q"]), fired=frozenset(), clock=clock)
