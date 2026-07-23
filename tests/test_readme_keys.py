"""Docs seam: key map, three-band Live UI, Match time, and Host/Guest smoke."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
README = REPO_ROOT / "README.md"


def test_readme_documents_key_map_layout_match_time_and_ctrl_c() -> None:
    text = README.read_text().lower()
    assert "w/a/s/d" in text or "wasd" in text
    assert "tab" in text
    assert "`y`" in text or "press `y`" in text or "y` to lock" in text
    assert "fire" in text
    assert "ctrl+c" in text
    assert "three-band" in text or "three band" in text
    assert "match time" in text
    assert "smoke" in text
    assert "host" in text and "guest" in text
