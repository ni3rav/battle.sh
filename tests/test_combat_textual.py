"""Combat through Winner in Textual: Aim chrome, wait, scripted Match, opening."""

from __future__ import annotations

from collections import deque

import pytest

from textual.pilot import Pilot

from battle_sh.networking.relay import start_relay
from battle_sh.rules.placement import COLUMNS, ROWS, Coordinate, Placement, coordinate
from battle_sh.ui.aim_flow import initial_aim, step_skipping_fired
from battle_sh.ui.clock import FakeClock
from battle_sh.ui.keys import MOVE_DELTA
from battle_sh.ui.textual_app import (
    BattleShApp,
    CombatScreen,
    FLEET_PREVIEW_HEIGHT,
    FLEET_PREVIEW_WIDTH,
    JoinScreen,
    MatchEndScreen,
    OpeningScreen,
    PlacementScreen,
)
from textual_helpers import host_to_waiting, make_app, wait_until


def _fixed_placement() -> Placement:
    return Placement(
        {
            "Carrier": frozenset(coordinate(c, 1) for c in "ABCDE"),
            "Battleship": frozenset(coordinate(c, 2) for c in "ABCD"),
            "Cruiser": frozenset(coordinate(c, 3) for c in "ABC"),
            "Submarine": frozenset(coordinate(c, 4) for c in "ABC"),
            "Destroyer": frozenset(coordinate(c, 5) for c in "AB"),
        }
    )


def _fleet_cells(placement: Placement) -> list[Coordinate]:
    cells: list[Coordinate] = []
    for row in ROWS:
        for col in COLUMNS:
            cell = coordinate(col, row)
            if any(cell in ships for ships in placement.ships.values()):
                cells.append(cell)
    return cells


def _keys_to_fire(
    start: Coordinate, target: Coordinate, fired: frozenset[Coordinate]
) -> list[str]:
    """Shortest Aim key path from ``start`` to ``target``, then fire."""
    aim0 = start if start not in fired else initial_aim(start, fired)
    if aim0 == target:
        return ["f"]
    queue: deque[tuple[Coordinate, list[str]]] = deque([(aim0, [])])
    seen = {aim0}
    while queue:
        cur, path = queue.popleft()
        for token, (dc, dr) in MOVE_DELTA.items():
            if token in {"up", "down", "left", "right"}:
                continue  # prefer wasd tokens only
            nxt = step_skipping_fired(cur, dc, dr, fired)
            if nxt is None or nxt in seen:
                continue
            nxt_path = [*path, token]
            if nxt == target:
                return [*nxt_path, "f"]
            seen.add(nxt)
            queue.append((nxt, nxt_path))
    raise AssertionError(f"no Aim path from {aim0} to {target}")


async def _both_to_combat(
    host_pilot: Pilot[None],
    guest_pilot: Pilot[None],
    host_app: BattleShApp,
    guest_app: BattleShApp,
    invite: str,
) -> None:
    await guest_pilot.pause()
    await guest_pilot.press("down", "down", "enter")
    await wait_until(guest_pilot, lambda: isinstance(guest_app.screen, JoinScreen))
    await guest_pilot.press(*list(invite))
    await guest_pilot.press("enter")
    await wait_until(
        guest_pilot, lambda: isinstance(guest_app.screen, PlacementScreen)
    )
    await wait_until(host_pilot, lambda: isinstance(host_app.screen, PlacementScreen))
    await host_pilot.press("y")
    await guest_pilot.press("y")
    await wait_until(host_pilot, lambda: isinstance(host_app.screen, CombatScreen))
    await wait_until(guest_pilot, lambda: isinstance(guest_app.screen, CombatScreen))


@pytest.mark.asyncio
async def test_combat_screen_has_aim_chrome_and_controls() -> None:
    async with start_relay() as relay_url:
        host_app = make_app(relay_url, placement_factory=_fixed_placement)
        guest_app = make_app(relay_url, placement_factory=_fixed_placement)
        async with host_app.run_test(size=(120, 40)) as host_pilot:
            waiting = await host_to_waiting(host_pilot, host_app)
            invite = waiting.displayed_invite()
            assert invite is not None
            async with guest_app.run_test(size=(120, 40)) as guest_pilot:
                await _both_to_combat(
                    host_pilot, guest_pilot, host_app, guest_app, invite
                )
                host_screen = host_app.screen
                assert isinstance(host_screen, CombatScreen)
                assert "Aim" in host_screen.info_text()
                assert "Match time" in host_screen.info_text()
                controls = host_screen.controls_text()
                assert "fire" in controls
                assert "move" in controls
                assert "f" in controls.lower()
                assert "`f`" not in controls
                assert "quit" in controls.lower()
                assert "lock" not in controls.lower()
                board = host_screen.board_text()
                assert "Opponent" in board or "Aim" in board or "+" in board
                assert "Your fleet" in board or "C" in board


@pytest.mark.asyncio
async def test_combat_fleet_preview_left_of_opponent_at_16_9() -> None:
    """Your fleet sits in a ~16:9 preview frame to the left of the opponent board."""
    async with start_relay() as relay_url:
        host_app = make_app(relay_url, placement_factory=_fixed_placement)
        guest_app = make_app(relay_url, placement_factory=_fixed_placement)
        async with host_app.run_test(size=(120, 32)) as host_pilot:
            waiting = await host_to_waiting(host_pilot, host_app)
            invite = waiting.displayed_invite()
            assert invite is not None
            async with guest_app.run_test(size=(120, 32)) as guest_pilot:
                await _both_to_combat(
                    host_pilot, guest_pilot, host_app, guest_app, invite
                )
                host_screen = host_app.screen
                assert isinstance(host_screen, CombatScreen)
                fleet = host_screen.query_one("#fleet-preview")
                tracking = host_screen.query_one("#board")
                panel = host_screen.query_one("#board-panel")
                assert fleet.region.x < tracking.region.x
                assert fleet.region.width == FLEET_PREVIEW_WIDTH
                assert fleet.region.height == FLEET_PREVIEW_HEIGHT
                # Character-cell aspect 16:9 (columns:rows).
                assert abs(fleet.region.width / fleet.region.height - 16 / 9) < 0.05
                assert tracking.region.height <= panel.region.height
                assert tracking.region.width >= 30
                board = host_screen.board_text()
                assert board.count("10") >= 2
                assert "Your fleet" in board
                assert "Opponent" in board


@pytest.mark.asyncio
async def test_off_turn_wait_shows_spinner_and_ignores_aim_keys() -> None:
    async with start_relay() as relay_url:
        host_app = make_app(relay_url, placement_factory=_fixed_placement)
        guest_app = make_app(relay_url, placement_factory=_fixed_placement)
        async with host_app.run_test(size=(120, 40)) as host_pilot:
            waiting = await host_to_waiting(host_pilot, host_app)
            invite = waiting.displayed_invite()
            assert invite is not None
            async with guest_app.run_test(size=(120, 40)) as guest_pilot:
                await _both_to_combat(
                    host_pilot, guest_pilot, host_app, guest_app, invite
                )
                guest_screen = guest_app.screen
                assert isinstance(guest_screen, CombatScreen)
                await wait_until(
                    guest_pilot,
                    lambda: "Waiting" in guest_screen.info_text(),
                )
                controls = guest_screen.controls_text()
                assert "quit" in controls.lower()
                assert "fire" not in controls
                await guest_pilot.pause(0.3)
                status_before = guest_screen.status_text()
                assert any(ch in status_before for ch in "|/-\\")
                await guest_pilot.press("w", "a", "s", "d", "f", "enter", "space")
                await guest_pilot.pause()
                assert isinstance(guest_app.screen, CombatScreen)
                assert "Waiting" in guest_app.screen.info_text()
                assert "fire" not in guest_app.screen.controls_text()


@pytest.mark.asyncio
async def test_scripted_winner_match_then_opening_with_frozen_match_time() -> None:
    clock = FakeClock(start=0.0)
    async with start_relay() as relay_url:
        host_app = make_app(relay_url, clock, placement_factory=_fixed_placement)
        guest_app = make_app(relay_url, clock, placement_factory=_fixed_placement)
        async with host_app.run_test(size=(120, 40)) as host_pilot:
            waiting = await host_to_waiting(host_pilot, host_app)
            invite = waiting.displayed_invite()
            assert invite is not None
            async with guest_app.run_test(size=(120, 40)) as guest_pilot:
                await _both_to_combat(
                    host_pilot, guest_pilot, host_app, guest_app, invite
                )
                clock.advance(95.0)

                targets = _fleet_cells(_fixed_placement())
                host_fired: set[Coordinate] = set()
                guest_fired: set[Coordinate] = set()
                host_aim = coordinate("A", 1)
                guest_aim = coordinate("A", 1)

                for i, target in enumerate(targets):
                    # Host Aim turn (observable: Aim chrome, not Waiting).
                    await wait_until(
                        host_pilot,
                        lambda: isinstance(host_app.screen, CombatScreen)
                        and "Aim" in host_app.screen.info_text()
                        and "Waiting" not in host_app.screen.info_text(),
                        attempts=120,
                    )
                    keys = _keys_to_fire(
                        host_aim, target, frozenset(host_fired)
                    )
                    await host_pilot.press(*keys)
                    host_fired.add(target)
                    host_aim = target

                    await wait_until(
                        host_pilot,
                        lambda: isinstance(host_app.screen, MatchEndScreen)
                        or (
                            isinstance(host_app.screen, CombatScreen)
                            and "Waiting" in host_app.screen.info_text()
                        ),
                        attempts=120,
                    )
                    if isinstance(host_app.screen, MatchEndScreen):
                        break

                    # Guest Aim turn (filler — same fleet cells; Host fires first so wins).
                    filler = targets[i]
                    await wait_until(
                        guest_pilot,
                        lambda: isinstance(guest_app.screen, CombatScreen)
                        and "Aim" in guest_app.screen.info_text()
                        and "Waiting" not in guest_app.screen.info_text(),
                        attempts=120,
                    )
                    gkeys = _keys_to_fire(
                        guest_aim, filler, frozenset(guest_fired)
                    )
                    await guest_pilot.press(*gkeys)
                    guest_fired.add(filler)
                    guest_aim = filler

                await wait_until(
                    host_pilot,
                    lambda: isinstance(host_app.screen, MatchEndScreen),
                    attempts=120,
                )
                await wait_until(
                    guest_pilot,
                    lambda: isinstance(guest_app.screen, MatchEndScreen),
                    attempts=120,
                )
                host_end = host_app.screen
                assert isinstance(host_end, MatchEndScreen)
                body = host_end.body_text()
                assert "win" in body.lower() or "Winner" in body
                assert "Match time 1:35" in body or "1:35" in host_end.info_text()
                # Frozen: advancing clock must not change the shown Match time.
                clock.advance(60.0)
                await host_pilot.pause(0.3)
                assert "1:35" in host_end.body_text() or "1:35" in host_end.info_text()

                await host_pilot.press("enter")
                await wait_until(
                    host_pilot,
                    lambda: isinstance(host_app.screen, OpeningScreen),
                    attempts=80,
                )
                await guest_pilot.press("enter")
                await wait_until(
                    guest_pilot,
                    lambda: isinstance(guest_app.screen, OpeningScreen),
                    attempts=80,
                )
                # Same process / Relay config: Host again from opening.
                waiting2 = await host_to_waiting(host_pilot, host_app)
                assert waiting2.displayed_invite() is not None


@pytest.mark.asyncio
async def test_two_step_ctrl_c_during_combat_wait_abandons() -> None:
    """Off-turn wait: confirmed Ctrl+C sends leave_match; opponent Abandons now."""
    clock = FakeClock(start=0.0)
    async with start_relay() as relay_url:
        host_app = make_app(relay_url, clock, placement_factory=_fixed_placement)
        guest_app = make_app(relay_url, clock, placement_factory=_fixed_placement)
        async with host_app.run_test(size=(120, 40)) as host_pilot:
            waiting = await host_to_waiting(host_pilot, host_app)
            invite = waiting.displayed_invite()
            assert invite is not None
            async with guest_app.run_test(size=(120, 40)) as guest_pilot:
                await _both_to_combat(
                    host_pilot, guest_pilot, host_app, guest_app, invite
                )
                await wait_until(
                    guest_pilot,
                    lambda: isinstance(guest_app.screen, CombatScreen)
                    and "Waiting" in guest_app.screen.info_text(),
                )
                await guest_pilot.press("ctrl+c")
                await guest_pilot.pause()
                assert isinstance(guest_app.screen, CombatScreen)
                assert "Press Ctrl+C again" in guest_app.screen.status_text()
                clock.advance(1.0)
                await guest_pilot.press("ctrl+c")
                await wait_until(
                    guest_pilot,
                    lambda: isinstance(guest_app.screen, MatchEndScreen)
                    and "Abandoned" in guest_app.screen.body_text(),
                    attempts=100,
                )
                assert isinstance(guest_app.screen, MatchEndScreen)
                assert guest_app.screen.end.outcome == "abandoned"
                assert guest_app.screen.end.reason == "left"
                await wait_until(
                    host_pilot,
                    lambda: isinstance(host_app.screen, MatchEndScreen)
                    and "Abandoned" in host_app.screen.body_text(),
                    attempts=100,
                )
                assert isinstance(host_app.screen, MatchEndScreen)
                assert host_app.screen.end.outcome == "abandoned"
                assert host_app.screen.end.reason == "left"
                await guest_pilot.press("enter")
                await host_pilot.press("enter")
                await wait_until(
                    guest_pilot,
                    lambda: isinstance(guest_app.screen, OpeningScreen),
                    attempts=80,
                )
                await wait_until(
                    host_pilot,
                    lambda: isinstance(host_app.screen, OpeningScreen),
                    attempts=80,
                )


@pytest.mark.asyncio
async def test_two_step_ctrl_c_during_aim_abandons_via_leave_match() -> None:
    """Mid-Aim confirmed Ctrl+C sends leave_match; opponent Abandons immediately."""
    from battle_sh.networking.connection import MatchConnection

    clock = FakeClock(start=0.0)
    async with start_relay() as relay_url:
        host_app = make_app(relay_url, clock, placement_factory=_fixed_placement)
        guest_conn: MatchConnection | None = None
        try:
            async with host_app.run_test(size=(120, 40)) as host_pilot:
                waiting = await host_to_waiting(host_pilot, host_app)
                invite = waiting.displayed_invite()
                assert invite is not None

                guest_conn = await MatchConnection.connect(relay_url)
                await guest_conn.join_match(invite)
                await wait_until(
                    host_pilot,
                    lambda: isinstance(host_app.screen, PlacementScreen),
                )
                await host_pilot.press("y")
                await guest_conn.lock_placement(_fixed_placement())
                await guest_conn.wait_for_opponent_commitment()
                await wait_until(
                    host_pilot,
                    lambda: isinstance(host_app.screen, CombatScreen)
                    and "Aim" in host_app.screen.info_text()
                    and "Waiting" not in host_app.screen.info_text(),
                )

                await host_pilot.press("ctrl+c")
                await host_pilot.pause()
                assert isinstance(host_app.screen, CombatScreen)
                assert "Press Ctrl+C again" in host_app.screen.status_text()
                clock.advance(1.0)
                await host_pilot.press("ctrl+c")
                await wait_until(
                    host_pilot,
                    lambda: isinstance(host_app.screen, MatchEndScreen)
                    and "Abandoned" in host_app.screen.body_text(),
                    attempts=100,
                )
                assert isinstance(host_app.screen, MatchEndScreen)
                assert host_app.screen.end.outcome == "abandoned"
                assert host_app.screen.end.reason == "left"

                end = await guest_conn.wait_for_match_end()
                assert end.outcome == "abandoned"
                assert end.reason == "left"

                await host_pilot.press("enter")
                await wait_until(
                    host_pilot,
                    lambda: isinstance(host_app.screen, OpeningScreen),
                    attempts=80,
                )
        finally:
            if guest_conn is not None:
                await guest_conn.close()


@pytest.mark.asyncio
async def test_no_back_during_combat_and_q_does_not_quit() -> None:
    async with start_relay() as relay_url:
        host_app = make_app(relay_url, placement_factory=_fixed_placement)
        guest_app = make_app(relay_url, placement_factory=_fixed_placement)
        async with host_app.run_test(size=(120, 40)) as host_pilot:
            waiting = await host_to_waiting(host_pilot, host_app)
            invite = waiting.displayed_invite()
            assert invite is not None
            async with guest_app.run_test(size=(120, 40)) as guest_pilot:
                await _both_to_combat(
                    host_pilot, guest_pilot, host_app, guest_app, invite
                )
                await host_pilot.press("escape")
                await host_pilot.pause()
                assert isinstance(host_app.screen, CombatScreen)
                await host_pilot.press("q")
                await host_pilot.pause()
                assert host_app.is_running
                assert isinstance(host_app.screen, CombatScreen)
