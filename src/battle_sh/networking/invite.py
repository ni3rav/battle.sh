"""Pasteable Match Invites as short hyphenated word phrases."""

from __future__ import annotations

import secrets

# Combined vocabulary: NATO phonetic + Breaking Bad + Marvel (single tokens).
_WORDS: tuple[str, ...] = (
    # Phonetic alphabet
    "alpha",
    "bravo",
    "charlie",
    "delta",
    "echo",
    "foxtrot",
    "golf",
    "hotel",
    "india",
    "juliet",
    "kilo",
    "lima",
    "mike",
    "november",
    "oscar",
    "papa",
    "quebec",
    "romeo",
    "sierra",
    "tango",
    "uniform",
    "victor",
    "whiskey",
    "xray",
    "yankee",
    "zulu",
    # Breaking Bad
    "walter",
    "jesse",
    "skyler",
    "hank",
    "marie",
    "saul",
    "gus",
    "todd",
    "lydia",
    "jane",
    "gale",
    "tuco",
    "hector",
    "badger",
    "skinny",
    "huell",
    "kim",
    "nacho",
    "chuck",
    "lalo",
    # Marvel
    "ironman",
    "spiderman",
    "thor",
    "hulk",
    "wolverine",
    "storm",
    "blackwidow",
    "captain",
    "strange",
    "vision",
    "wanda",
    "falcon",
    "hawkeye",
    "groot",
    "rocket",
    "gamora",
    "starlord",
    "panther",
    "antman",
    "wasp",
    "daredevil",
    "punisher",
    "deadpool",
    "magneto",
    "mystique",
    "cyclops",
    "colossus",
    "nightcrawler",
    "loki",
    "thanos",
)

_WORD_COUNT = 4


def mint_invite() -> str:
    """Return a 4-word Invite like ``alpha-tango-jesse-ironman``."""
    return "-".join(secrets.choice(_WORDS) for _ in range(_WORD_COUNT))


def normalize_invite(raw: str) -> str:
    """Trim and lowercase so Guest paste is forgiving."""
    return raw.strip().lower()
