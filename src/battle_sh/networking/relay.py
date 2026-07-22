"""Local WebSocket Relay: Match membership and message forwarding only."""

from __future__ import annotations

import asyncio
import contextlib
import secrets
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from websockets.asyncio.server import ServerConnection, serve
from websockets.exceptions import ConnectionClosed

from battle_sh.networking.protocol import (
    ErrorCode,
    MsgType,
    decode,
    encode,
    error_message,
)


@dataclass
class _Match:
    invite: str
    host: ServerConnection
    guest: ServerConnection | None = None


@dataclass
class _RelayState:
    matches: dict[str, _Match] = field(default_factory=dict)
    seats: dict[ServerConnection, tuple[str, str]] = field(default_factory=dict)


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
    if match is None:
        await _send(ws, error_message(ErrorCode.UNKNOWN_INVITE, "Unknown Invite"))
        return
    if match.guest is not None:
        await _send(ws, error_message(ErrorCode.MATCH_FULL, "Match already has two Players"))
        return
    match.guest = ws
    state.seats[ws] = (invite, "guest")
    await _send(ws, {"type": MsgType.MATCH_JOINED, "invite": invite, "role": "guest"})
    await _send(
        match.host,
        {"type": MsgType.PLAYER_JOINED, "invite": invite, "role": "guest"},
    )


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
                if match is None:
                    await _send(
                        ws,
                        error_message(ErrorCode.UNKNOWN_INVITE, "Unknown Invite"),
                    )
                    continue
                other = match.guest if role == "host" else match.host
                if other is None:
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
        seat = state.seats.pop(ws, None)
        if seat is not None:
            invite, role = seat
            match = state.matches.get(invite)
            if match is not None:
                if role == "host":
                    if match.guest is not None:
                        with contextlib.suppress(ConnectionClosed):
                            await _send(
                                match.guest,
                                error_message(
                                    ErrorCode.PLAYER_GONE, "Host disconnected"
                                ),
                            )
                        state.seats.pop(match.guest, None)
                    state.matches.pop(invite, None)
                else:
                    match.guest = None
                    with contextlib.suppress(ConnectionClosed):
                        await _send(
                            match.host,
                            error_message(
                                ErrorCode.PLAYER_GONE, "Guest disconnected"
                            ),
                        )


@contextlib.asynccontextmanager
async def start_relay(
    bind_host: str = "127.0.0.1", port: int = 0
) -> AsyncIterator[str]:
    """Start a local Relay; yield a ws:// URL callers can connect to."""
    state = _RelayState()

    async def handler(ws: ServerConnection) -> None:
        await _handle_client(ws, state)

    async with serve(handler, bind_host, port) as server:
        socks = server.sockets
        if not socks:
            raise RuntimeError("Relay failed to bind a socket")
        bound_port = socks[0].getsockname()[1]
        yield f"ws://{bind_host}:{bound_port}"
        await asyncio.sleep(0)
