"""Cloud-agnostic Relay provision over SSH (uv + Caddy + systemd)."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from battle_sh.deploy import render_caddyfile, render_relay_unit

DEFAULT_INSTALL_DIR = "/opt/battle-sh"
DEFAULT_PORT = 8765
DEFAULT_UV_BIN = "/root/.local/bin/uv"
UNIT_NAME = "battle-sh-relay.service"
CADDY_UNIT = "caddy.service"


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Provision any SSH-able Linux host as a TLS-facing battle.sh Relay "
            "(uv app + Caddy + systemd). Not cloud-vendor specific."
        )
    )
    parser.add_argument(
        "--host",
        required=True,
        help="SSH target, e.g. root@203.0.113.10 or user@relay.example.com",
    )
    parser.add_argument(
        "--domain",
        required=True,
        help="Public DNS name for wss:// (A/AAAA must already point at the host)",
    )
    parser.add_argument(
        "--email",
        required=True,
        help="Email for Caddy / Let's Encrypt registration",
    )
    parser.add_argument(
        "--install-dir",
        default=DEFAULT_INSTALL_DIR,
        help=f"Remote install directory (default: {DEFAULT_INSTALL_DIR})",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help=f"Local Relay port behind Caddy (default: {DEFAULT_PORT})",
    )
    parser.add_argument(
        "--uv-bin",
        default=DEFAULT_UV_BIN,
        help=f"Remote uv binary path (default: {DEFAULT_UV_BIN})",
    )
    parser.add_argument(
        "--tls-internal",
        action="store_true",
        help=(
            "Use Caddy tls internal (self-signed). For Docker practice VMs "
            "without public DNS. Do not use on a real internet-facing host."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Write Caddyfile and systemd unit locally; do not SSH",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="Where dry-run writes artifacts (required with --dry-run)",
    )
    parser.add_argument(
        "--ssh-option",
        action="append",
        default=[],
        help="Extra ssh -o OPTION (repeatable)",
    )
    return parser


def write_dry_run_artifacts(
    output_dir: Path,
    *,
    domain: str,
    email: str,
    install_dir: str,
    port: int,
    uv_bin: str,
    tls_internal: bool = False,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    upstream = f"127.0.0.1:{port}"
    (output_dir / "Caddyfile").write_text(
        render_caddyfile(
            domain=domain,
            email=email,
            upstream=upstream,
            tls_internal=tls_internal,
        )
    )
    (output_dir / UNIT_NAME).write_text(
        render_relay_unit(
            install_dir=install_dir,
            uv_bin=uv_bin,
            bind_host="127.0.0.1",
            port=port,
        )
    )


def _ssh(host: str, remote_cmd: str, ssh_options: list[str]) -> None:
    cmd = ["ssh"]
    for opt in ssh_options:
        cmd.extend(["-o", opt])
    cmd.extend([host, remote_cmd])
    subprocess.run(cmd, check=True)


def _rsync(host: str, local: Path, remote_dir: str, ssh_options: list[str]) -> None:
    ssh_cmd = "ssh"
    if ssh_options:
        ssh_cmd = "ssh " + " ".join(f"-o {opt}" for opt in ssh_options)
    cmd = [
        "rsync",
        "-az",
        "--delete",
        "--exclude",
        ".venv",
        "--exclude",
        ".git",
        "--exclude",
        ".pytest_cache",
        "-e",
        ssh_cmd,
        f"{local}/",
        f"{host}:{remote_dir}/",
    ]
    subprocess.run(cmd, check=True)


def provision_remote(
    *,
    host: str,
    domain: str,
    email: str,
    install_dir: str,
    port: int,
    uv_bin: str,
    ssh_options: list[str],
    tls_internal: bool = False,
) -> None:
    root = _repo_root()
    upstream = f"127.0.0.1:{port}"
    caddyfile = render_caddyfile(
        domain=domain,
        email=email,
        upstream=upstream,
        tls_internal=tls_internal,
    )
    unit = render_relay_unit(
        install_dir=install_dir,
        uv_bin=uv_bin,
        bind_host="127.0.0.1",
        port=port,
    )

    _ssh(host, f"mkdir -p {install_dir}", ssh_options)
    _rsync(host, root, install_dir, ssh_options)

    remote_script = f"""
set -euo pipefail
export PATH="$HOME/.local/bin:/usr/local/bin:$PATH"
if ! command -v uv >/dev/null 2>&1; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
fi
if ! command -v caddy >/dev/null 2>&1; then
  if command -v apt-get >/dev/null 2>&1; then
    apt-get update
    apt-get install -y debian-keyring debian-archive-keyring apt-transport-https curl
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \\
      | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \\
      | tee /etc/apt/sources.list.d/caddy-stable.list
    apt-get update
    apt-get install -y caddy
  else
    echo "Install Caddy manually, then re-run provision." >&2
    exit 1
  fi
fi
cd {install_dir}
uv sync
mkdir -p /etc/caddy /etc/systemd/system
cat > /etc/caddy/Caddyfile <<'CADDY_EOF'
{caddyfile}CADDY_EOF
cat > /etc/systemd/system/{UNIT_NAME} <<'UNIT_EOF'
{unit}UNIT_EOF
systemctl daemon-reload
systemctl enable --now {UNIT_NAME}
systemctl enable --now {CADDY_UNIT}
systemctl reload {CADDY_UNIT} || systemctl restart {CADDY_UNIT}
"""
    _ssh(host, remote_script, ssh_options)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.dry_run:
        if args.output_dir is None:
            parser.error("--output-dir is required with --dry-run")
        write_dry_run_artifacts(
            args.output_dir,
            domain=args.domain,
            email=args.email,
            install_dir=args.install_dir,
            port=args.port,
            uv_bin=args.uv_bin,
            tls_internal=args.tls_internal,
        )
        print(f"Dry-run artifacts written to {args.output_dir}")
        return 0

    provision_remote(
        host=args.host,
        domain=args.domain,
        email=args.email,
        install_dir=args.install_dir,
        port=args.port,
        uv_bin=args.uv_bin,
        ssh_options=args.ssh_option,
        tls_internal=args.tls_internal,
    )
    print(
        f"Provisioned Relay on {args.host}; Players should use wss://{args.domain}"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except subprocess.CalledProcessError as exc:
        print(f"provision failed: {exc}", file=sys.stderr)
        raise SystemExit(exc.returncode) from exc
