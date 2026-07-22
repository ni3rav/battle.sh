"""Player-facing Match connection over the Relay protocol."""

from __future__ import annotations

from typing import Any, Self

from websockets.asyncio.client import ClientConnection, connect

from battle_sh.networking.protocol import MsgType, decode, encode


class MatchConnectionError(Exception):
    """Raised when a Match create/join (or related) Relay reply is an error."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


class MatchConnection:
    def __init__(self, ws: ClientConnection) -> None:
        self._ws = ws

    @classmethod
    async def connect(cls, relay_url: str) -> Self:
        ws = await connect(relay_url)
        return cls(ws)

    async def create_match(self) -> str:
        await self._send({"type": MsgType.CREATE_MATCH})
        reply = await self._expect(MsgType.MATCH_CREATED)
        invite = reply.get("invite")
        if not isinstance(invite, str) or not invite:
            raise MatchConnectionError("unexpected", "Match created without Invite")
        return invite

    async def join_match(self, invite: str) -> None:
        await self._send({"type": MsgType.JOIN_MATCH, "invite": invite})
        await self._expect(MsgType.MATCH_JOINED)

    async def wait_for_player_joined(self) -> None:
        await self._expect(MsgType.PLAYER_JOINED)

    async def close(self) -> None:
        await self._ws.close()

    async def _expect(self, expected: MsgType) -> dict[str, Any]:
        reply = await self._recv()
        if reply.get("type") == MsgType.ERROR:
            raise MatchConnectionError(
                str(reply.get("code", "")),
                str(reply.get("message", "")),
            )
        if reply.get("type") != expected:
            raise MatchConnectionError(
                "unexpected",
                f"Unexpected reply: {reply.get('type')}",
            )
        return reply

    async def _send(self, message: dict[str, Any]) -> None:
        await self._ws.send(encode(message))

    async def _recv(self) -> dict[str, Any]:
        raw = await self._ws.recv()
        text = raw if isinstance(raw, str) else raw.decode()
        return decode(text)
