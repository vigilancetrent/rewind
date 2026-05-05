"""Core data types for rewind."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


_DEFAULT_PRICING: dict[str, tuple[float, float]] = {
    "claude-opus-4": (15.00, 75.00),
    "claude-sonnet-4": (3.00, 15.00),
    "claude-haiku-4": (0.80, 4.00),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
    "gpt-4.1": (2.00, 8.00),
    "o1": (15.00, 60.00),
    "o3": (10.00, 40.00),
}


def estimate_cost_usd(model: str, input_tokens: int, output_tokens: int) -> float | None:
    """Best-effort USD cost estimate. Returns None when the model is unknown."""
    if not model:
        return None
    m = model.lower()
    for needle, (in_rate, out_rate) in _DEFAULT_PRICING.items():
        if needle in m:
            return (input_tokens / 1_000_000.0) * in_rate + (output_tokens / 1_000_000.0) * out_rate
    return None


@dataclass(frozen=True)
class ProviderCall:
    """A single LLM provider invocation captured by rewind."""

    step: int
    timestamp: float
    provider: str
    model: str
    messages: list[dict[str, Any]]
    response_text: str
    input_tokens: int
    output_tokens: int
    cached_tokens: int = 0
    cost_usd: float | None = None
    latency_ms: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def short_response(self, n: int = 60) -> str:
        flat = " ".join(self.response_text.split())
        return flat if len(flat) <= n else flat[: n - 1] + "…"

    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def to_row(self) -> dict[str, Any]:
        return {
            "step": self.step,
            "timestamp": self.timestamp,
            "provider": self.provider,
            "model": self.model,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cached_tokens": self.cached_tokens,
            "cost_usd": self.cost_usd,
            "latency_ms": self.latency_ms,
            "response_preview": self.short_response(80),
        }


@dataclass
class Trace:
    """A complete recording of an agent run."""

    name: str
    started_at: str
    ended_at: str | None
    calls: list[ProviderCall]
    notes: str = ""

    def total_cost(self) -> float:
        return sum((c.cost_usd or 0.0) for c in self.calls)

    def total_input_tokens(self) -> int:
        return sum(c.input_tokens for c in self.calls)

    def total_output_tokens(self) -> int:
        return sum(c.output_tokens for c in self.calls)

    def total_latency_ms(self) -> float:
        return sum(c.latency_ms for c in self.calls)

    def __len__(self) -> int:
        return len(self.calls)
