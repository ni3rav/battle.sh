"""Local WebSocket Relay: Match membership and message forwarding only."""

from __future__ import annotations

import asyncio
import contextlib
import secrets
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, cast

from websockets.asyncio.server import ServerConnection, serve
from websockets.exceptions import ConnectionClosed

from battle_sh.networking.protocol import (
    ErrorCode,
    MatchOutcome,
    MsgType,
    Role,
    decode,
    encode,
    error_message,
)


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
    matches: dict[str, _Match] = field(default_factory=dict)
    seats: dict[ServerConnection, tuple[str, Role]] = field(default_factory=dict)
    grace_seconds: float = 30.0


def _mint_invite() -> str:
    return secrets.token_urlsafe(16)


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


async def _abandon_match(state: _RelayState, invite: str) -> None:
    match = state.matches.pop(invite, None)
    if match is None or match.ended:
        return
    match.ended = True
    current = asyncio.current_task()
    for task in (match.host_grace, match.guest_grace):
        if task is None or task is current or task.done():
            continue
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
    match.host_grace = None
    match.guest_grace = None
    for ws in (match.host, match.guest):
        if ws is None:
            continue
        state.seats.pop(ws, None)
        with contextlib.suppress(ConnectionClosed):
                        await _send(
                            ws,
                            {"type": MsgType.MATCH_END, "outcome": MatchOutcome.ABANDONED},
                        )


async def _start_grace(state: _RelayState, invite: str, role: Role) -> None:
    async def _expire() -> None:
        try:
            await asyncio.sleep(state.grace_seconds)
        except asyncio.CancelledError:
            return
        await _abandon_match(state, invite)

    match = state.matches.get(invite)
    if match is None:
        return
    task = asyncio.create_task(_expire())
    if role == "host":
        if match.host_grace is not None and not match.host_grace.done():
            match.host_grace.cancel()
        match.host_grace = task
    else:
        if match.guest_grace is not None and not match.guest_grace.done():
            match.guest_grace.cancel()
        match.guest_grace = task


async def _handle_create(ws: ServerConnection, state: _RelayState) -> None:
    if ws in state.seats:
        await _send(ws, error_message(ErrorCode.ALREADY_IN_MATCH, "Already in a Match"))
        return
    invite = _mint_invite()
    while invite in state.matches:
        invite = _mint_invite()
    state.matches[invite] = _Match(invite=invite, host=ws)
    state.seats[ws] = (invite, "host")
    await _send(ws, {"type": MsgType.MATCH_CREATED, "invite": invite, "role": "host"})


async def _handle_join(ws: ServerConnection, state: _RelayState, invite: object) -> None:
    if ws in state.seats:
        await _send(ws, error_message(ErrorCode.ALREADY_IN_MATCH, "Already in a Match"))
        return
    if not isinstance(invite, str) or not invite:
        await _send(
            ws,
            error_message(ErrorCode.MALFORMED_INVITE, "Invite must be a non-empty string"),
        )
        return
    match = state.matches.get(invite)
    if match is None or match.ended:
        await _send(ws, error_message(ErrorCode.UNKNOWN_INVITE, "Unknown Invite"))
        return
    if match.guest is not None:
        await _send(ws, error_message(ErrorCode.MATCH_FULL, "Match already has two Players"))
        return
    if match.guest_grace is not None and not match.guest_grace.done():
        await _send(
            ws,
            error_message(
                ErrorCode.MATCH_FULL,
                "Guest is held for reconnect; use reconnect_match",
            ),
        )
        return
    match.guest = ws
    state.seats[ws] = (invite, "guest")
    await _send(ws, {"type": MsgType.MATCH_JOINED, "invite": invite, "role": "guest"})
    if match.host is not None:
        await _send(
            match.host,
            {"type": MsgType.PLAYER_JOINED, "invite": invite, "role": "guest"},
        )


async def _handle_reconnect(
    ws: ServerConnection, state: _RelayState, invite: object, role: object
) -> None:
    if ws in state.seats:
        await _send(ws, error_message(ErrorCode.ALREADY_IN_MATCH, "Already in a Match"))
        return
    if not isinstance(invite, str) or not invite:
        await _send(
            ws,
            error_message(ErrorCode.MALFORMED_INVITE, "Invite must be a non-empty string"),
        )
        return
    if role not in ("host", "guest"):
        await _send(
            ws,
            error_message(ErrorCode.MALFORMED_MESSAGE, "Role must be host or guest"),
        )
        return
    claimed_role = cast(Role, role)
    match = state.matches.get(invite)
    if match is None or match.ended:
        await _send(ws, error_message(ErrorCode.UNKNOWN_INVITE, "Unknown Invite"))
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
        return
    if grace is None or grace.done():
        await _send(
            ws,
            error_message(ErrorCode.UNKNOWN_INVITE, "Reconnect grace has expired"),
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
    # Both seats empty with no grace yet: still start grace for the departing seat.
    # If the other seat is also vacant and its grace already running, either expiry abandons.
    await _start_grace(state, invite, role)


async def _handle_client(ws: ServerConnection, state: _RelayState) -> None:
    try:
        async for raw in ws:
            try:
                message = decode(raw if isinstance(raw, str) else raw.decode())
            except ValueError as exc:
                await _send(ws, error_message(ErrorCode.MALFORMED_MESSAGE, str(exc)))
                continue

            msg_type = message.get("type")
            if msg_type == MsgType.CREATE_MATCH:
                await _handle_create(ws, state)
            elif msg_type == MsgType.JOIN_MATCH:
                await _handle_join(ws, state, message.get("invite"))
            elif msg_type == MsgType.RECONNECT_MATCH:
                await _handle_reconnect(
                    ws, state, message.get("invite"), message.get("role")
                )
            else:
                seat = state.seats.get(ws)
                if seat is None:
                    await _send(
                        ws,
                        error_message(ErrorCode.NOT_IN_MATCH, "Not in a Match"),
                    )
                    continue
                invite, role = seat
                match = state.matches.get(invite)
                if match is None or match.ended:
                    await _send(
                        ws,
                        error_message(ErrorCode.UNKNOWN_INVITE, "Unknown Invite"),
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
                    continue
                await _forward(
                    ws, other, raw if isinstance(raw, str) else raw.decode()
                )
    finally:
        await _on_disconnect(ws, state)


@contextlib.asynccontextmanager
async def start_relay(
    bind_host: str = "127.0.0.1",
    port: int = 0,
    *,
    grace_seconds: float = 30.0,
) -> AsyncIterator[str]:
    """Start a local Relay; yield a ws:// URL callers can connect to."""
    state = _RelayState(grace_seconds=grace_seconds)

    async def handler(ws: ServerConnection) -> None:
        await _handle_client(ws, state)

    async with serve(handler, bind_host, port) as server:
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
    grace_seconds: float = 30.0,
) -> None:
    """Serve the Relay until cancelled (systemd / local process entry)."""
    state = _RelayState(grace_seconds=grace_seconds)

    async def handler(ws: ServerConnection) -> None:
        await _handle_client(ws, state)

    async with serve(handler, bind_host, port):
        await asyncio.Future()
