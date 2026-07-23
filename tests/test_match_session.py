"""Match session: elapsed time, Ctrl+C arm, lobby/wait frames (Clock/KeySource)."""

from __future__ import annotations

import asyncio

import pytest
from rich.console import Console

from battle_sh.ui.clock import FakeClock, format_elapsed
from battle_sh.ui.keys import ScriptedKeySource
from battle_sh.ui.placement_flow import QuitRequested
from battle_sh.ui.quit_arm import QuitArm
from battle_sh.ui.shell import lobby_frame, wait_frame
from battle_sh.ui.wait_flow import wait_honoring_quit


def test_format_elapsed_m_ss() -> None:
    assert format_elapsed(0) == "0:00"
    assert format_elapsed(5) == "0:05"
    assert format_elapsed(65) == "1:05"
    assert format_elapsed(3599) == "59:59"


def test_format_elapsed_includes_hours_when_needed() -> None:
    assert format_elapsed(3600) == "1:00:00"
    assert format_elapsed(3661) == "1:01:01"


def test_quit_arm_first_interrupt_warns_second_confirms_within_window() -> None:
    clock = FakeClock(start=10.0)
    arm = QuitArm(clock, window=3.0)

    assert arm.handle_interrupt() == "warn"
    assert arm.is_armed

    clock.advance(2.0)
    assert arm.handle_interrupt() == "confirm"


def test_quit_arm_expires_after_window() -> None:
    clock = FakeClock(start=0.0)
    arm = QuitArm(clock, window=3.0)

    assert arm.handle_interrupt() == "warn"
    clock.advance(3.0)
    arm.expire_if_due()
    assert not arm.is_armed

    # Next interrupt re-arms rather than confirming.
    assert arm.handle_interrupt() == "warn"


def _export(frame: object) -> str:
    console = Console(record=True, width=100, height=24, force_terminal=True)
    console.print(frame)  # type: ignore[arg-type]
    return console.export_text()


def test_lobby_frame_shows_waiting_for_guest_without_match_time() -> None:
    text = _export(
        lobby_frame(
            role="Host",
            invite="ABC123",
            status="Waiting for Guest…",
        )
    )
    assert "Host" in text
    assert "Waiting for Guest" in text
    assert "ABC123" in text
    assert "0:00" not in text
    assert "Match time" not in text.lower()


def test_wait_frame_shows_spinner_match_time_and_wait_keys_only() -> None:
    text = _export(
        wait_frame(
            role="Guest",
            phase="Waiting for opponent Placement",
            match_time="1:05",
            spinner_frame=0,
            status="Waiting…",
        )
    )
    assert "Guest" in text
    assert "1:05" in text
    assert "Waiting for opponent Placement" in text
    assert "q" in text.lower()
    assert "ctrl+c" in text.lower() or "ctrl-c" in text.lower()
    # Aim / Placement edit keys must not appear as active controls.
    assert "lock" not in text.lower()
    assert "fire" not in text.lower()


async def test_wait_honoring_quit_completes_when_awaitable_finishes() -> None:
    clock = FakeClock()
    keys = ScriptedKeySource([])  # no keys — wait should still finish
    messages: list[str] = []

    async def done_soon() -> str:
        await asyncio.sleep(0.01)
        return "ok"

    result = await wait_honoring_quit(
        done_soon(),
        keys=keys,
        clock=clock,
        on_message=messages.append,
    )
    assert result == "ok"


async def test_wait_honoring_quit_q_raises_quit_requested() -> None:
    clock = FakeClock()
    keys = ScriptedKeySource(["q"])

    async def never() -> None:
        await asyncio.sleep(60)

    with pytest.raises(QuitRequested):
        await wait_honoring_quit(never(), keys=keys, clock=clock)


def test_scripted_try_read_leaves_placement_keys_for_read() -> None:
    from battle_sh.ui.keys import Key

    keys = ScriptedKeySource(["y", "q"])
    assert keys.try_read() is None
    assert keys.read() == Key("y")
    assert keys.try_read() == Key("q")


async def test_wait_honoring_ctrl_c_arm_then_confirm() -> None:
    clock = FakeClock(start=0.0)
    keys = ScriptedKeySource(["ctrl+c", "ctrl+c"])
    messages: list[str] = []

    async def never() -> None:
        await asyncio.sleep(60)

    # Advance clock between polls via on_tick so arm stays valid.
    ticks = {"n": 0}

    def on_tick() -> None:
        ticks["n"] += 1
        if ticks["n"] == 2:
            clock.advance(1.0)

    with pytest.raises(QuitRequested):
        await wait_honoring_quit(
            never(),
            keys=keys,
            clock=clock,
            on_message=messages.append,
            on_tick=on_tick,
        )
    assert any("ctrl+c" in m.lower() or "again" in m.lower() for m in messages)


async def test_placement_top_info_includes_match_time_from_clock() -> None:
    from battle_sh.ui.placement_flow import run_placement
    from battle_sh.ui.shell import placement_frame
    from battle_sh.rules.placement import Placement, coordinate

    clock = FakeClock(start=100.0)
    match_started_at = 100.0

    def top_info() -> str:
        return f"Host · Placement · Match time {format_elapsed(clock.now() - match_started_at)}"

    clock.advance(65)
    text = _export(
        placement_frame(
            placement=Placement(
                {
                    "Carrier": frozenset(coordinate(c, 1) for c in "ABCDE"),
                    "Battleship": frozenset(coordinate(c, 2) for c in "ABCD"),
                    "Cruiser": frozenset(coordinate(c, 3) for c in "ABC"),
                    "Submarine": frozenset(coordinate(c, 4) for c in "ABC"),
                    "Destroyer": frozenset(coordinate(c, 5) for c in "AB"),
                }
            ),
            selected=None,
            top_info=top_info(),
        )
    )
    assert "Match time 1:05" in text

    keys = ScriptedKeySource(["y"])
    run_placement(keys, top_info=top_info, clock=clock)
