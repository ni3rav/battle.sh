"""Local WebSocket Relay: Match membership and message forwarding only."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from typing import Any

import structlog
from websockets.asyncio.server import ServerConnection, serve
from websockets.exceptions import ConnectionClosed

from battle_sh.networking.invite import mint_invite, normalize_invite
from battle_sh.networking.protocol import (
    DEFAULT_GRACE_SECONDS,
    KEEPALIVE_PING_INTERVAL,
    KEEPALIVE_PING_TIMEOUT,
    ErrorCode,
    MatchOutcome,
    MsgType,
    Role,
    decode,
    encode,
    error_message,
)
from battle_sh.observability import get_logger, new_conn_id


def _log() -> "structlog.stdlib.BoundLogger":
    """Relay logger resolved at call time so configure_logging always applies."""
    return get_logger(component="relay")

# How often the Relay records a per-connection health sample (latency + state).
HEALTH_SAMPLE_INTERVAL = 30.0


@dataclass
class _Match:
    invite: str
    host: ServerConnection | None
    guest: ServerConnection | None = None
    host_grace: asyncio.Task[None] | None = None
    guest_grace: asyncio.Task[None] | None = None
    ended: bool = False


@dataclass
class _RelayState:
    matches: dict[str, _Match] = field(default_factory=dict[str, _Match])
    seats: dict[ServerConnection, tuple[str, Role]] = field(
        default_factory=dict[ServerConnection, tuple[str, Role]]
    )
    grace_seconds: float = DEFAULT_GRACE_SECONDS


def _mint_invite() -> str:
    return mint_invite()


def _remote(ws: ServerConnection) -> str:
    address: Any = ws.remote_address
    try:
        host: Any = address[0]
        port: Any = address[1]
    except (TypeError, KeyError, IndexError):
        return str(address)
    return f"{host}:{port}"


async def _send(ws: ServerConnection, message: dict[str, Any]) -> None:
    await ws.send(encode(message))


async def _forward(
    ws: ServerConnection, other: ServerConnection, raw: str
) -> None:
    try:
        await other.send(raw)
    except ConnectionClosed:
        await _send(
            ws,
            error_message(ErrorCode.PLAYER_GONE, "Other Player is no longer connected"),
        )


async def _monitor_connection_health(
    ws: ServerConnection, state: _RelayState, conn_id: str
) -> None:
    """Periodically record keepalive latency and connection state until close."""
    if HEALTH_SAMPLE_INTERVAL <= 0:
        return
    try:
        while ws.state.name == "OPEN":
            await asyncio.sleep(HEALTH_SAMPLE_INTERVAL)
            seat = state.seats.get(ws)
            session_id = seat[0] if seat is not None else None
            role = seat[1] if seat is not None else None
            _log().debug(
                "connection_health",
                conn_id=conn_id,
                session_id=session_id,
                player_id=f"{role}:{conn_id}" if role else None,
                latency_ms=round(ws.latency * 1000, 2),
                state=ws.state.name,
            )
    except asyncio.CancelledError:
        return


async def _abandon_match(
    state: _RelayState, invite: str, *, reason: str | None = None
) -> None:
    match = state.matches.pop(invite, None)
    if match is None or match.ended:
        return
    match.ended = True
    _log().info("match_abandoned", session_id=invite, reason=reason)
    current = asyncio.current_task()
    for task in (match.host_grace, match.guest_grace):
        if task is None or task is current or task.done():
            continue
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
    match.host_grace = None
    match.guest_grace = None
    payload: dict[str, Any] = {
        "type": MsgType.MATCH_END,
        "outcome": MatchOutcome.ABANDONED,
    }
    if reason is not None:
        payload["reason"] = reason
    for ws in (match.host, match.guest):
        if ws is None:
            continue
        state.seats.pop(ws, None)
        with contextlib.suppress(ConnectionClosed):
            await _send(ws, payload)


async def _notify_other(
    match: _Match, role: Role, message: dict[str, Any]
) -> None:
    other = match.guest if role == "host" else match.host
    if other is None:
        return
    with contextlib.suppress(ConnectionClosed):
        await _send(other, message)


async def _start_grace(state: _RelayState, invite: str, role: Role) -> None:
    async def _expire() -> None:
        try:
            await asyncio.sleep(state.grace_seconds)
        except asyncio.CancelledError:
            return
        _log().info(
            "reconnect_grace_expired", session_id=invite, role=role
        )
        await _abandon_match(state, invite)

    match = state.matches.get(invite)
    if match is None:
        return
    _log().info(
        "reconnect_grace_started",
        session_id=invite,
        role=role,
        grace_seconds=state.grace_seconds,
    )
    task = asyncio.create_task(_expire())
    if role == "host":
        if match.host_grace is not None and not match.host_grace.done():
            match.host_grace.cancel()
        match.host_grace = task
    else:
        if match.guest_grace is not None and not match.guest_grace.done():
            match.guest_grace.cancel()
        match.guest_grace = task


async def _handle_create(
    ws: ServerConnection, state: _RelayState, log: structlog.stdlib.BoundLogger
) -> None:
    if ws in state.seats:
        await _send(ws, error_message(ErrorCode.ALREADY_IN_MATCH, "Already in a Match"))
        log.warning("create_rejected", reason="already_in_match")
        return
    invite = _mint_invite()
    while invite in state.matches:
        invite = _mint_invite()
    state.matches[invite] = _Match(invite=invite, host=ws)
    state.seats[ws] = (invite, "host")
    await _send(ws, {"type": MsgType.MATCH_CREATED, "invite": invite, "role": "host"})
    log.info("match_created", session_id=invite, role="host")


async def _handle_join(
    ws: ServerConnection, state: _RelayState, invite: object, log: structlog.stdlib.BoundLogger
) -> None:
    if ws in state.seats:
        await _send(ws, error_message(ErrorCode.ALREADY_IN_MATCH, "Already in a Match"))
        log.warning("join_rejected", reason="already_in_match")
        return
    if not isinstance(invite, str) or not invite.strip():
        await _send(
            ws,
            error_message(ErrorCode.MALFORMED_INVITE, "Invite must be a non-empty string"),
        )
        log.warning("join_rejected", reason="malformed_invite")
        return
    invite = normalize_invite(invite)
    match = state.matches.get(invite)
    if match is None or match.ended:
        await _send(ws, error_message(ErrorCode.UNKNOWN_INVITE, "Unknown Invite"))
        log.warning("join_rejected", reason="unknown_invite", session_id=invite)
        return
    if match.guest is not None:
        await _send(ws, error_message(ErrorCode.MATCH_FULL, "Match already has two Players"))
        log.warning("join_rejected", reason="match_full", session_id=invite)
        return
    if match.guest_grace is not None and not match.guest_grace.done():
        await _send(
            ws,
            error_message(
                ErrorCode.MATCH_FULL,
                "Guest is held for reconnect; use reconnect_match",
            ),
        )
        log.warning("join_rejected", reason="guest_held_for_reconnect", session_id=invite)
        return
    match.guest = ws
    state.seats[ws] = (invite, "guest")
    await _send(ws, {"type": MsgType.MATCH_JOINED, "invite": invite, "role": "guest"})
    log.info("match_joined", session_id=invite, role="guest")
    if match.host is not None:
        await _send(
            match.host,
            {"type": MsgType.PLAYER_JOINED, "invite": invite, "role": "guest"},
        )
        _log().info("match_started", session_id=invite)


async def _handle_reconnect(
    ws: ServerConnection, state: _RelayState, invite: object, role: object, log: structlog.stdlib.BoundLogger
) -> None:
    if ws in state.seats:
        await _send(ws, error_message(ErrorCode.ALREADY_IN_MATCH, "Already in a Match"))
        log.warning("reconnect_rejected", reason="already_in_match")
        return
    if not isinstance(invite, str) or not invite.strip():
        await _send(
            ws,
            error_message(ErrorCode.MALFORMED_INVITE, "Invite must be a non-empty string"),
        )
        log.warning("reconnect_rejected", reason="malformed_invite")
        return
    invite = normalize_invite(invite)
    if role == "host":
        claimed_role: Role = "host"
    elif role == "guest":
        claimed_role = "guest"
    else:
        await _send(
            ws,
            error_message(ErrorCode.MALFORMED_MESSAGE, "Role must be host or guest"),
        )
        log.warning("reconnect_rejected", reason="malformed_role", session_id=invite)
        return
    match = state.matches.get(invite)
    if match is None or match.ended:
        await _send(ws, error_message(ErrorCode.UNKNOWN_INVITE, "Unknown Invite"))
        log.warning("reconnect_rejected", reason="unknown_invite", session_id=invite)
        return

    if claimed_role == "host":
        grace = match.host_grace
        occupied = match.host is not None
    else:
        grace = match.guest_grace
        occupied = match.guest is not None

    if occupied:
        await _send(
            ws,
            error_message(ErrorCode.MATCH_FULL, "Seat is already occupied"),
        )
        log.warning(
            "reconnect_rejected",
            reason="seat_occupied",
            session_id=invite,
            role=claimed_role,
        )
        return
    if grace is None or grace.done():
        await _send(
            ws,
            error_message(ErrorCode.UNKNOWN_INVITE, "Reconnect grace has expired"),
        )
        log.warning(
            "reconnect_rejected",
            reason="grace_expired",
            session_id=invite,
            role=claimed_role,
        )
        return

    grace.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await grace
    if claimed_role == "host":
        match.host = ws
        match.host_grace = None
    else:
        match.guest = ws
        match.guest_grace = None
    state.seats[ws] = (invite, claimed_role)
    await _send(
        ws,
        {"type": MsgType.MATCH_RESUMED, "invite": invite, "role": claimed_role},
    )
    log.info("match_resumed", session_id=invite, role=claimed_role)
    other = match.guest if claimed_role == "host" else match.host
    if other is not None:
        await _send(other, {"type": MsgType.OPPONENT_RECONNECTED})


async def _handle_leave(
    ws: ServerConnection, state: _RelayState, log: structlog.stdlib.BoundLogger
) -> None:
    seat = state.seats.get(ws)
    if seat is None:
        await _send(ws, error_message(ErrorCode.NOT_IN_MATCH, "Not in a Match"))
        log.warning("leave_rejected", reason="not_in_match")
        return
    invite, role = seat
    match = state.matches.get(invite)
    if match is None or match.ended:
        state.seats.pop(ws, None)
        await _send(ws, error_message(ErrorCode.UNKNOWN_INVITE, "Unknown Invite"))
        log.warning("leave_rejected", reason="unknown_invite", session_id=invite)
        return
    state.seats.pop(ws, None)
    if role == "host":
        match.host = None
    else:
        match.guest = None
    log.info("match_left", session_id=invite, role=role)
    await _abandon_match(state, invite, reason="left")


async def _on_disconnect(ws: ServerConnection, state: _RelayState) -> None:
    seat = state.seats.pop(ws, None)
    if seat is None:
        return
    invite, role = seat
    match = state.matches.get(invite)
    if match is None or match.ended:
        return
    if role == "host":
        match.host = None
    else:
        match.guest = None
    await _notify_other(
        match,
        role,
        {
            "type": MsgType.OPPONENT_DISCONNECTED,
            "grace_seconds": state.grace_seconds,
        },
    )
    # Both seats empty with no grace yet: still start grace for the departing seat.
    # If the other seat is also vacant and its grace already running, either expiry abandons.
    await _start_grace(state, invite, role)


def _log_closure(ws: ServerConnection, log: structlog.stdlib.BoundLogger) -> None:
    code = ws.close_code
    reason = ws.close_reason or ""
    if code == 1011 and "keepalive" in reason.lower():
        log.warning(
            "keepalive_timeout",
            close_code=code,
            close_reason=reason,
        )
    elif code is not None and code not in (1000, 1001):
        log.warning(
            "connection_closed_unexpectedly",
            close_code=code,
            close_reason=reason,
        )
    else:
        log.info("client_disconnected", close_code=code, close_reason=reason)


async def _handle_client(ws: ServerConnection, state: _RelayState) -> None:
    conn_id = new_conn_id()
    log = _log().bind(conn_id=conn_id, remote=_remote(ws))
    log.info("client_connected")
    health = asyncio.create_task(
        _monitor_connection_health(ws, state, conn_id)
    )
    try:
        async for raw in ws:
            try:
                message = decode(raw if isinstance(raw, str) else raw.decode())
            except ValueError as exc:
                await _send(ws, error_message(ErrorCode.MALFORMED_MESSAGE, str(exc)))
                log.warning("malformed_message", error=str(exc))
                continue

            msg_type = message.get("type")
            log.debug("message_received", msg_type=str(msg_type))
            if msg_type == MsgType.CREATE_MATCH:
                await _handle_create(ws, state, log)
            elif msg_type == MsgType.JOIN_MATCH:
                await _handle_join(ws, state, message.get("invite"), log)
            elif msg_type == MsgType.RECONNECT_MATCH:
                await _handle_reconnect(
                    ws, state, message.get("invite"), message.get("role"), log
                )
            elif msg_type == MsgType.LEAVE_MATCH:
                await _handle_leave(ws, state, log)
            else:
                seat = state.seats.get(ws)
                if seat is None:
                    await _send(
                        ws,
                        error_message(ErrorCode.NOT_IN_MATCH, "Not in a Match"),
                    )
                    log.warning("message_rejected", reason="not_in_match")
                    continue
                invite, role = seat
                match = state.matches.get(invite)
                if match is None or match.ended:
                    await _send(
                        ws,
                        error_message(ErrorCode.UNKNOWN_INVITE, "Unknown Invite"),
                    )
                    log.warning(
                        "message_rejected",
                        reason="unknown_invite",
                        session_id=invite,
                    )
                    continue
                other = match.guest if role == "host" else match.host
                if other is None:
                    other_grace = (
                        match.guest_grace if role == "host" else match.host_grace
                    )
                    if other_grace is not None and not other_grace.done():
                        await _send(
                            ws,
                            error_message(
                                ErrorCode.PLAYER_GONE,
                                "Other Player disconnected; reconnect grace active",
                            ),
                        )
                    else:
                        await _send(
                            ws,
                            error_message(
                                ErrorCode.PLAYER_GONE,
                                "Other Player has not joined yet",
                            ),
                        )
                    log.warning(
                        "forward_failed",
                        reason="other_player_absent",
                        session_id=invite,
                        role=role,
                        msg_type=str(msg_type),
                    )
                    continue
                await _forward(
                    ws, other, raw if isinstance(raw, str) else raw.decode()
                )
                log.debug(
                    "message_forwarded",
                    session_id=invite,
                    role=role,
                    msg_type=str(msg_type),
                )
    except ConnectionClosed:
        # The client vanished mid-exchange (e.g. while we were replying). Treat
        # it as a normal disconnect and clean up rather than crashing the handler.
        log.debug("client_closed_during_exchange")
    finally:
        health.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await health
        _log_closure(ws, log)
        await _on_disconnect(ws, state)


@contextlib.asynccontextmanager
async def start_relay(
    bind_host: str = "127.0.0.1",
    port: int = 0,
    *,
    grace_seconds: float = DEFAULT_GRACE_SECONDS,
) -> AsyncGenerator[str, None]:
    """Start a local Relay; yield a ws:// URL callers can connect to."""
    state = _RelayState(grace_seconds=grace_seconds)

    async def handler(ws: ServerConnection) -> None:
        await _handle_client(ws, state)

    async with serve(
        handler,
        bind_host,
        port,
        ping_interval=KEEPALIVE_PING_INTERVAL,
        ping_timeout=KEEPALIVE_PING_TIMEOUT,
    ) as server:
        socks = server.sockets
        if not socks:
            raise RuntimeError("Relay failed to bind a socket")
        bound_port = socks[0].getsockname()[1]
        yield f"ws://{bind_host}:{bound_port}"
        await asyncio.sleep(0)


async def run_relay(
    bind_host: str = "127.0.0.1",
    port: int = 8765,
    *,
    grace_seconds: float = DEFAULT_GRACE_SECONDS,
) -> None:
    """Serve the Relay until cancelled (systemd / local process entry)."""
    state = _RelayState(grace_seconds=grace_seconds)

    async def handler(ws: ServerConnection) -> None:
        await _handle_client(ws, state)

    _log().info(
        "relay_starting",
        bind_host=bind_host,
        port=port,
        grace_seconds=grace_seconds,
        ping_interval=KEEPALIVE_PING_INTERVAL,
        ping_timeout=KEEPALIVE_PING_TIMEOUT,
    )
    async with serve(
        handler,
        bind_host,
        port,
        ping_interval=KEEPALIVE_PING_INTERVAL,
        ping_timeout=KEEPALIVE_PING_TIMEOUT,
    ):
        _log().info("relay_listening", bind_host=bind_host, port=port)
        await asyncio.Future()
