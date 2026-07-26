"""Match session helpers: elapsed time and QuitArm (Clock seam)."""

from __future__ import annotations

from battle_sh.ui.clock import FakeClock, format_elapsed
from battle_sh.ui.quit_arm import QuitArm


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
