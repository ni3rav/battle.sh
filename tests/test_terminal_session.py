"""Match-over-Relay seam via terminal session (scripted KeySource, not typed Coordinates)."""

from __future__ import annotations

import asyncio
from collections import deque

import pytest

from battle_sh.networking.connection import MatchConnection
from battle_sh.networking.relay import start_relay
from battle_sh.rules.board import parse_coordinate
from battle_sh.rules.placement import Coordinate, Placement, coordinate
from battle_sh.ui.aim_flow import initial_aim, step_skipping_fired
from battle_sh.ui.clock import FakeClock
from battle_sh.ui.keys import ScriptedKeySource
from battle_sh.ui.play import ScriptedIO, run_guest, run_host


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


def _aim_keys_for(
    target: Coordinate,
    *,
    last: Coordinate | None,
    fired: set[Coordinate],
) -> list[str]:
    """WASD + f sequence that Aims at ``target`` given last Shot and fired set."""
    frozen = frozenset(fired)
    start = initial_aim(last, frozen)
    if start == target:
        return ["f"]

    queue: deque[tuple[Coordinate, list[str]]] = deque([(start, [])])
    seen = {start}
    moves = (("d", 1, 0), ("a", -1, 0), ("s", 0, 1), ("w", 0, -1))
    while queue:
        cur, path = queue.popleft()
        for name, dc, dr in moves:
            nxt = step_skipping_fired(cur, dc, dr, frozen)
            if nxt is None or nxt in seen:
                continue
            new_path = [*path, name]
            if nxt == target:
                return [*new_path, "f"]
            seen.add(nxt)
            queue.append((nxt, new_path))
    raise RuntimeError(f"Cannot Aim path from {start} to {target}")


def _combat_key_script(targets: list[str]) -> list[str]:
    """Placement lock then Aim/fire each target in order (updating fired/last)."""
    keys: list[str] = ["y"]
    fired: set[Coordinate] = set()
    last: Coordinate | None = None
    for raw in targets:
        target = parse_coordinate(raw)
        keys.extend(_aim_keys_for(target, last=last, fired=fired))
        fired.add(target)
        last = target
    return keys


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
    # Guest miss Coordinates between Host turns (must be unique).
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
        inputs=deque(),
        keys=ScriptedKeySource(_combat_key_script(guest_targets)),
        clock=FakeClock(start=0.0),
    )
    guest_io = ScriptedIO(
        inputs=deque(),
        keys=ScriptedKeySource(_combat_key_script(guest_misses)),
        clock=FakeClock(start=0.0),
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
    assert "Match time 0:00" in "\n".join(host_io.outputs)
    assert "Match time 0:00" in "\n".join(guest_io.outputs)


async def test_guest_ui_reports_abandoned_when_host_disconnects() -> None:
    clock = FakeClock(start=0.0)
    guest_io = ScriptedIO(
        inputs=deque(), keys=ScriptedKeySource(["y"]), clock=clock
    )

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
        clock.advance(65.0)
        await host.close()
        await asyncio.wait_for(guest, timeout=10)

    assert "Abandoned" in "\n".join(guest_io.outputs)
    assert "Match time 1:05" in guest_io.outputs


async def test_host_quit_during_commitment_wait_abandons_for_guest() -> None:
    """Ctrl+C during wait-for-commitment sends leave_match → Abandoned."""
    host_io = ScriptedIO(
        inputs=deque(), keys=ScriptedKeySource(["y", "ctrl+c", "ctrl+c"])
    )

    async with start_relay(grace_seconds=0.05) as relay_url:
        invite_holder: list[str] = []
        guest_outcome: list[str] = []

        async def host_task() -> None:
            await run_host(
                relay_url,
                host_io,
                placement_factory=_placement_a,
                on_invite=lambda inv: invite_holder.append(inv),
                grace_seconds=0.05,
            )

        async def guest_task() -> None:
            for _ in range(100):
                if invite_holder:
                    break
                await asyncio.sleep(0.01)
            else:
                pytest.fail("Host never published Invite")
            guest = await MatchConnection.connect(relay_url, grace_seconds=0.05)
            try:
                await guest.join_match(invite_holder[0])
                await guest.wait_for_opponent_commitment()
                end = await guest.wait_for_match_end()
                guest_outcome.append(str(end.outcome))
                guest_outcome.append(end.reason or "")
            finally:
                await guest.close()

        await asyncio.wait_for(
            asyncio.gather(host_task(), guest_task()),
            timeout=15,
        )

    assert any("Quitting" in o or "Abandoned" in o for o in host_io.outputs)
    assert guest_outcome == ["abandoned", "left"]


async def test_host_quit_during_aim_abandons_for_guest() -> None:
    """Ctrl+C during Aim (combat) sends leave_match → Abandoned."""
    # Spacer key so wait_honoring_quit does not consume quit before Aim.
    host_io = ScriptedIO(
        inputs=deque(), keys=ScriptedKeySource(["y", "1", "ctrl+c", "ctrl+c"])
    )

    async with start_relay(grace_seconds=0.05) as relay_url:
        invite_holder: list[str] = []
        guest_outcome: list[str] = []

        async def host_task() -> None:
            await run_host(
                relay_url,
                host_io,
                placement_factory=_placement_a,
                on_invite=lambda inv: invite_holder.append(inv),
                grace_seconds=0.05,
            )

        async def guest_task() -> None:
            for _ in range(100):
                if invite_holder:
                    break
                await asyncio.sleep(0.01)
            else:
                pytest.fail("Host never published Invite")
            guest = await MatchConnection.connect(relay_url, grace_seconds=0.05)
            try:
                await guest.join_match(invite_holder[0])
                await guest.lock_placement(_placement_b())
                await guest.wait_for_opponent_commitment()
                end = await guest.wait_for_match_end()
                guest_outcome.append(str(end.outcome))
            finally:
                await guest.close()

        await asyncio.wait_for(
            asyncio.gather(host_task(), guest_task()),
            timeout=15,
        )

    assert any("Quitting" in o or "Abandoned" in o for o in host_io.outputs)
    assert guest_outcome == ["abandoned"]
