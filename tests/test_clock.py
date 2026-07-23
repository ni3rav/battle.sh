"""Clock seam: injectable time for Match elapsed and Ctrl+C arming."""

from __future__ import annotations

from battle_sh.ui.clock import FakeClock, SystemClock


def test_fake_clock_supplies_now_and_advances() -> None:
    clock = FakeClock(start=10.0)

    assert clock.now() == 10.0
    clock.advance(3.0)
    assert clock.now() == 13.0


def test_fake_clock_supports_ctrl_c_arm_window() -> None:
    """Callers can arm on first interrupt and expire after ~3s via Clock.now()."""
    clock = FakeClock(start=0.0)
    arm_until: float | None = None
    arm_window = 3.0

    # First Ctrl+C arms.
    arm_until = clock.now() + arm_window
    assert arm_until == 3.0

    clock.advance(2.9)
    assert clock.now() < arm_until

    clock.advance(0.2)
    assert clock.now() >= arm_until
    # Arm expired — next Ctrl+C would re-arm, not confirm.
    arm_until = None
    assert arm_until is None


def test_system_clock_returns_monotonic_now() -> None:
    clock = SystemClock()
    first = clock.now()
    second = clock.now()

    assert second >= first
