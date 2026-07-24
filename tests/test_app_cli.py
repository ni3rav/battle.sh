"""Unified `battle-sh` CLI: host / join / relay dispatch and defaults."""

from __future__ import annotations

import argparse
from typing import Any

import pytest

from battle_sh import app


def test_parser_exposes_exactly_host_join_relay() -> None:
    parser = app.build_parser()
    for command in ("host", "join", "relay"):
        args = parser.parse_args([command])
        assert args.command == command


def test_missing_command_errors() -> None:
    with pytest.raises(SystemExit):
        app.build_parser().parse_args([])


def test_relay_defaults() -> None:
    args = app.build_parser().parse_args(["relay"])
    assert args.bind_host == "127.0.0.1"
    assert args.port == 8765
    assert args.grace_seconds == 10.0


def test_host_relay_url_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BATTLE_SH_RELAY", "wss://relay.example.com")
    args = app.build_parser().parse_args(["host"])
    assert args.relay == "wss://relay.example.com"


def test_main_dispatches_to_each_handler(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def record(name: str) -> object:
        def handler(_: argparse.Namespace) -> None:
            calls.append(name)

        return handler

    monkeypatch.setattr(app, "_run_host", record("host"))
    monkeypatch.setattr(app, "_run_join", record("join"))
    monkeypatch.setattr(app, "_run_relay", record("relay"))

    app.main(["host"])
    app.main(["join", "--invite", "alpha-bravo-charlie-delta"])
    app.main(["relay"])

    assert calls == ["host", "join", "relay"]


def test_run_relay_invokes_run_relay(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_run_relay(bind_host: str, port: int, *, grace_seconds: float) -> None:
        captured["bind_host"] = bind_host
        captured["port"] = port
        captured["grace_seconds"] = grace_seconds

    def fake_configure(**_: object) -> None:
        return None

    def fake_asyncio_run(result: Any) -> None:
        return None

    monkeypatch.setattr(app, "run_relay", fake_run_relay)
    monkeypatch.setattr(app, "configure_logging", fake_configure)
    monkeypatch.setattr(app.asyncio, "run", fake_asyncio_run)

    args = argparse.Namespace(bind_host="0.0.0.0", port=9001, grace_seconds=5.0)
    app._run_relay(args)  # pyright: ignore[reportPrivateUsage]

    assert captured == {"bind_host": "0.0.0.0", "port": 9001, "grace_seconds": 5.0}


def test_main_keyboard_interrupt_exits_quietly(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def boom(_: argparse.Namespace) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(app, "_run_host", boom)
    app.main(["host"])
    captured = capsys.readouterr()
    assert "Traceback" not in captured.err
    assert "Traceback" not in captured.out
    assert "Interrupted" in captured.out


def test_run_relay_keyboard_interrupt_stops_quietly(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def boom(*_a: object, **_k: object) -> object:
        raise KeyboardInterrupt

    def fake_configure(**_: object) -> None:
        return None

    monkeypatch.setattr(app, "run_relay", boom)
    monkeypatch.setattr(app, "configure_logging", fake_configure)

    args = argparse.Namespace(bind_host="127.0.0.1", port=8765, grace_seconds=30.0)
    app._run_relay(args)  # pyright: ignore[reportPrivateUsage]
    out = capsys.readouterr().out
    assert "Relay stopped" in out
    assert "Traceback" not in out
