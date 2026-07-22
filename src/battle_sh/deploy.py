"""Render deploy artifacts for a cloud-agnostic Relay host (Caddy + systemd)."""

from __future__ import annotations


def render_caddyfile(*, domain: str, email: str, upstream: str) -> str:
    """Caddy terminates HTTPS/WSS for domain and proxies to the local Relay."""
    return (
        f"{{\n"
        f"\temail {email}\n"
        f"}}\n"
        f"\n"
        f"{domain} {{\n"
        f"\treverse_proxy {upstream}\n"
        f"}}\n"
    )


def render_relay_unit(
    *,
    install_dir: str,
    uv_bin: str = "/root/.local/bin/uv",
    bind_host: str = "127.0.0.1",
    port: int = 8765,
) -> str:
    """systemd unit: run the Relay under uv on loopback behind Caddy."""
    exec_start = (
        f"{uv_bin} run python -m battle_sh.networking.relay_cli "
        f"--bind-host {bind_host} --port {port}"
    )
    return (
        "[Unit]\n"
        "Description=battle.sh Match Relay\n"
        "After=network.target\n"
        "\n"
        "[Service]\n"
        "Type=simple\n"
        f"WorkingDirectory={install_dir}\n"
        f"Environment=PATH={uv_bin.rsplit('/', 1)[0]}:/usr/bin\n"
        f"ExecStart={exec_start}\n"
        "Restart=on-failure\n"
        "RestartSec=2\n"
        "\n"
        "[Install]\n"
        "WantedBy=multi-user.target\n"
    )
