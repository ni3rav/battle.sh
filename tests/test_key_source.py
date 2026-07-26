"""Scripted key driver: immediate keys without a real TTY."""

from __future__ import annotations

import pytest

from battle_sh.ui.keys import INTERRUPT, Key
from key_drivers import ScriptedKeySource


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


def test_scripted_try_read_surfaces_interrupt_by_default() -> None:
    keys = ScriptedKeySource(["y", "ctrl+c"])
    assert keys.try_read() is None
    assert keys.read() == Key("y")
    assert keys.try_read() == Key("ctrl+c")


def test_scripted_try_read_poll_all_surfaces_every_key() -> None:
    keys = ScriptedKeySource(["w", "f"], poll_all=True)
    assert keys.try_read() == Key("w")
    assert keys.try_read() == Key("f")
