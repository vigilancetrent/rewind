"""Interactive Rich-based scrubber."""
from __future__ import annotations

import json
import sys
from typing import Iterable

from rich.console import Console, Group
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.text import Text

from rewind.types import ProviderCall, Trace


def _read_key() -> str:
    """Block on a single keypress."""
    if sys.platform == "win32":
        import msvcrt  # type: ignore
        ch = msvcrt.getwch()
        if ch in ("\x00", "\xe0"):
            ch2 = msvcrt.getwch()
            return {
                "H": "up", "P": "down", "K": "left", "M": "right",
                "G": "home", "O": "end", "I": "pgup", "Q": "pgdn",
            }.get(ch2, "")
        if ch in ("\r", "\n"):
            return "enter"
        return ch.lower()

    import termios
    import tty
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        ch = sys.stdin.read(1)
        if ch == "\x1b":
            ch += sys.stdin.read(2)
            return {
                "\x1b[A": "up", "\x1b[B": "down",
                "\x1b[D": "left", "\x1b[C": "right",
                "\x1b[H": "home", "\x1b[F": "end",
                "\x1b[5": "pgup", "\x1b[6": "pgdn",
            }.get(ch, "")
        if ch in ("\r", "\n"):
            return "enter"
        return ch.lower()
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def _render_step_list(calls: Iterable[ProviderCall], cursor: int) -> Panel:
    lines: list[Text] = []
    for c in calls:
        marker = "[bold yellow]>[/]" if c.step == cursor else " "
        latency = f"{c.latency_ms:>5.0f}"
        line = Text.from_markup(
            f"{marker} {c.step:>3}  [cyan]{c.model[:18]:<18}[/]  {latency} ms  "
            f"[green]${(c.cost_usd or 0):.4f}[/]"
        )
        if c.step == cursor:
            line.stylize("on grey15")
        lines.append(line)
    body = Group(*lines) if lines else Text("(no calls yet)", style="dim")
    return Panel(body, title="STEPS", border_style="cyan", padding=(0, 1))


def _render_detail(call: ProviderCall | None, total: int) -> Panel:
    if call is None:
        return Panel(Text("(empty trace)", style="dim"), title="DETAIL", border_style="magenta")

    meta = Text()
    meta.append(f"step:      ", style="dim"); meta.append(f"{call.step} of {total - 1}\n")
    meta.append(f"provider:  ", style="dim"); meta.append(f"{call.provider}\n", style="magenta")
    meta.append(f"model:     ", style="dim"); meta.append(f"{call.model}\n", style="cyan")
    meta.append(f"tokens:    ", style="dim")
    meta.append(f"input={call.input_tokens:,}  output={call.output_tokens:,}")
    if call.cached_tokens:
        meta.append(f"  cached={call.cached_tokens:,}")
    meta.append("\n")
    meta.append(f"cost:      ", style="dim")
    meta.append(f"${(call.cost_usd or 0):.4f}", style="green")
    meta.append(f"   latency: {call.latency_ms:.0f} ms\n")

    msgs = Text("\nmessages:\n", style="bold")
    for m in call.messages:
        role = m.get("role", "?") if isinstance(m, dict) else "?"
        content = m.get("content", "") if isinstance(m, dict) else str(m)
        if isinstance(content, list):
            content = " ".join(
                (b.get("text", "") if isinstance(b, dict) else str(b)) for b in content
            )
        snippet = str(content).strip().replace("\n", " ")
        if len(snippet) > 200:
            snippet = snippet[:199] + "…"
        msgs.append(f"  [{role}] ", style="yellow")
        msgs.append(f"{snippet}\n")

    resp = Text("\nresponse:\n", style="bold")
    body = call.response_text.strip()
    if len(body) > 1500:
        body = body[:1499] + "…"
    resp.append(body or "(empty)")

    return Panel(Group(meta, msgs, resp), title=f"STEP {call.step}", border_style="magenta")


def _render_status(trace: Trace, cursor: int) -> Panel:
    msg = Text()
    msg.append("q ", style="bold yellow"); msg.append("quit  ")
    msg.append("e ", style="bold yellow"); msg.append("export  ")
    msg.append("r ", style="bold yellow"); msg.append("replay from here  ")
    msg.append("↑/↓ ", style="bold yellow"); msg.append("scrub   ")
    msg.append(f"   total cost: ", style="dim")
    msg.append(f"${trace.total_cost():.4f}", style="green")
    msg.append(f"   trace: ", style="dim")
    msg.append(trace.name, style="cyan")
    return Panel(msg, border_style="dim")


def _build_layout(trace: Trace, cursor: int) -> Layout:
    layout = Layout()
    layout.split_column(
        Layout(name="main", ratio=1),
        Layout(name="status", size=3),
    )
    layout["main"].split_row(
        Layout(name="steps", ratio=1),
        Layout(name="detail", ratio=2),
    )
    layout["steps"].update(_render_step_list(trace.calls, cursor))
    current = next((c for c in trace.calls if c.step == cursor), None)
    layout["detail"].update(_render_detail(current, len(trace.calls)))
    layout["status"].update(_render_status(trace, cursor))
    return layout


def scrub(trace: Trace, console: Console | None = None) -> dict:
    """Run the interactive scrubber."""
    console = console or Console()
    if not trace.calls:
        console.print(f"[yellow]Trace {trace.name!r} has no calls to scrub.[/]")
        return {"action": "quit"}

    steps = [c.step for c in trace.calls]
    idx = 0

    with Live(_build_layout(trace, steps[idx]), console=console,
              screen=True, refresh_per_second=20) as live:
        while True:
            try:
                key = _read_key()
            except (KeyboardInterrupt, EOFError):
                return {"action": "quit"}

            if key in ("q", "\x03"):
                return {"action": "quit"}
            if key == "up":
                idx = max(0, idx - 1)
            elif key == "down":
                idx = min(len(steps) - 1, idx + 1)
            elif key == "home":
                idx = 0
            elif key == "end":
                idx = len(steps) - 1
            elif key == "pgup":
                idx = max(0, idx - 10)
            elif key == "pgdn":
                idx = min(len(steps) - 1, idx + 10)
            elif key == "e":
                current = trace.calls[idx]
                return {"action": "export", "step": current.step,
                        "payload": json.dumps(current.to_row())}
            elif key == "r":
                return {"action": "replay", "from_step": steps[idx]}
            else:
                pass

            live.update(_build_layout(trace, steps[idx]))
