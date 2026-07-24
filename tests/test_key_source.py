"""KeySource seam: scripted immediate keys without a real TTY."""

from __future__ import annotations

import select
import sys
import types
from collections import deque

import pytest

from battle_sh.ui.clock import FakeClock
from battle_sh.ui.keys import INTERRUPT, Key, ScriptedKeySource, TerminalKeySource
from battle_sh.ui.play import ScriptedIO


def test_terminal_try_read_survives_windows_stdin_select(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """WinError 10038: select cannot poll stdin on Windows; try_read must not raise."""
    def boom(*_a: object, **_k: object) -> list[object]:
        # WinError 10038 as raised by select(stdin) on Windows.
        raise OSError(
            10038, "An operation was attempted on something that is not a socket"
        )

    monkeypatch.setattr(select, "select", boom)
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setitem(sys.modules, "msvcrt", types.SimpleNamespace(kbhit=lambda: 0))

    assert TerminalKeySource().try_read(0.0) is None


def test_scripted_key_source_yields_immediate_keys_in_order() -> None:
    keys = ScriptedKeySource([Key("w"), Key("a"), Key("enter")])

    assert keys.read() == Key("w")
    assert keys.read() == Key("a")
    assert keys.read() == Key("enter")


def test_scripted_key_source_can_represent_interrupt() -> None:
    keys = ScriptedKeySource([INTERRUPT])

    key = keys.read()
    assert key == INTERRUPT
    assert key.is_interrupt


def test_scripted_key_source_accepts_string_shorthand() -> None:
    keys = ScriptedKeySource(["1", "tab", "ctrl+c"])

    assert keys.read() == Key("1")
    assert keys.read() == Key("tab")
    assert keys.read().is_interrupt


def test_scripted_key_source_raises_when_exhausted() -> None:
    keys = ScriptedKeySource(["q"])
    keys.read()

    with pytest.raises(EOFError, match="No scripted key left"):
        keys.read()


def test_terminal_read_maps_keyboard_interrupt_to_interrupt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import readchar

    def boom() -> str:
        raise KeyboardInterrupt

    monkeypatch.setattr(readchar, "readkey", boom)
    assert TerminalKeySource().read() == INTERRUPT


def test_scripted_io_injects_key_source_and_clock_without_tty() -> None:
    """Host/Guest IO accepts KeySource + Clock beside line ask (no real terminal)."""
    keys = ScriptedKeySource(["w", "ctrl+c"])
    clock = FakeClock(start=5.0)
    io = ScriptedIO(inputs=deque(["unused"]), keys=keys, clock=clock)

    assert io.keys.read() == Key("w")
    assert io.clock.now() == 5.0
    clock.advance(3.0)
    assert io.clock.now() == 8.0
    assert io.keys.read().is_interrupt
    # Line ask path remains available for existing Host/Guest play.
    assert io.ask("prompt> ") == "unused"
