"""Render deploy artifacts for a cloud-agnostic Relay host (Caddy + systemd)."""

from __future__ import annotations


def render_caddyfile(
    *,
    domain: str,
    email: str,
    upstream: str,
    tls_internal: bool = False,
) -> str:
    """Caddy terminates HTTPS/WSS for domain and proxies to the local Relay.

    ``tls_internal`` uses Caddy's local CA (practice VMs / Docker without
    public DNS). Real cloud hosts leave it false for Let's Encrypt.
    """
    global_block = f"{{\n\temail {email}\n}}\n\n"
    site_lines = [f"{domain} {{"]
    if tls_internal:
        site_lines.append("\ttls internal")
    site_lines.append(f"\treverse_proxy {upstream}")
    site_lines.append("}\n")
    return global_block + "\n".join(site_lines) + "\n"


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
