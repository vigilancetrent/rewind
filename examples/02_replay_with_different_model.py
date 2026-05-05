"""Example 2 — replay a recorded trace with a different model."""
from __future__ import annotations

from rewind.replay import replay


def stub_dispatcher(model: str, messages: list[dict]) -> tuple[str, int, int]:
    """Stand-in for a real provider."""
    last_user = next((m["content"] for m in reversed(messages) if m.get("role") == "user"), "")
    return f"[{model}] reply to: {last_user}", len(str(last_user)) // 4, 16


def main() -> None:
    new_trace = replay(
        "demo-run",
        from_step=1,
        model_override="claude-haiku-4-5-20251001",
        dispatchers={"anthropic": stub_dispatcher},
    )
    print(f"Wrote replay trace: {new_trace.name}")
    print(f"Replayed {len(new_trace.calls)} calls with model override.")
    print("Compare with: rewind summary", new_trace.name)


if __name__ == "__main__":
    main()
