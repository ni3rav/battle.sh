"""Player-facing Match connection over the Relay protocol."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Self

from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed

from battle_sh.networking.protocol import (
    MatchOutcome,
    MsgType,
    Role,
    decode,
    encode,
)
from battle_sh.rules.placement import Placement, placement_commitment


class MatchConnectionError(Exception):
    """Raised when a Match create/join (or related) Relay reply is an error."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


class NotReadyToFireError(Exception):
    """Raised when a Shot is attempted before both Placement Commitments are in."""


@dataclass(frozen=True)
class MatchEnd:
    outcome: MatchOutcome
    winner: Role | None = None


class MatchConnection:
    def __init__(self, ws: ClientConnection, *, grace_seconds: float = 30.0) -> None:
        self._ws = ws
        self._grace_seconds = grace_seconds
        self._own_commitment: str | None = None
        self._opponent_commitment: str | None = None
        self._invite: str | None = None
        self._role: Role | None = None

    @classmethod
    async def connect(cls, relay_url: str, *, grace_seconds: float = 30.0) -> Self:
        ws = await connect(relay_url)
        return cls(ws, grace_seconds=grace_seconds)

    @property
    def invite(self) -> str | None:
        return self._invite

    @property
    def role(self) -> Role | None:
        return self._role

    @property
    def opponent_commitment(self) -> str | None:
        return self._opponent_commitment

    @property
    def ready_to_fire(self) -> bool:
        return self._own_commitment is not None and self._opponent_commitment is not None

    async def create_match(self) -> str:
        await self._send({"type": MsgType.CREATE_MATCH})
        reply = await self._expect(MsgType.MATCH_CREATED)
        invite = reply.get("invite")
        if not isinstance(invite, str) or not invite:
            raise MatchConnectionError("unexpected", "Match created without Invite")
        self._invite = invite
        self._role = "host"
        return invite

    async def join_match(self, invite: str) -> None:
        await self._send({"type": MsgType.JOIN_MATCH, "invite": invite})
        await self._expect(MsgType.MATCH_JOINED)
        self._invite = invite
        self._role = "guest"

    async def reconnect_match(self, invite: str, role: Role) -> None:
        await self._send(
            {"type": MsgType.RECONNECT_MATCH, "invite": invite, "role": role}
        )
        await self._expect(MsgType.MATCH_RESUMED)
        self._invite = invite
        self._role = role

    async def wait_for_player_joined(self) -> None:
        await self._expect(MsgType.PLAYER_JOINED)

    async def lock_placement(self, placement: Placement) -> str:
        """Validate Placement, seal it, and publish the Placement Commitment."""
        commitment = placement_commitment(placement)
        self._own_commitment = commitment
        await self._send(
            {"type": MsgType.PLACEMENT_COMMITMENT, "commitment": commitment}
        )
        return commitment

    async def wait_for_opponent_commitment(self) -> str:
        """Block until the opponent's Placement Commitment arrives."""
        if self._opponent_commitment is not None:
            return self._opponent_commitment
        reply = await self._expect(MsgType.PLACEMENT_COMMITMENT)
        value = reply.get("commitment")
        if not isinstance(value, str) or not value:
            raise MatchConnectionError(
                "unexpected", "Placement Commitment missing commitment"
            )
        self._opponent_commitment = value
        return value

    async def fire_shot(self, _coordinate: str) -> None:
        """Gate a Shot attempt until both Placement Commitments are exchanged."""
        if not self.ready_to_fire:
            raise NotReadyToFireError(
                "Cannot fire until both Placement Commitments are exchanged"
            )

    async def wait_for_match_end(self) -> MatchEnd:
        """Block until the Match ends as Abandoned or with a Winner."""
        try:
            reply = await self._expect(MsgType.MATCH_END)
        except ConnectionClosed:
            await asyncio.sleep(self._grace_seconds)
            return MatchEnd(outcome=MatchOutcome.ABANDONED)
        outcome_raw = reply.get("outcome")
        if outcome_raw == MatchOutcome.ABANDONED:
            return MatchEnd(outcome=MatchOutcome.ABANDONED)
        if outcome_raw == MatchOutcome.WINNER:
            winner = reply.get("winner")
            if winner not in ("host", "guest"):
                raise MatchConnectionError(
                    "unexpected", "Winner Match end missing winner role"
                )
            return MatchEnd(outcome=MatchOutcome.WINNER, winner=winner)
        raise MatchConnectionError(
            "unexpected", f"Unknown Match end outcome: {outcome_raw!r}"
        )

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
