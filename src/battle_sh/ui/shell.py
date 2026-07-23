"""Fixed three-band Match UI shell (top | board+controls | bottom)."""

from __future__ import annotations

from battle_sh.rules.board import ShotResultKind
from battle_sh.rules.placement import Coordinate, Placement
from battle_sh.ui.boards import own_board_renderable, tracking_board_renderable
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

AIM_CONTROLS = """\
[bold]Aim[/]

  [bold]w/a/s/d[/] / arrows move
  [bold]f[/] / Enter / Space fire
  [bold]q[/]              quit
  [bold]Ctrl+C[/]          quit (twice)
"""

WAIT_CONTROLS = """\
[bold]Waiting[/]

  [bold]q[/]              quit
  [bold]Ctrl+C[/]          quit (twice)
"""

_SPINNER = ("|", "/", "-", "\\")


def _three_band(
    *,
    top: RenderableType,
    middle_left: RenderableType,
    middle_right: RenderableType,
    bottom: RenderableType,
    top_size: int = 3,
) -> Layout:
    layout = Layout()
    layout.split_column(
        Layout(Panel(top, title="info", padding=(0, 1)), name="top", size=top_size),
        Layout(name="middle", ratio=1),
        Layout(Panel(bottom, title="status", padding=(0, 1)), name="bottom", size=3),
    )
    layout["middle"].split_row(
        Layout(Panel(middle_left, title="board", padding=(0, 1)), name="board", ratio=3),
        Layout(
            Panel(middle_right, title="controls", padding=(0, 1)),
            name="controls",
            size=28,
        ),
    )
    return layout


def placement_frame(
    *,
    placement: Placement,
    selected: str | None,
    status: str = "",
    top_info: str = "Phase: Placement",
) -> RenderableType:
    """Compose the Placement three-band view (pure; no Live)."""
    board = own_board_renderable(placement, {}, selected=selected)
    selected_line = (
        f"Selected: [bold yellow]{selected}[/]"
        if selected
        else "No ship selected — press [bold]1-5[/] or [bold]tab[/]."
    )
    board_body: RenderableType = Group(board, Text.from_markup(selected_line))
    return _three_band(
        top=Text(top_info),
        middle_left=board_body,
        middle_right=Text.from_markup(PLACEMENT_CONTROLS),
        bottom=Text(status or " "),
    )


def lobby_frame(
    *,
    role: str,
    invite: str,
    status: str = "Waiting for Guest…",
) -> RenderableType:
    """Host lobby: waiting for Guest; Match time has not started."""
    top = Text(f"{role} · Lobby — waiting for Guest (Invite {invite})")
    body = Text(
        "Share the Invite with your opponent.\nMatch time starts when they join."
    )
    return _three_band(
        top=top,
        middle_left=body,
        middle_right=Text.from_markup(WAIT_CONTROLS),
        bottom=Text(status or " "),
    )


def wait_frame(
    *,
    role: str,
    phase: str,
    match_time: str,
    spinner_frame: int = 0,
    status: str = "Waiting…",
    board: RenderableType | None = None,
) -> RenderableType:
    """Wait chrome with Match time and spinner; only quit keys in controls."""
    spin = _SPINNER[spinner_frame % len(_SPINNER)]
    top = Text(f"{role} · {phase} · Match time {match_time}  {spin}")
    middle = board if board is not None else Text("Boards stay visible while you wait.")
    return _three_band(
        top=top,
        middle_left=middle,
        middle_right=Text.from_markup(WAIT_CONTROLS),
        bottom=Text(status or " "),
    )


def combat_frame(
    *,
    role: str,
    match_time: str,
    placement: Placement,
    own_marks: dict[Coordinate, ShotResultKind],
    tracking: dict[Coordinate, ShotResultKind],
    revealed: frozenset[Coordinate],
    aim: Coordinate,
    status: str = "",
) -> RenderableType:
    """Your turn: opponent Board + Aim wide; own Board compact in the top strip."""
    info = Text(f"{role} · Aim · Match time {match_time}")
    own = own_board_renderable(placement, own_marks)
    top: RenderableType = Group(info, Text(""), own)
    return _three_band(
        top=top,
        top_size=16,
        middle_left=tracking_board_renderable(tracking, revealed, aim=aim),
        middle_right=Text.from_markup(AIM_CONTROLS),
        bottom=Text(status or " "),
    )


def combat_wait_frame(
    *,
    role: str,
    match_time: str,
    placement: Placement,
    own_marks: dict[Coordinate, ShotResultKind],
    tracking: dict[Coordinate, ShotResultKind],
    revealed: frozenset[Coordinate],
    spinner_frame: int = 0,
    status: str = "Waiting for opponent…",
) -> RenderableType:
    """Opponent's turn: Aim board wide, own Board in top strip, spinner in status."""
    spin = _SPINNER[spinner_frame % len(_SPINNER)]
    info = Text(f"{role} · Waiting · Match time {match_time}")
    own = own_board_renderable(placement, own_marks)
    top: RenderableType = Group(info, Text(""), own)
    status_line = f"{spin} {status}" if status else spin
    return _three_band(
        top=top,
        top_size=16,
        middle_left=tracking_board_renderable(tracking, revealed),
        middle_right=Text.from_markup(WAIT_CONTROLS),
        bottom=Text(status_line),
    )
