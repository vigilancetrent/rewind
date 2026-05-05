"""Ollama Python client integration — patches the top-level `chat` function."""
from __future__ import annotations

import time
from typing import Any

from rewind.types import ProviderCall

_ORIGINAL: Any = None
_MODULE: Any = None


def _extract_text(response: Any) -> str:
    if isinstance(response, dict):
        msg = response.get("message") or {}
        if isinstance(msg, dict):
            return str(msg.get("content", "") or "")
        return str(response.get("response", "") or "")
    msg = getattr(response, "message", None)
    if msg is not None:
        return str(getattr(msg, "content", "") or "")
    return str(response)[:2000]


def _extract_usage(response: Any) -> tuple[int, int]:
    if isinstance(response, dict):
        return int(response.get("prompt_eval_count", 0) or 0), int(response.get("eval_count", 0) or 0)
    inp = int(getattr(response, "prompt_eval_count", 0) or 0)
    out = int(getattr(response, "eval_count", 0) or 0)
    return inp, out


def install(recorder) -> bool:
    global _ORIGINAL, _MODULE
    try:
        import ollama  # type: ignore
    except Exception:
        return False
    if _ORIGINAL is not None:
        return True

    _MODULE = ollama
    _ORIGINAL = ollama.chat
    original = _ORIGINAL

    def patched(*args, **kwargs):
        t0 = time.time()
        try:
            response = original(*args, **kwargs)
        except Exception:
            try:
                recorder.log_call(ProviderCall(
                    step=-1,
                    timestamp=t0,
                    provider="ollama",
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
        model = str(kwargs.get("model", ""))
        in_toks, out_toks = _extract_usage(response)
        text = _extract_text(response)

        try:
            recorder.log_call(ProviderCall(
                step=-1,
                timestamp=t0,
                provider="ollama",
                model=model,
                messages=list(kwargs.get("messages", [])),
                response_text=text,
                input_tokens=in_toks,
                output_tokens=out_toks,
                cost_usd=0.0,
                latency_ms=latency_ms,
                metadata={"options": kwargs.get("options")},
            ))
        except Exception:
            pass
        return response

    ollama.chat = patched  # type: ignore[assignment]
    return True


def uninstall() -> None:
    global _ORIGINAL, _MODULE
    if _ORIGINAL is not None and _MODULE is not None:
        _MODULE.chat = _ORIGINAL
    _ORIGINAL = None
    _MODULE = None
