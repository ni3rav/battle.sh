"""Relay process seam: long-running bind for local and provisioned hosts."""

from __future__ import annotations

import asyncio

import pytest

from battle_sh.networking.connection import MatchConnection
from battle_sh.networking.relay import run_relay


async def test_run_relay_accepts_match_create_on_fixed_port() -> None:
    port = 18765
    server = asyncio.create_task(run_relay("127.0.0.1", port, grace_seconds=0.5))
    try:
        for _ in range(50):
            try:
                host = await MatchConnection.connect(f"ws://127.0.0.1:{port}")
                break
            except OSError:
                await asyncio.sleep(0.02)
        else:
            pytest.fail("Relay did not accept connections")

        try:
            invite = await host.create_match()
            assert isinstance(invite, str)
            assert invite.count("-") == 3
            assert invite == invite.lower()
        finally:
            await host.close()
    finally:
        server.cancel()
        with pytest.raises(asyncio.CancelledError):
            await server
