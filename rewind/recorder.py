"""The Recorder context manager — the main API surface."""
from __future__ import annotations

import os
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Iterator

from rewind import storage
from rewind.types import ProviderCall


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Recorder:
    """Active recording session. Hand it ProviderCalls; it persists them."""

    def __init__(self, name: str, db_path: str | os.PathLike[str] | None = None):
        self.name = name
        self.db_path = db_path
        self._lock = threading.Lock()
        self._step = 0
        self._installed: list = []

    def log_call(self, call: ProviderCall) -> ProviderCall:
        """Persist a call. If `call.step < 0`, auto-assign the next step."""
        with self._lock:
            if call.step < 0:
                call = ProviderCall(
                    step=self._step,
                    timestamp=call.timestamp,
                    provider=call.provider,
                    model=call.model,
                    messages=call.messages,
                    response_text=call.response_text,
                    input_tokens=call.input_tokens,
                    output_tokens=call.output_tokens,
                    cached_tokens=call.cached_tokens,
                    cost_usd=call.cost_usd,
                    latency_ms=call.latency_ms,
                    metadata=call.metadata,
                )
            self._step = max(self._step, call.step + 1)
            storage.append_call(self.name, call, db_path=self.db_path)
            return call

    def _start(self) -> None:
        storage.insert_trace(self.name, _utcnow_iso(), db_path=self.db_path)
        self._step = storage.next_step(self.name, db_path=self.db_path)
        self._install_integrations()

    def _stop(self) -> None:
        for integ in self._installed:
            try:
                integ.uninstall()
            except Exception:
                pass
        self._installed.clear()
        storage.finalize_trace(self.name, _utcnow_iso(), db_path=self.db_path)

    def _install_integrations(self) -> None:
        from rewind.integrations import anthropic as a_int
        from rewind.integrations import ollama as ol_int
        from rewind.integrations import openai as o_int

        for module in (a_int, o_int, ol_int):
            try:
                if module.install(self):
                    self._installed.append(module)
            except Exception:
                continue


@contextmanager
def record(name: str,
           db_path: str | os.PathLike[str] | None = None) -> Iterator[Recorder]:
    """Context manager — the primary entry point for users."""
    if not name or not isinstance(name, str):
        raise ValueError("rewind.record(name): name must be a non-empty string")
    rec = Recorder(name, db_path=db_path)
    rec._start()
    try:
        yield rec
    finally:
        rec._stop()
