"""Tear down a provisioned battle.sh Relay stack on an SSH-able Linux host."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

DEFAULT_INSTALL_DIR = "/opt/battle-sh"
UNIT_NAME = "battle-sh-relay.service"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Deprovision the battle.sh Relay stack (stop/disable Relay + Caddy "
            "units, remove install dir and unit). Leaves the Caddy OS package installed."
        )
    )
    parser.add_argument(
        "--host",
        required=True,
        help="SSH target previously provisioned",
    )
    parser.add_argument(
        "--install-dir",
        default=DEFAULT_INSTALL_DIR,
        help=f"Remote install directory (default: {DEFAULT_INSTALL_DIR})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print planned steps; do not SSH",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="With --dry-run, also write plan.txt here",
    )
    parser.add_argument(
        "--ssh-option",
        action="append",
        default=[],
        help="Extra ssh -o OPTION (repeatable)",
    )
    return parser


def deprovision_plan(install_dir: str) -> str:
    return "\n".join(
        [
            f"systemctl stop {UNIT_NAME}",
            f"systemctl disable {UNIT_NAME}",
            "systemctl stop caddy",
            "systemctl disable caddy",
            f"rm -f /etc/systemd/system/{UNIT_NAME}",
            "rm -f /etc/caddy/Caddyfile",
            "systemctl daemon-reload",
            f"rm -rf {install_dir}",
        ]
    )


def _ssh(host: str, remote_cmd: str, ssh_options: list[str]) -> None:
    cmd = ["ssh"]
    for opt in ssh_options:
        cmd.extend(["-o", opt])
    cmd.extend([host, remote_cmd])
    subprocess.run(cmd, check=True)


def deprovision_remote(
    *, host: str, install_dir: str, ssh_options: list[str]
) -> None:
    remote = f"""
set -euo pipefail
systemctl stop {UNIT_NAME} || true
systemctl disable {UNIT_NAME} || true
systemctl stop caddy || true
systemctl disable caddy || true
rm -f /etc/systemd/system/{UNIT_NAME}
rm -f /etc/caddy/Caddyfile
systemctl daemon-reload
rm -rf {install_dir}
"""
    _ssh(host, remote, ssh_options)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    plan = deprovision_plan(args.install_dir)

    if args.dry_run:
        print(plan)
        if args.output_dir is not None:
            args.output_dir.mkdir(parents=True, exist_ok=True)
            (args.output_dir / "plan.txt").write_text(plan + "\n")
        return 0

    deprovision_remote(
        host=args.host,
        install_dir=args.install_dir,
        ssh_options=args.ssh_option,
    )
    print(f"Deprovisioned Relay stack on {args.host}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except subprocess.CalledProcessError as exc:
        print(f"deprovision failed: {exc}", file=sys.stderr)
        raise SystemExit(exc.returncode) from exc
