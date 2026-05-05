"""OpenAI SDK integration — patches `Completions.create`."""
from __future__ import annotations

import time
from typing import Any

from rewind.types import ProviderCall, estimate_cost_usd

_ORIGINAL: Any = None
_PATCHED_CLASS: Any = None


def _extract_text(response: Any) -> str:
    try:
        choices = getattr(response, "choices", None) or []
        if not choices:
            return ""
        msg = getattr(choices[0], "message", None)
        if msg is None:
            return ""
        text = getattr(msg, "content", None) or ""
        tool_calls = getattr(msg, "tool_calls", None) or []
        if tool_calls:
            names = [getattr(tc.function, "name", "?") for tc in tool_calls]
            text = (text or "") + "\n" + " ".join(f"[tool_use:{n}]" for n in names)
        return text or ""
    except Exception:
        return str(response)[:2000]


def _extract_usage(response: Any) -> tuple[int, int, int]:
    usage = getattr(response, "usage", None)
    if usage is None:
        return 0, 0, 0
    inp = getattr(usage, "prompt_tokens", 0) or 0
    out = getattr(usage, "completion_tokens", 0) or 0
    details = getattr(usage, "prompt_tokens_details", None)
    cached = getattr(details, "cached_tokens", 0) if details else 0
    return int(inp), int(out), int(cached or 0)


def install(recorder) -> bool:
    global _ORIGINAL, _PATCHED_CLASS
    try:
        from openai.resources.chat.completions import Completions  # type: ignore
    except Exception:
        return False
    if _ORIGINAL is not None:
        return True

    _PATCHED_CLASS = Completions
    _ORIGINAL = Completions.create
    original = _ORIGINAL

    def patched(self, *args, **kwargs):
        t0 = time.time()
        try:
            response = original(self, *args, **kwargs)
        except Exception:
            try:
                recorder.log_call(ProviderCall(
                    step=-1,
                    timestamp=t0,
                    provider="openai",
                    model=str(kwargs.get("model", "")),
                    messages=list(kwargs.get("messages", [])),
                    response_text="<EXCEPTION>",
                    input_tokens=0,
                    output_tokens=0,
                    latency_ms=(time.time() - t0) * 1000.0,
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
                provider="openai",
                model=model,
                messages=list(kwargs.get("messages", [])),
                response_text=text,
                input_tokens=in_toks,
                output_tokens=out_toks,
                cached_tokens=cached,
                cost_usd=estimate_cost_usd(model, in_toks, out_toks),
                latency_ms=latency_ms,
                metadata={
                    "temperature": kwargs.get("temperature"),
                    "max_tokens": kwargs.get("max_tokens") or kwargs.get("max_completion_tokens"),
                    "tools": [t.get("function", {}).get("name") if isinstance(t, dict) else None
                              for t in kwargs.get("tools") or []],
                },
            ))
        except Exception:
            pass
        return response

    Completions.create = patched  # type: ignore[assignment]
    return True


def uninstall() -> None:
    global _ORIGINAL, _PATCHED_CLASS
    if _ORIGINAL is not None and _PATCHED_CLASS is not None:
        _PATCHED_CLASS.create = _ORIGINAL
    _ORIGINAL = None
    _PATCHED_CLASS = None
