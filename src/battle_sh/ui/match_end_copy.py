"""Match-end outcome copy (You win / Opponent Won / Match Abandoned)."""

from __future__ import annotations

from battle_sh.networking.connection import MatchEnd
from battle_sh.networking.protocol import MatchOutcome, Role


def match_end_headline(role: Role, end: MatchEnd) -> str:
    if end.outcome == MatchOutcome.ABANDONED:
        return "Match Abandoned"
    if end.outcome == MatchOutcome.WINNER:
        if end.winner == role:
            return "You win"
        return "Opponent Won"
    return f"Match {end.outcome}"


def match_end_detail(role: Role, end: MatchEnd) -> str | None:
    """Optional one-liner under Abandoned; None when not useful."""
    if end.outcome != MatchOutcome.ABANDONED:
        return None
    reason = (end.reason or "").lower()
    if reason == "left":
        # Local confirmed quit uses reason "left".
        return "You left"
    if "disconnect" in reason or "grace" in reason or "opponent" in reason:
        return "Opponent left"
    return None
