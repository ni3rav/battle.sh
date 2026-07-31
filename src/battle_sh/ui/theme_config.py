"""Persist and load the player's Textual theme choice."""

from __future__ import annotations

import os
import tomllib
from pathlib import Path

DEFAULT_THEME = "textual-dark"


def config_path() -> Path:
    """XDG config path for battle-sh (`$XDG_CONFIG_HOME/battle-sh/config.toml`)."""
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg) if xdg else Path.home() / ".config"
    return base / "battle-sh" / "config.toml"


def load_theme_name(*, path: Path | None = None) -> str:
    """Return the saved theme name, or the default when missing/invalid."""
    cfg = path if path is not None else config_path()
    try:
        raw = cfg.read_bytes()
    except OSError:
        return DEFAULT_THEME
    try:
        data = tomllib.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError):
        return DEFAULT_THEME
    theme = data.get("theme")
    if isinstance(theme, str) and theme.strip():
        return theme.strip()
    return DEFAULT_THEME


def save_theme_name(theme: str, *, path: Path | None = None) -> None:
    """Write the theme name to the config file, creating parent dirs as needed."""
    cfg = path if path is not None else config_path()
    cfg.parent.mkdir(parents=True, exist_ok=True)
    # Minimal TOML — avoid a write dependency; theme names are simple tokens.
    safe = theme.replace("\\", "\\\\").replace('"', '\\"')
    cfg.write_text(f'theme = "{safe}"\n', encoding="utf-8")
