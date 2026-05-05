"""Anthropic SDK integration — patches `Messages.create`."""
from __future__ import annotations

import time
from typing import Any

from rewind.types import ProviderCall, estimate_cost_usd

_ORIGINAL: Any = None
_PATCHED_CLASS: Any = None
_PATCH_NAME: str = "create"


def _extract_text(response: Any) -> str:
    """Flatten Anthropic's content-block list into a single string."""
    try:
        blocks = getattr(response, "content", None) or []
        parts: list[str] = []
        for b in blocks:
            t = getattr(b, "type", None) or (b.get("type") if isinstance(b, dict) else None)
            if t == "text":
                parts.append(getattr(b, "text", "") or (b.get("text", "") if isinstance(b, dict) else ""))
            elif t == "tool_use":
                name = getattr(b, "name", None) or (b.get("name") if isinstance(b, dict) else "")
                parts.append(f"[tool_use:{name}]")
        return "\n".join(p for p in parts if p)
    except Exception:
        return str(response)[:2000]


def _extract_usage(response: Any) -> tuple[int, int, int]:
    usage = getattr(response, "usage", None)
    if usage is None:
        return 0, 0, 0
    inp = getattr(usage, "input_tokens", 0) or 0
    out = getattr(usage, "output_tokens", 0) or 0
    cached = getattr(usage, "cache_read_input_tokens", 0) or 0
    return int(inp), int(out), int(cached)


def install(recorder) -> bool:
    """Patch anthropic.resources.messages.Messages.create."""
    global _ORIGINAL, _PATCHED_CLASS
    try:
        from anthropic.resources.messages import Messages  # type: ignore
    except Exception:
        return False
    if _ORIGINAL is not None:
        return True

    _PATCHED_CLASS = Messages
    _ORIGINAL = Messages.create

    original = _ORIGINAL

    def patched(self, *args, **kwargs):
        t0 = time.time()
        try:
            response = original(self, *args, **kwargs)
        except Exception:
            latency = (time.time() - t0) * 1000.0
            try:
                recorder.log_call(ProviderCall(
                    step=-1,
                    timestamp=t0,
                    provider="anthropic",
                    model=str(kwargs.get("model", "")),
                    messages=list(kwargs.get("messages", [])),
                    response_text="<EXCEPTION>",
                    input_tokens=0,
                    output_tokens=0,
                    latency_ms=latency,
                    metadata={"error": True},
                ))
            except Exception:
                pass
            raise

        latency_ms = (time.time() - t0) * 1000.0
        model = str(kwargs.get("model", "") or getattr(response, "model", ""))
        in_toks, out_toks, cached = _extract_usage(response)
        text = _extract_text(response)

        try:
            recorder.log_call(ProviderCall(
                step=-1,
                timestamp=t0,
                provider="anthropic",
                model=model,
                messages=list(kwargs.get("messages", [])),
                response_text=text,
                input_tokens=in_toks,
                output_tokens=out_toks,
                cached_tokens=cached,
                cost_usd=estimate_cost_usd(model, in_toks, out_toks),
                latency_ms=latency_ms,
                metadata={
                    "system": kwargs.get("system"),
                    "max_tokens": kwargs.get("max_tokens"),
                    "tools": [getattr(t, "name", None) or (t.get("name") if isinstance(t, dict) else None)
                              for t in kwargs.get("tools") or []],
                },
            ))
        except Exception:
            pass
        return response

    Messages.create = patched  # type: ignore[assignment]
    return True


def uninstall() -> None:
    global _ORIGINAL, _PATCHED_CLASS
    if _ORIGINAL is not None and _PATCHED_CLASS is not None:
        _PATCHED_CLASS.create = _ORIGINAL
    _ORIGINAL = None
    _PATCHED_CLASS = None
