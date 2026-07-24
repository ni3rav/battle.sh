"""Structured logging and connection-diagnostics coverage."""

from __future__ import annotations

import io
import json
import logging
from collections.abc import Iterator

import pytest
import structlog

from battle_sh.networking.connection import (
    MatchConnection,
    close_code_and_reason,
)
from battle_sh.networking.relay import start_relay
from battle_sh.observability import (
    configure_logging,
    get_logger,
    new_conn_id,
    shutdown_logging,
)
from battle_sh.rules.placement import Placement, coordinate
from battle_sh.ui.play import _connection_lost_message  # pyright: ignore[reportPrivateUsage]
from websockets.exceptions import ConnectionClosed
from websockets.frames import Close


@pytest.fixture
def log_buffer() -> Iterator[io.StringIO]:
    """Configure structured logging to an in-memory buffer, then reset globals."""
    buffer = io.StringIO()
    configure_logging(
        component="test", level="DEBUG", fmt="json", stream=buffer
    )
    try:
        yield buffer
    finally:
        shutdown_logging()
        root = logging.getLogger()
        for handler in list(root.handlers):
            root.removeHandler(handler)
        root.setLevel(logging.WARNING)
        structlog.reset_defaults()
        structlog.contextvars.clear_contextvars()


def _records(buffer: io.StringIO) -> list[dict[str, object]]:
    shutdown_logging()  # flush the queue listener before reading
    return [json.loads(line) for line in buffer.getvalue().splitlines() if line]


def test_new_conn_id_is_short_and_unique() -> None:
    ids = {new_conn_id() for _ in range(100)}
    assert len(ids) == 100
    assert all(len(i) == 12 for i in ids)


def test_structured_log_includes_timestamp_level_and_context(
    log_buffer: io.StringIO,
) -> None:
    structlog.contextvars.bind_contextvars(session_id="alpha-bravo")
    get_logger(component="relay").info(
        "client_connected", conn_id="abc123", player_id="host:abc123"
    )
    records = _records(log_buffer)
    assert len(records) == 1
    record = records[0]
    assert record["event"] == "client_connected"
    assert record["level"] == "info"
    assert record["component"] == "relay"
    assert record["conn_id"] == "abc123"
    assert record["player_id"] == "host:abc123"
    assert record["session_id"] == "alpha-bravo"
    assert "timestamp" in record


def _placement_a() -> Placement:
    return Placement(
        {
            "Carrier": frozenset(coordinate(c, 10) for c in "ABCDE"),
            "Battleship": frozenset(coordinate(c, 9) for c in "ABCD"),
            "Cruiser": frozenset(coordinate(c, 8) for c in "ABC"),
            "Submarine": frozenset(coordinate(c, 7) for c in "ABC"),
            "Destroyer": frozenset(coordinate("A", r) for r in (1, 2)),
        }
    )


def _placement_b() -> Placement:
    return Placement(
        {
            "Carrier": frozenset(coordinate(c, 1) for c in "ABCDE"),
            "Battleship": frozenset(coordinate(c, 2) for c in "ABCD"),
            "Cruiser": frozenset(coordinate(c, 3) for c in "ABC"),
            "Submarine": frozenset(coordinate(c, 4) for c in "ABC"),
            "Destroyer": frozenset(coordinate("J", r) for r in (10, 9)),
        }
    )


async def test_relay_logs_match_lifecycle_events(log_buffer: io.StringIO) -> None:
    async with start_relay() as relay_url:
        host = await MatchConnection.connect(relay_url)
        guest = await MatchConnection.connect(relay_url)
        try:
            invite = await host.create_match()
            await guest.join_match(invite)
            await host.wait_for_player_joined()
            await host.lock_placement(_placement_a())
            await guest.lock_placement(_placement_b())
            await host.wait_for_opponent_commitment()
            await guest.wait_for_opponent_commitment()
        finally:
            await guest.close()
            await host.close()

    events = {r["event"] for r in _records(log_buffer)}
    for expected in (
        "client_connected",
        "match_created",
        "match_joined",
        "match_started",
        "message_forwarded",
    ):
        assert expected in events, f"missing relay event {expected!r}: {events}"


def test_close_code_and_reason_reads_received_frame() -> None:
    exc = ConnectionClosed(
        Close(1011, "keepalive ping timeout"),
        Close(1011, "keepalive ping timeout"),
        True,
    )
    code, reason = close_code_and_reason(exc)
    assert code == 1011
    assert reason == "keepalive ping timeout"


def test_close_code_and_reason_handles_missing_frames() -> None:
    exc = ConnectionClosed(None, None)
    code, reason = close_code_and_reason(exc)
    assert code is None
    assert reason == ""


def test_connection_lost_message_names_keepalive_timeout() -> None:
    exc = ConnectionClosed(
        Close(1011, "keepalive ping timeout"),
        Close(1011, "keepalive ping timeout"),
        True,
    )
    message = _connection_lost_message(exc)
    assert "keepalive timeout" in message.lower()
    assert "Abandoned" in message
