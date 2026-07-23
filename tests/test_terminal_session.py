"""Match-over-Relay seam via terminal session (scripted IO, not rich markup)."""

from __future__ import annotations

import asyncio
from collections import deque

import pytest

from battle_sh.networking.connection import MatchConnection
from battle_sh.networking.relay import start_relay
from battle_sh.rules.placement import Placement, coordinate
from battle_sh.ui.play import ScriptedIO, run_guest, run_host
from battle_sh.ui.keys import ScriptedKeySource


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


async def test_host_and_guest_sessions_complete_a_winner_match() -> None:
    """Scripted Host/Guest UI sessions play through to Winner over a local Relay."""
    guest_targets = [
        "J10",
        "J9",
        "A1",
        "B1",
        "C1",
        "D1",
        "E1",
        "A2",
        "B2",
        "C2",
        "D2",
        "A3",
        "B3",
        "C3",
        "A4",
        "B4",
        "C4",
    ]
    # Guest miss Coordinates between Host turns (must be unique — duplicates re-prompt).
    guest_misses = [
        "E5",
        "E6",
        "F5",
        "F6",
        "G5",
        "G6",
        "H5",
        "H6",
        "I5",
        "I6",
        "F7",
        "G7",
        "H7",
        "I7",
        "F8",
        "G8",
    ]
    assert len(guest_misses) == len(guest_targets) - 1
    host_io = ScriptedIO(
        inputs=deque(guest_targets),
        keys=ScriptedKeySource(["y"]),
    )
    guest_io = ScriptedIO(
        inputs=deque(guest_misses),
        keys=ScriptedKeySource(["y"]),
    )

    async with start_relay() as relay_url:
        invite_holder: list[str] = []

        async def host_task() -> None:
            await run_host(
                relay_url,
                host_io,
                placement_factory=_placement_a,
                on_invite=lambda inv: invite_holder.append(inv),
            )

        async def guest_task() -> None:
            for _ in range(100):
                if invite_holder:
                    break
                await asyncio.sleep(0.01)
            else:
                pytest.fail("Host never published Invite")
            await run_guest(
                relay_url,
                invite_holder[0],
                guest_io,
                placement_factory=_placement_b,
            )

        await asyncio.wait_for(
            asyncio.gather(host_task(), guest_task()),
            timeout=30,
        )

    joined = "\n".join(host_io.outputs + guest_io.outputs)
    assert "Winner" in joined
    assert "Commitment verification" in joined


async def test_guest_ui_reports_abandoned_when_host_disconnects() -> None:
    guest_io = ScriptedIO(inputs=deque(), keys=ScriptedKeySource(["y"]))

    async with start_relay(grace_seconds=0.05) as relay_url:
        host = await MatchConnection.connect(relay_url, grace_seconds=0.05)
        invite = await host.create_match()

        async def guest_task() -> None:
            await run_guest(
                relay_url,
                invite,
                guest_io,
                placement_factory=_placement_b,
                grace_seconds=0.05,
            )

        guest = asyncio.create_task(guest_task())
        await host.wait_for_player_joined()
        await host.lock_placement(_placement_a())
        # Guest locks via UI; wait until Host has opponent commitment
        await host.wait_for_opponent_commitment()
        await host.close()
        await asyncio.wait_for(guest, timeout=10)

    joined = "\n".join(guest_io.outputs)
    assert "Abandoned" in joined
