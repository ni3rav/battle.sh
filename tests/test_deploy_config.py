"""Deploy config renderers: Caddyfile and systemd unit content."""

from __future__ import annotations

from battle_sh.deploy import render_caddyfile, render_relay_unit


def test_caddyfile_terminates_https_for_domain_to_local_relay() -> None:
    text = render_caddyfile(
        domain="relay.example.com",
        email="ops@example.com",
        upstream="127.0.0.1:8765",
    )
    assert "relay.example.com" in text
    assert "ops@example.com" in text
    assert "reverse_proxy 127.0.0.1:8765" in text
    assert "tls internal" not in text


def test_caddyfile_tls_internal_for_practice_vms() -> None:
    text = render_caddyfile(
        domain="relay.local.test",
        email="ops@example.com",
        upstream="127.0.0.1:8765",
        tls_internal=True,
    )
    assert "tls internal" in text
    assert "reverse_proxy 127.0.0.1:8765" in text


def test_relay_unit_runs_uv_relay_on_loopback() -> None:
    text = render_relay_unit(
        install_dir="/opt/battle-sh",
        uv_bin="/root/.local/bin/uv",
        bind_host="127.0.0.1",
        port=8765,
    )
    assert "WorkingDirectory=/opt/battle-sh" in text
    assert "/root/.local/bin/uv run" in text
    assert "battle_sh.networking.relay_cli" in text
    assert "--bind-host 127.0.0.1" in text
    assert "--port 8765" in text
    assert "[Install]" in text
    assert "WantedBy=multi-user.target" in text
