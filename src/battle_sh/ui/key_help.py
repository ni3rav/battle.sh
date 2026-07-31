"""Kbd-styled shortcut tables for sidebar / lobby chrome."""

from __future__ import annotations

from rich.console import Group, RenderableType
from rich.table import Table
from rich.text import Text

# (keys_display, action) — keys shown without backticks, kbd-styled.
PLACEMENT_KEYS: tuple[tuple[str, str], ...] = (
    ("1-5", "select ship"),
    ("tab / shift+tab", "cycle"),
    ("w a s d / arrows", "move"),
    ("e / r", "flip H↔V"),
    ("t", "new random"),
    ("y", "lock"),
    ("Ctrl+C", "quit"),
)

AIM_KEYS: tuple[tuple[str, str], ...] = (
    ("w a s d / arrows", "move"),
    ("f / Enter / Space", "fire"),
    ("Ctrl+C", "quit"),
)

WAIT_KEYS: tuple[tuple[str, str], ...] = (("Ctrl+C", "quit"),)

OPENING_KEYS: tuple[tuple[str, str], ...] = (
    ("Enter", "select"),
    ("↑ ↓", "move"),
    ("Ctrl+C", "quit"),
)

LOBBY_KEYS: tuple[tuple[str, str], ...] = (
    ("Enter", "select"),
    ("Esc", "back"),
    ("Ctrl+C", "quit"),
)

JOIN_KEYS: tuple[tuple[str, str], ...] = (
    ("Enter", "join / select"),
    ("Esc", "back"),
    ("Ctrl+C", "quit"),
)

MATCH_END_KEYS: tuple[tuple[str, str], ...] = (
    ("Enter", "select"),
    ("Ctrl+C", "quit"),
)

THEME_KEYS: tuple[tuple[str, str], ...] = (
    ("↑ ↓", "browse"),
    ("Enter", "apply"),
    ("Esc", "back"),
    ("Ctrl+C", "quit"),
)


def _kbd(label: str) -> Text:
    """Render a key chord like an HTML <kbd> chip (no backticks)."""
    return Text.assemble(
        Text(" "),
        Text(f" {label} ", style="bold reverse"),
        Text(" "),
    )


def keys_table_renderable(
    rows: tuple[tuple[str, str], ...], *, title: str
) -> RenderableType:
    """Two-column kbd → action table for the sidebar / lobby."""
    table = Table(
        title=title,
        show_header=False,
        box=None,
        pad_edge=False,
        padding=(0, 1),
        expand=True,
    )
    table.add_column("key", justify="left", no_wrap=True)
    table.add_column("action", justify="left")
    for keys, action in rows:
        table.add_row(_kbd(keys), Text(f"→ {action}"))
    return table


def keys_plain_text(rows: tuple[tuple[str, str], ...]) -> str:
    """Plain export for tests (arrows preserved, no backticks)."""
    return "\n".join(f"{keys} → {action}" for keys, action in rows)


def stacked_sidebar(
    *sections: RenderableType,
) -> RenderableType:
    parts: list[RenderableType] = []
    for i, section in enumerate(sections):
        if i:
            parts.append(Text("─" * 40, style="dim"))
        parts.append(section)
    return Group(*parts)
