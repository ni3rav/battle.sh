"""Invite phrase minting: 4 hyphenated words."""

from __future__ import annotations

import re

from battle_sh.networking.invite import mint_invite, normalize_invite


def test_mint_invite_is_four_lowercase_hyphenated_words() -> None:
    invite = mint_invite()
    assert re.fullmatch(r"[a-z]+(?:-[a-z]+){3}", invite)
    parts = invite.split("-")
    assert len(parts) == 4
    assert all(part.isalpha() and part.islower() for part in parts)


def test_mint_invite_varies() -> None:
    samples = {mint_invite() for _ in range(40)}
    assert len(samples) >= 2


def test_normalize_invite_trims_and_lowercases() -> None:
    assert normalize_invite("  Alpha-Tango-Jesse-Ironman  ") == "alpha-tango-jesse-ironman"
