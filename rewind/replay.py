"""Replay a recorded trace — optionally with a different model or provider."""
from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from typing import Callable

from rewind import storage
from rewind.types import ProviderCall, Trace, estimate_cost_usd

ProviderFn = Callable[[str, list[dict]], tuple[str, int, int]]


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _dispatch_anthropic(model: str, messages: list[dict]) -> tuple[str, int, int]:
    import anthropic  # type: ignore
    client = anthropic.Anthropic()
    resp = client.messages.create(model=model, max_tokens=1024, messages=messages)
    text = "\n".join(getattr(b, "text", "") for b in (resp.content or []) if getattr(b, "type", "") == "text")
    usage = getattr(resp, "usage", None)
    return text, int(getattr(usage, "input_tokens", 0) or 0), int(getattr(usage, "output_tokens", 0) or 0)


def _dispatch_openai(model: str, messages: list[dict]) -> tuple[str, int, int]:
    import openai  # type: ignore
    client = openai.OpenAI()
    resp = client.chat.completions.create(model=model, messages=messages)
    text = resp.choices[0].message.content or ""
    usage = getattr(resp, "usage", None)
    return text, int(getattr(usage, "prompt_tokens", 0) or 0), int(getattr(usage, "completion_tokens", 0) or 0)


def _dispatch_ollama(model: str, messages: list[dict]) -> tuple[str, int, int]:
    import ollama  # type: ignore
    resp = ollama.chat(model=model, messages=messages)
    text = (resp.get("message") or {}).get("content", "") if isinstance(resp, dict) else ""
    inp = int(resp.get("prompt_eval_count", 0)) if isinstance(resp, dict) else 0
    out = int(resp.get("eval_count", 0)) if isinstance(resp, dict) else 0
    return text, inp, out


_BUILTIN_DISPATCHERS: dict[str, ProviderFn] = {
    "anthropic": _dispatch_anthropic,
    "openai": _dispatch_openai,
    "ollama": _dispatch_ollama,
}


def replay(
    trace_name: str,
    from_step: int = 0,
    model_override: str | None = None,
    provider_override: str | None = None,
    db_path: str | os.PathLike[str] | None = None,
    new_trace_name: str | None = None,
    dispatchers: dict[str, ProviderFn] | None = None,
) -> Trace:
    """Replay `trace_name` from `from_step` onward, optionally swapping model/provider."""
    original = storage.get_trace(trace_name, db_path=db_path)
    if original is None:
        raise KeyError(f"No trace named {trace_name!r}")
    if from_step < 0:
        raise ValueError("from_step must be >= 0")

    dispatchers = {**_BUILTIN_DISPATCHERS, **(dispatchers or {})}

    new_name = new_trace_name or f"{trace_name}__replay_{int(time.time())}"
    storage.insert_trace(new_name, _utcnow_iso(), db_path=db_path,
                         notes=f"Replay of {trace_name} from step {from_step}")

    new_calls: list[ProviderCall] = []
    for original_call in original.calls:
        if original_call.step < from_step:
            continue

        provider = provider_override or original_call.provider
        model = model_override or original_call.model

        dispatch = dispatchers.get(provider)
        if dispatch is None:
            raise RuntimeError(
                f"No dispatcher available for provider {provider!r}. "
                f"Pass `dispatchers={{'{provider}': fn}}` to rewind.replay()."
            )

        t0 = time.time()
        try:
            text, in_toks, out_toks = dispatch(model, original_call.messages)
            err_meta: dict = {}
        except Exception as e:
            text = f"<REPLAY ERROR: {type(e).__name__}: {e}>"
            in_toks = out_toks = 0
            err_meta = {"replay_error": True, "exception": repr(e)}

        latency_ms = (time.time() - t0) * 1000.0
        new_call = ProviderCall(
            step=original_call.step,
            timestamp=t0,
            provider=provider,
            model=model,
            messages=original_call.messages,
            response_text=text,
            input_tokens=in_toks,
            output_tokens=out_toks,
            cost_usd=estimate_cost_usd(model, in_toks, out_toks),
            latency_ms=latency_ms,
            metadata={
                "replay_of": trace_name,
                "original_model": original_call.model,
                "original_provider": original_call.provider,
                **err_meta,
            },
        )
        storage.append_call(new_name, new_call, db_path=db_path)
        new_calls.append(new_call)

    storage.finalize_trace(new_name, _utcnow_iso(), db_path=db_path)

    return Trace(
        name=new_name,
        started_at=original.started_at,
        ended_at=_utcnow_iso(),
        calls=new_calls,
        notes=f"Replay of {trace_name} from step {from_step}",
    )
