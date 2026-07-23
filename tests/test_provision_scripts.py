"""Provision / deprovision CLI seam: args, dry-run artifacts, no cloud lock-in."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
PROVISION = REPO_ROOT / "scripts" / "provision-relay"
DEPROVISION = REPO_ROOT / "scripts" / "deprovision-relay"


def test_provision_requires_host_domain_and_email() -> None:
    result = subprocess.run(
        [str(PROVISION)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    combined = (result.stdout + result.stderr).lower()
    assert "host" in combined
    assert "domain" in combined
    assert "email" in combined


def test_provision_dry_run_writes_caddy_and_systemd_unit(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            str(PROVISION),
            "--host",
            "root@203.0.113.10",
            "--domain",
            "relay.example.com",
            "--email",
            "ops@example.com",
            "--dry-run",
            "--output-dir",
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    caddy = (tmp_path / "Caddyfile").read_text()
    unit = (tmp_path / "battle-sh-relay.service").read_text()
    assert "relay.example.com" in caddy
    assert "ops@example.com" in caddy
    assert "reverse_proxy 127.0.0.1:8765" in caddy
    assert "WorkingDirectory=/opt/battle-sh" in unit
    assert "battle_sh.networking.relay_cli" in unit


def test_deprovision_requires_host() -> None:
    result = subprocess.run(
        [str(DEPROVISION)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "host" in (result.stdout + result.stderr).lower()


def test_deprovision_dry_run_lists_stop_and_remove_steps(tmp_path: Path) -> None:
    out = tmp_path / "plan.txt"
    result = subprocess.run(
        [
            str(DEPROVISION),
            "--host",
            "root@203.0.113.10",
            "--dry-run",
            "--output-dir",
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    plan = out.read_text() if out.exists() else result.stdout
    lowered = plan.lower()
    assert "systemctl stop" in lowered or "stop" in lowered
    assert "battle-sh-relay" in lowered
    assert "disable" in lowered
    assert "caddy" in lowered


def test_provision_dry_run_tls_internal_writes_internal_directive(
    tmp_path: Path,
) -> None:
    result = subprocess.run(
        [
            str(PROVISION),
            "--host",
            "root@203.0.113.10",
            "--domain",
            "relay.local.test",
            "--email",
            "ops@example.com",
            "--tls-internal",
            "--dry-run",
            "--output-dir",
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "tls internal" in (tmp_path / "Caddyfile").read_text()


def test_no_aws_specific_provision_helpers_ship() -> None:
    scripts = REPO_ROOT / "scripts"
    names = [p.name.lower() for p in scripts.iterdir()] if scripts.is_dir() else []
    assert not any("aws" in name for name in names)
    for path in REPO_ROOT.rglob("*"):
        if ".venv" in path.parts or ".git" in path.parts:
            continue
        if path.is_file() and "aws" in path.name.lower():
            pytest.fail(f"AWS-specific helper shipped: {path}")
