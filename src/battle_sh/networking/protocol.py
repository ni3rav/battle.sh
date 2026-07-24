"""WebSocket + JSON message framing for Match traffic."""

from __future__ import annotations

import json
from enum import StrEnum
from typing import Any, Literal, cast


class MsgType(StrEnum):
    CREATE_MATCH = "create_match"
    MATCH_CREATED = "match_created"
    JOIN_MATCH = "join_match"
    MATCH_JOINED = "match_joined"
    PLAYER_JOINED = "player_joined"
    RECONNECT_MATCH = "reconnect_match"
    MATCH_RESUMED = "match_resumed"
    PLACEMENT_COMMITMENT = "placement_commitment"
    SHOT = "shot"
    SHOT_RESULT = "shot_result"
    REVEAL = "reveal"
    MATCH_END = "match_end"
    ERROR = "error"


class MatchOutcome(StrEnum):
    ABANDONED = "abandoned"
    WINNER = "winner"


Role = Literal["host", "guest"]


# WebSocket keepalive (seconds). Both Relay and clients ping on this interval and
# close a peer that fails to pong within the timeout. Clients keep the event loop
# free during input so pongs are always answered promptly (see ui.play).
KEEPALIVE_PING_INTERVAL = 20.0
KEEPALIVE_PING_TIMEOUT = 20.0


class ErrorCode(StrEnum):
    MATCH_FULL = "match_full"
    UNKNOWN_INVITE = "unknown_invite"
    MALFORMED_INVITE = "malformed_invite"
    MALFORMED_MESSAGE = "malformed_message"
    ALREADY_IN_MATCH = "already_in_match"
    NOT_IN_MATCH = "not_in_match"
    PLAYER_GONE = "player_gone"
    ILLEGAL_SHOT = "illegal_shot"
    DUPLICATE_SHOT = "duplicate_shot"


def encode(message: dict[str, Any]) -> str:
    return json.dumps(message, separators=(",", ":"), sort_keys=True)


def decode(raw: str) -> dict[str, Any]:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON: {exc.msg}") from exc
    if not isinstance(data, dict):
        raise ValueError("Message must be a JSON object")
    if "type" not in data:
        raise ValueError("Message missing type")
    return cast(dict[str, Any], data)


def error_message(code: ErrorCode, message: str) -> dict[str, Any]:
    return {"type": MsgType.ERROR, "code": code, "message": message}
