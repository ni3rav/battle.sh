"""Fixed three-band Match UI shell (top | board+controls | bottom)."""

from __future__ import annotations

from battle_sh.rules.placement import Placement
from battle_sh.ui.boards import own_board_renderable
from rich.console import Group, RenderableType
from rich.layout import Layout
from rich.panel import Panel
from rich.text import Text

PLACEMENT_CONTROLS = """\
[bold]Placement[/]

  [bold]1[/]-[bold]5[/]            select ship
  [bold]tab[/] / [bold]shift+tab[/] cycle
  [bold]w/a/s/d[/] / arrows move
  [bold]e[/] / [bold]r[/]          flip H↔V
  [bold]t[/]              new random
  [bold]y[/]              lock
  [bold]q[/]              quit
"""


def placement_frame(
    *,
    placement: Placement,
    selected: str | None,
    status: str = "",
    top_info: str = "Phase: Placement",
) -> RenderableType:
    """Compose the Placement three-band view (pure; no Live)."""
    layout = Layout()
    layout.split_column(
        Layout(Panel(Text(top_info), title="info", padding=(0, 1)), name="top", size=3),
        Layout(name="middle", ratio=1),
        Layout(
            Panel(Text(status or " "), title="status", padding=(0, 1)),
            name="bottom",
            size=3,
        ),
    )
    board = own_board_renderable(placement, {}, selected=selected)
    selected_line = (
        f"Selected: [bold yellow]{selected}[/]"
        if selected
        else "No ship selected — press [bold]1-5[/] or [bold]tab[/]."
    )
    board_body: RenderableType = Group(board, Text.from_markup(selected_line))
    layout["middle"].split_row(
        Layout(Panel(board_body, title="board", padding=(0, 1)), name="board", ratio=3),
        Layout(
            Panel(Text.from_markup(PLACEMENT_CONTROLS), title="controls", padding=(0, 1)),
            name="controls",
            size=28,
        ),
    )
    return layout
