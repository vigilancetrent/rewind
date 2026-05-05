"""`rewind` command-line entry point."""
from __future__ import annotations

import argparse
import json
import sys
from html import escape

from rich.console import Console

from rewind import storage
from rewind.replay import replay as do_replay
from rewind.types import Trace
from rewind.ui.scrub import scrub
from rewind.ui.summary import print_summary, print_trace_list


def _cmd_list(args: argparse.Namespace, console: Console) -> int:
    rows = storage.list_traces(db_path=args.db)
    print_trace_list(rows, console=console)
    return 0


def _cmd_summary(args: argparse.Namespace, console: Console) -> int:
    trace = storage.get_trace(args.name, db_path=args.db)
    if trace is None:
        console.print(f"[red]No trace named {args.name!r}[/red]")
        return 1
    print_summary(trace, console=console)
    return 0


def _cmd_scrub(args: argparse.Namespace, console: Console) -> int:
    trace = storage.get_trace(args.name, db_path=args.db)
    if trace is None:
        console.print(f"[red]No trace named {args.name!r}[/red]")
        return 1
    result = scrub(trace, console=console)
    action = result.get("action")
    if action == "export":
        sys.stdout.write(result["payload"] + "\n")
    elif action == "replay":
        from_step = int(result["from_step"])
        console.print(f"[cyan]Replaying from step {from_step}…[/cyan]")
        try:
            new_trace = do_replay(args.name, from_step=from_step, db_path=args.db)
        except RuntimeError as e:
            console.print(f"[red]Replay failed:[/red] {e}")
            return 2
        console.print(f"[green]Replay complete → {new_trace.name}[/green]")
    return 0


def _cmd_replay(args: argparse.Namespace, console: Console) -> int:
    try:
        new_trace = do_replay(
            args.name,
            from_step=args.from_step,
            model_override=args.model,
            provider_override=args.provider,
            db_path=args.db,
        )
    except KeyError as e:
        console.print(f"[red]{e}[/red]")
        return 1
    except RuntimeError as e:
        console.print(f"[red]Replay failed:[/red] {e}")
        return 2
    console.print(f"[green]Replay complete → {new_trace.name}[/green]")
    print_summary(new_trace, console=console)
    return 0


def _cmd_delete(args: argparse.Namespace, console: Console) -> int:
    n = storage.delete_trace(args.name, db_path=args.db)
    if n == 0:
        console.print(f"[yellow]No trace named {args.name!r}[/yellow]")
        return 1
    console.print(f"[green]Deleted {args.name}[/green]")
    return 0


def _export_jsonl(trace: Trace) -> str:
    lines = [json.dumps({
        "trace": trace.name, "started": trace.started_at, "ended": trace.ended_at,
    })]
    for c in trace.calls:
        lines.append(json.dumps({
            "step": c.step, "timestamp": c.timestamp, "provider": c.provider,
            "model": c.model, "messages": c.messages, "response": c.response_text,
            "input_tokens": c.input_tokens, "output_tokens": c.output_tokens,
            "cached_tokens": c.cached_tokens, "cost_usd": c.cost_usd,
            "latency_ms": c.latency_ms, "metadata": c.metadata,
        }, default=str))
    return "\n".join(lines)


def _export_md(trace: Trace) -> str:
    out = [f"# rewind trace: `{trace.name}`", ""]
    out.append(f"- started: {trace.started_at}")
    out.append(f"- ended: {trace.ended_at}")
    out.append(f"- calls: {len(trace.calls)}")
    out.append(f"- total cost: ${trace.total_cost():.4f}")
    out.append("")
    for c in trace.calls:
        out.append(f"## Step {c.step} — `{c.provider}/{c.model}`")
        out.append(f"- tokens: in={c.input_tokens} out={c.output_tokens}  "
                   f"cost=${(c.cost_usd or 0):.4f}  latency={c.latency_ms:.0f} ms")
        out.append("")
        out.append("**Messages:**")
        out.append("```json")
        out.append(json.dumps(c.messages, indent=2, default=str))
        out.append("```")
        out.append("")
        out.append("**Response:**")
        out.append("")
        out.append(c.response_text or "_(empty)_")
        out.append("")
    return "\n".join(out)


def _export_html(trace: Trace) -> str:
    rows = []
    for c in trace.calls:
        rows.append(
            f"<tr><td>{c.step}</td><td>{escape(c.provider)}</td>"
            f"<td>{escape(c.model)}</td><td>{c.input_tokens}</td>"
            f"<td>{c.output_tokens}</td><td>${(c.cost_usd or 0):.4f}</td>"
            f"<td>{c.latency_ms:.0f} ms</td>"
            f"<td><pre>{escape(c.short_response(160))}</pre></td></tr>"
        )
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>rewind: {escape(trace.name)}</title>
<style>
body{{font-family:Inter,system-ui,sans-serif;max-width:1100px;margin:2rem auto;padding:0 1rem;color:#222}}
h1{{font-weight:600}}
table{{border-collapse:collapse;width:100%;font-size:14px}}
th,td{{border-bottom:1px solid #eee;padding:.5rem .75rem;text-align:left;vertical-align:top}}
th{{background:#fafafa}}
pre{{margin:0;white-space:pre-wrap;font-family:ui-monospace,SFMono-Regular,monospace;font-size:13px}}
</style></head><body>
<h1>rewind: {escape(trace.name)}</h1>
<p>{len(trace.calls)} calls · ${trace.total_cost():.4f} · started {escape(trace.started_at)}</p>
<table><thead><tr><th>#</th><th>provider</th><th>model</th><th>in</th><th>out</th>
<th>cost</th><th>latency</th><th>response</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table>
</body></html>
"""


def _cmd_export(args: argparse.Namespace, console: Console) -> int:
    trace = storage.get_trace(args.name, db_path=args.db)
    if trace is None:
        console.print(f"[red]No trace named {args.name!r}[/red]")
        return 1
    fmt = args.format.lower()
    if fmt == "jsonl":
        sys.stdout.write(_export_jsonl(trace) + "\n")
    elif fmt == "md":
        sys.stdout.write(_export_md(trace) + "\n")
    elif fmt == "html":
        sys.stdout.write(_export_html(trace))
    else:
        console.print(f"[red]Unknown format {fmt!r}[/red]")
        return 1
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="rewind",
        description="Chrome DevTools for AI agents — record, scrub, replay.",
    )
    p.add_argument("--db", default=None, help="path to SQLite store (default ~/.rewind/traces.sqlite)")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="list all recorded traces")

    sp = sub.add_parser("summary", help="print a static table for one trace")
    sp.add_argument("name")

    sp = sub.add_parser("scrub", help="interactive scrubber TUI")
    sp.add_argument("name")

    sp = sub.add_parser("replay", help="re-run a trace, optionally with a different model")
    sp.add_argument("name")
    sp.add_argument("--from-step", type=int, default=0, dest="from_step")
    sp.add_argument("--model", default=None)
    sp.add_argument("--provider", default=None, choices=[None, "anthropic", "openai", "ollama"])

    sp = sub.add_parser("export", help="export a trace as jsonl, md, or html")
    sp.add_argument("name")
    sp.add_argument("--format", default="jsonl", choices=["jsonl", "md", "html"])

    sp = sub.add_parser("delete", help="delete one trace and all its calls")
    sp.add_argument("name")
    return p


_DISPATCH = {
    "list": _cmd_list,
    "summary": _cmd_summary,
    "scrub": _cmd_scrub,
    "replay": _cmd_replay,
    "export": _cmd_export,
    "delete": _cmd_delete,
}


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    console = Console()
    return _DISPATCH[args.cmd](args, console)


if __name__ == "__main__":
    raise SystemExit(main())
