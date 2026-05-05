"""Example 1 — record an agent run and scrub through it."""
from __future__ import annotations

import time

import rewind
from rewind.types import ProviderCall


def fake_step(recorder: rewind.Recorder, prompt: str, response: str,
              model: str = "claude-opus-4-7") -> None:
    """Simulate a model call."""
    t0 = time.time()
    time.sleep(0.05)
    recorder.log_call(ProviderCall(
        step=-1,
        timestamp=t0,
        provider="anthropic",
        model=model,
        messages=[{"role": "user", "content": prompt}],
        response_text=response,
        input_tokens=len(prompt) // 4,
        output_tokens=len(response) // 4,
        cost_usd=0.001 * (len(prompt) + len(response)) / 1000,
        latency_ms=(time.time() - t0) * 1000.0,
    ))


def main() -> None:
    with rewind.record("demo-run") as r:
        fake_step(r, "Plan a 3-day Tokyo trip.", "Day 1: Asakusa... Day 2: Shibuya... Day 3: Akihabara...")
        fake_step(r, "Refine: focus on food.", "Day 1: ramen tour... Day 2: izakaya... Day 3: sushi...",
                  model="claude-haiku-4-5")
        fake_step(r, "Add a budget.", "Estimated total: 60,000 yen (~$400)...")
        fake_step(r, "Translate to Japanese.", "1日目: ラーメンツアー...")

    print("Recorded 4 steps to demo-run. Now run:")
    print("  rewind list")
    print("  rewind scrub demo-run")


if __name__ == "__main__":
    main()
