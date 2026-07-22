"""Docs seam: DNS prerequisites and local vs hosted Relay URLs."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
README = REPO_ROOT / "README.md"


def test_readme_explains_dns_before_certs_and_local_ws() -> None:
    text = README.read_text().lower()
    assert "dns" in text
    assert "a/aaaa" in text or "aaaa" in text
    assert "ws://" in text
    assert "wss://" in text
    assert "caddy" in text
    assert "provision" in text
    assert "deprovision" in text
    assert "player" in text
