"""Player-facing Match connection over the Relay protocol."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Self, cast

import structlog
from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed

from battle_sh.networking.protocol import (
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
from battle_sh.rules.board import (
    Board,
    DuplicateShotError,
    IllegalShotError,
    ShotAnswer,
    parse_coordinate,
)
from battle_sh.rules.placement import Coordinate, Placement, placement_commitment
from battle_sh.rules.reveal import (
    RevealVerificationError,
    placement_from_reveal,
    verify_fleet_reveal,
    verify_ship_reveal,
    verify_shot_answers_against_placement,
)


class MatchConnectionError(Exception):
    """Raised when a Match create/join (or related) Relay reply is an error."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


def close_code_and_reason(exc: ConnectionClosed) -> tuple[int | None, str]:
    """Extract the close code/reason without the deprecated ``.code`` accessor."""
    close = exc.rcvd or exc.sent
    if close is None:
        return None, ""
    return close.code, close.reason or ""


class NotReadyToFireError(Exception):
    """Raised when a Shot is attempted before both Placement Commitments are in."""


class NotYourTurnError(Exception):
    """Raised when a Player fires out of turn."""


@dataclass(frozen=True)
class MatchEnd:
    outcome: MatchOutcome
    winner: Role | None = None


@dataclass
class ShotReport:
    result: str
    coordinate: str
    ship: str | None = None
    revealed_cells: tuple[str, ...] = ()
    match_end: MatchEnd | None = None
    verification_ok: bool | None = None


@dataclass
class MatchConnection:
    _ws: ClientConnection
    _grace_seconds: float = 30.0
    _own_commitment: str | None = None
    _opponent_commitment: str | None = None
    _invite: str | None = None
    _role: Role | None = None
    _board: Board | None = None
    _my_turn: bool = False
    _outgoing: set[Coordinate] = field(default_factory=set[Coordinate])
    _opponent_answers: list[ShotAnswer] = field(default_factory=list[ShotAnswer])
    _match_end: MatchEnd | None = None
    _conn_id: str = field(default_factory=new_conn_id)

    @classmethod
    async def connect(cls, relay_url: str, *, grace_seconds: float = 30.0) -> Self:
        ws = await connect(
            relay_url,
            ping_interval=KEEPALIVE_PING_INTERVAL,
            ping_timeout=KEEPALIVE_PING_TIMEOUT,
        )
        conn = cls(_ws=ws, _grace_seconds=grace_seconds)
        conn._log().info("relay_connected", relay_url=relay_url)
        return conn

    def _log(self) -> structlog.stdlib.BoundLogger:
        return get_logger(
            component="connection",
            conn_id=self._conn_id,
            role=self._role,
            session_id=self._invite,
        )

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

    @property
    def my_turn(self) -> bool:
        return self._my_turn

    @property
    def match_end(self) -> MatchEnd | None:
        return self._match_end

    @property
    def is_connected(self) -> bool:
        """True while the underlying WebSocket to the Relay is open."""
        return self._ws.state.name == "OPEN"

    def _arm_turns_if_ready(self) -> None:
        if self.ready_to_fire and self._role is not None:
            self._my_turn = self._role == "host"

    async def create_match(self) -> str:
        await self._send({"type": MsgType.CREATE_MATCH})
        reply = await self._expect(MsgType.MATCH_CREATED)
        invite = reply.get("invite")
        if not isinstance(invite, str) or not invite:
            raise MatchConnectionError("unexpected", "Match created without Invite")
        self._invite = invite
        self._role = "host"
        self._log().info("match_created")
        return invite

    async def join_match(self, invite: str) -> None:
        await self._send({"type": MsgType.JOIN_MATCH, "invite": invite})
        await self._expect(MsgType.MATCH_JOINED)
        self._invite = invite
        self._role = "guest"
        self._log().info("match_joined")

    async def reconnect_match(self, invite: str, role: Role) -> None:
        await self._send(
            {"type": MsgType.RECONNECT_MATCH, "invite": invite, "role": role}
        )
        await self._expect(MsgType.MATCH_RESUMED)
        self._invite = invite
        self._role = role
        self._log().info("match_reconnected")

    async def wait_for_player_joined(self) -> None:
        await self._expect(MsgType.PLAYER_JOINED)

    async def lock_placement(self, placement: Placement) -> str:
        """Validate Placement, seal it, and publish the Placement Commitment."""
        commitment = placement_commitment(placement)
        self._board = Board(placement)
        self._own_commitment = commitment
        await self._send(
            {"type": MsgType.PLACEMENT_COMMITMENT, "commitment": commitment}
        )
        self._arm_turns_if_ready()
        self._log().info("placement_locked", commitment=commitment)
        return commitment

    async def wait_for_opponent_commitment(self) -> str:
        """Block until the opponent's Placement Commitment arrives."""
        if self._opponent_commitment is not None:
            self._arm_turns_if_ready()
            return self._opponent_commitment
        reply = await self._expect(MsgType.PLACEMENT_COMMITMENT)
        value = reply.get("commitment")
        if not isinstance(value, str) or not value:
            raise MatchConnectionError(
                "unexpected", "Placement Commitment missing commitment"
            )
        self._opponent_commitment = value
        self._arm_turns_if_ready()
        return value

    async def fire_shot(self, coordinate_text: str) -> ShotReport:
        """Fire one Shot on our turn; wait for the Board owner's answer (and Reveals)."""
        if not self.ready_to_fire:
            raise NotReadyToFireError(
                "Cannot fire until both Placement Commitments are exchanged"
            )
        if not self._my_turn:
            raise NotYourTurnError("It is not your turn to fire")
        try:
            coord = parse_coordinate(coordinate_text)
        except IllegalShotError:
            raise
        if coord in self._outgoing:
            raise DuplicateShotError(f"Already fired at {coord}")

        self._outgoing.add(coord)
        await self._send({"type": MsgType.SHOT, "coordinate": str(coord)})
        result_msg = await self._expect(MsgType.SHOT_RESULT)
        answer = self._parse_shot_result(result_msg, expected=coord)
        self._opponent_answers.append(answer)

        revealed: list[str] = []
        match_end: MatchEnd | None = None
        verification_ok: bool | None = None

        if answer.result == "sunk":
            reveal = await self._expect(MsgType.REVEAL)
            revealed = self._cells_from_ship_reveal(reveal, answer.ship)
            verify_ship_reveal(answer.ship or "", revealed, self._opponent_answers)
            if reveal.get("fleet_destroyed"):
                full = await self._expect(MsgType.REVEAL)
                self._verify_full_reveal(full)
                verification_ok = True
                end_msg = await self._expect(MsgType.MATCH_END)
                match_end = self._parse_match_end(end_msg)
                self._match_end = match_end

        self._my_turn = False

        self._log().info(
            "shot_fired",
            coordinate=str(coord),
            result=answer.result,
            ship=answer.ship,
            match_end=match_end.outcome if match_end is not None else None,
        )

        return ShotReport(
            result=answer.result,
            coordinate=str(coord),
            ship=answer.ship,
            revealed_cells=tuple(revealed),
            match_end=match_end,
            verification_ok=verification_ok,
        )

    async def serve_opponent_shot(self) -> ShotReport:
        """Answer one incoming Shot against our Board (split authority)."""
        if self._board is None:
            raise MatchConnectionError("unexpected", "No Placement locked")
        if self._my_turn:
            raise NotYourTurnError("Cannot answer a Shot on your own firing turn")

        shot_msg = await self._recv()
        if shot_msg.get("type") == MsgType.MATCH_END:
            end = self._parse_match_end(shot_msg)
            self._match_end = end
            self._log().info(
                "match_end_received", outcome=end.outcome, winner=end.winner
            )
            return ShotReport(
                result="miss",
                coordinate="",
                match_end=end,
            )
        if shot_msg.get("type") == MsgType.ERROR:
            raise MatchConnectionError(
                str(shot_msg.get("code", "")),
                str(shot_msg.get("message", "")),
            )
        if shot_msg.get("type") != MsgType.SHOT:
            raise MatchConnectionError(
                "unexpected",
                f"Unexpected reply: {shot_msg.get('type')}",
            )
        raw = shot_msg.get("coordinate")
        if not isinstance(raw, str):
            await self._send(
                error_message(ErrorCode.ILLEGAL_SHOT, "Shot missing coordinate")
            )
            raise IllegalShotError("Shot missing coordinate")
        try:
            coord = parse_coordinate(raw)
            answer = self._board.resolve_incoming(coord)
        except IllegalShotError as exc:
            await self._send(error_message(ErrorCode.ILLEGAL_SHOT, str(exc)))
            raise
        except DuplicateShotError as exc:
            await self._send(error_message(ErrorCode.DUPLICATE_SHOT, str(exc)))
            raise

        payload: dict[str, Any] = {
            "type": MsgType.SHOT_RESULT,
            "coordinate": str(coord),
            "result": answer.result,
        }
        if answer.ship is not None:
            payload["ship"] = answer.ship
        await self._send(payload)

        revealed: list[str] = []
        match_end: MatchEnd | None = None

        if answer.result == "sunk" and answer.ship is not None:
            cells = sorted(str(c) for c in self._board.ship_cells(answer.ship))
            revealed = cells
            await self._send(
                {
                    "type": MsgType.REVEAL,
                    "scope": "ship",
                    "ship": answer.ship,
                    "cells": cells,
                    "fleet_destroyed": self._board.fleet_destroyed,
                }
            )
            if self._board.fleet_destroyed:
                full_ships = {
                    name: sorted(str(c) for c in ship_cells)
                    for name, ship_cells in self._board.placement.ships.items()
                }
                await self._send(
                    {
                        "type": MsgType.REVEAL,
                        "scope": "fleet",
                        "ships": full_ships,
                    }
                )
                winner: Role = "guest" if self._role == "host" else "host"
                end = MatchEnd(outcome=MatchOutcome.WINNER, winner=winner)
                await self._send(
                    {
                        "type": MsgType.MATCH_END,
                        "outcome": MatchOutcome.WINNER,
                        "winner": winner,
                    }
                )
                self._match_end = end
                match_end = end

        if match_end is None:
            self._my_turn = True

        self._log().info(
            "shot_answered",
            coordinate=str(coord),
            result=answer.result,
            ship=answer.ship,
            match_end=match_end.outcome if match_end is not None else None,
        )

        return ShotReport(
            result=answer.result,
            coordinate=str(coord),
            ship=answer.ship,
            revealed_cells=tuple(revealed),
            match_end=match_end,
            verification_ok=None,
        )

    async def wait_for_match_end(self) -> MatchEnd:
        """Block until the Match ends as Abandoned or with a Winner."""
        if self._match_end is not None:
            return self._match_end
        try:
            reply = await self._expect(MsgType.MATCH_END)
        except ConnectionClosed as exc:
            code, reason = close_code_and_reason(exc)
            self._log().warning(
                "connection_lost_waiting_for_end",
                close_code=code,
                close_reason=reason,
                grace_seconds=self._grace_seconds,
            )
            await asyncio.sleep(self._grace_seconds)
            end = MatchEnd(outcome=MatchOutcome.ABANDONED)
            self._match_end = end
            return end
        end = self._parse_match_end(reply)
        self._match_end = end
        return end

    async def close(self) -> None:
        self._log().info("connection_closing")
        await self._ws.close()

    def _parse_shot_result(
        self, message: dict[str, Any], *, expected: Coordinate
    ) -> ShotAnswer:
        raw = message.get("coordinate")
        result = message.get("result")
        ship = message.get("ship")
        if raw != str(expected):
            raise MatchConnectionError(
                "unexpected", f"Shot result coordinate mismatch: {raw!r}"
            )
        if result not in ("miss", "hit", "sunk"):
            raise MatchConnectionError("unexpected", f"Bad shot result: {result!r}")
        if result == "sunk" and not isinstance(ship, str):
            raise MatchConnectionError("unexpected", "Sunk result missing ship")
        return ShotAnswer(
            coordinate=expected,
            result=result,  # type: ignore[arg-type]
            ship=ship if isinstance(ship, str) else None,
        )

    def _cells_from_ship_reveal(
        self, message: dict[str, Any], ship: str | None
    ) -> list[str]:
        if message.get("scope") != "ship":
            raise MatchConnectionError("unexpected", "Expected ship Reveal")
        if ship is not None and message.get("ship") != ship:
            raise MatchConnectionError("unexpected", "Reveal ship mismatch")
        cells = message.get("cells")
        if not isinstance(cells, list):
            raise MatchConnectionError("unexpected", "Reveal missing cells")
        typed_cells: list[str] = []
        for cell in cast(list[Any], cells):
            if not isinstance(cell, str):
                raise MatchConnectionError("unexpected", "Reveal missing cells")
            typed_cells.append(cell)
        return typed_cells

    def _verify_full_reveal(self, message: dict[str, Any]) -> None:
        if message.get("scope") != "fleet":
            raise MatchConnectionError("unexpected", "Expected fleet Reveal")
        ships = message.get("ships")
        if not isinstance(ships, dict):
            raise MatchConnectionError("unexpected", "Fleet Reveal missing ships")
        if self._opponent_commitment is None:
            raise MatchConnectionError("unexpected", "No opponent commitment")
        typed_ships: dict[str, list[str]] = {}
        for name, cells in cast(dict[Any, Any], ships).items():
            if not isinstance(name, str) or not isinstance(cells, list):
                raise MatchConnectionError("unexpected", "Fleet Reveal missing ships")
            typed_cells: list[str] = []
            for cell in cast(list[Any], cells):
                if not isinstance(cell, str):
                    raise MatchConnectionError(
                        "unexpected", "Fleet Reveal missing ships"
                    )
                typed_cells.append(cell)
            typed_ships[name] = typed_cells
        placement = placement_from_reveal(typed_ships)
        verify_fleet_reveal(placement, self._opponent_commitment)
        verify_shot_answers_against_placement(placement, self._opponent_answers)

    def _parse_match_end(self, reply: dict[str, Any]) -> MatchEnd:
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


# Re-export rule errors for seam callers
__all__ = [
    "DuplicateShotError",
    "IllegalShotError",
    "MatchConnection",
    "MatchConnectionError",
    "MatchEnd",
    "NotReadyToFireError",
    "NotYourTurnError",
    "RevealVerificationError",
    "ShotReport",
    "close_code_and_reason",
]
