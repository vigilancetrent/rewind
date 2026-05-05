"""Non-interactive summary tables — the `rewind list` and `rewind summary` views."""
from __future__ import annotations

from rich.console import Console
from rich.table import Table

from rewind.types import Trace


def print_summary(trace: Trace, console: Console | None = None) -> None:
    """Single-trace summary table: one row per call."""
    console = console or Console()

    if not trace.calls:
        console.print(f"[yellow]Trace {trace.name!r} has no calls yet.[/yellow]")
        return

    table = Table(
        title=f"rewind: {trace.name}",
        title_style="bold cyan",
        header_style="bold",
        show_lines=False,
    )
    table.add_column("#", justify="right", style="dim")
    table.add_column("provider", style="magenta")
    table.add_column("model", style="cyan")
    table.add_column("in", justify="right")
    table.add_column("out", justify="right")
    table.add_column("$", justify="right", style="green")
    table.add_column("ms", justify="right", style="yellow")
    table.add_column("response", overflow="ellipsis", max_width=60)

    for c in trace.calls:
        table.add_row(
            str(c.step),
            c.provider,
            c.model,
            f"{c.input_tokens:,}",
            f"{c.output_tokens:,}",
            f"{c.cost_usd:.4f}" if c.cost_usd is not None else "-",
            f"{c.latency_ms:.0f}",
            c.short_response(60),
        )

    console.print(table)
    console.print(
        f"[bold]Total:[/bold] {len(trace.calls)} calls   "
        f"[green]${trace.total_cost():.4f}[/green]   "
        f"in={trace.total_input_tokens():,}  out={trace.total_output_tokens():,}  "
        f"latency={trace.total_latency_ms():.0f} ms"
    )


def print_trace_list(rows: list[dict], console: Console | None = None) -> None:
    """The `rewind list` view."""
    console = console or Console()
    if not rows:
        console.print("[dim]No traces yet. Run something inside `rewind.record(...)`.[/dim]")
        return

    table = Table(title="rewind traces", title_style="bold cyan", header_style="bold")
    table.add_column("name", style="cyan")
    table.add_column("started", style="dim")
    table.add_column("calls", justify="right")
    table.add_column("$ total", justify="right", style="green")
    table.add_column("in toks", justify="right")
    table.add_column("out toks", justify="right")
    table.add_column("status", style="magenta")

    for r in rows:
        status = "active" if r["ended"] is None else "done"
        table.add_row(
            r["name"],
            r["started"],
            str(r["n_calls"]),
            f"{(r['total_cost'] or 0.0):.4f}",
            f"{int(r['total_in'] or 0):,}",
            f"{int(r['total_out'] or 0):,}",
            status,
        )
    console.print(table)
