"""WebSocket + JSON message framing for Match traffic."""

from __future__ import annotations

import json
from enum import StrEnum
from typing import Any


class MsgType(StrEnum):
    CREATE_MATCH = "create_match"
    MATCH_CREATED = "match_created"
    JOIN_MATCH = "join_match"
    MATCH_JOINED = "match_joined"
    PLAYER_JOINED = "player_joined"
    ERROR = "error"


class ErrorCode(StrEnum):
    MATCH_FULL = "match_full"
    UNKNOWN_INVITE = "unknown_invite"
    MALFORMED_INVITE = "malformed_invite"
    MALFORMED_MESSAGE = "malformed_message"
    ALREADY_IN_MATCH = "already_in_match"
    NOT_IN_MATCH = "not_in_match"
    PLAYER_GONE = "player_gone"


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
    return data


def error_message(code: ErrorCode, message: str) -> dict[str, Any]:
    return {"type": MsgType.ERROR, "code": code, "message": message}
