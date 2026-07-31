"""Ship-progress Rich tables for the Combat sidebar."""

from __future__ import annotations

from rich.table import Table
from rich.text import Text

from battle_sh.ui.ship_progress import ShipRow


def ship_table_renderable(
    rows: tuple[ShipRow, ...], *, title: str
) -> Table:
    """Ship · Progress · Status table."""
    table = Table(
        title=title,
        show_header=True,
        box=None,
        pad_edge=False,
        padding=(0, 1),
        expand=True,
    )
    table.add_column("Ship", justify="left", no_wrap=True)
    table.add_column("Progress", justify="right", no_wrap=True)
    table.add_column("Status", justify="left", no_wrap=True)
    for name, progress, status in rows:
        if status == "sunk":
            status_cell = Text(status, style="bold red")
        elif status == "afloat":
            status_cell = Text(status, style="bold green")
        else:
            status_cell = Text(status, style="dim")
        table.add_row(name, progress, status_cell)
    return table
