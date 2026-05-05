"""Replay tests — verify stub dispatchers, model overrides, error capture."""
from __future__ import annotations

import time

import pytest

import rewind
from rewind import storage
from rewind.replay import replay
from rewind.types import ProviderCall


def _seed_trace(db_path, name: str = "src", n: int = 3) -> None:
    with rewind.record(name, db_path=db_path) as r:
        for i in range(n):
            r.log_call(ProviderCall(
                step=-1, timestamp=time.time(),
                provider="anthropic", model="claude-opus-4-7",
                messages=[{"role": "user", "content": f"q{i}"}],
                response_text=f"a{i}", input_tokens=10, output_tokens=2,
                cost_usd=0.01, latency_ms=100.0,
            ))


def test_replay_with_stub_dispatcher(tmp_path):
    db = tmp_path / "r.sqlite"
    _seed_trace(db)

    calls_made: list[tuple[str, list]] = []

    def stub(model, messages):
        calls_made.append((model, messages))
        return ("stub-response", 7, 2)

    new_trace = replay("src", db_path=db, dispatchers={"anthropic": stub})

    assert len(new_trace.calls) == 3
    assert all(c.response_text == "stub-response" for c in new_trace.calls)
    assert all(c.input_tokens == 7 for c in new_trace.calls)
    assert len(calls_made) == 3


def test_replay_from_step_skips_earlier(tmp_path):
    db = tmp_path / "r.sqlite"
    _seed_trace(db, n=5)

    seen_models = []

    def stub(model, messages):
        seen_models.append(messages[0]["content"])
        return ("ok", 1, 1)

    new_trace = replay("src", from_step=2, db_path=db, dispatchers={"anthropic": stub})
    assert len(new_trace.calls) == 3
    assert seen_models == ["q2", "q3", "q4"]
    assert [c.step for c in new_trace.calls] == [2, 3, 4]


def test_replay_with_model_override(tmp_path):
    db = tmp_path / "r.sqlite"
    _seed_trace(db, n=2)
    seen = []

    def stub(model, messages):
        seen.append(model)
        return ("ok", 1, 1)

    new_trace = replay("src", model_override="claude-haiku-4-5",
                       db_path=db, dispatchers={"anthropic": stub})
    assert seen == ["claude-haiku-4-5", "claude-haiku-4-5"]
    assert all(c.model == "claude-haiku-4-5" for c in new_trace.calls)
    assert all(c.metadata["original_model"] == "claude-opus-4-7" for c in new_trace.calls)


def test_replay_missing_trace_raises(tmp_path):
    db = tmp_path / "r.sqlite"
    storage.init_db(db)
    with pytest.raises(KeyError):
        replay("does-not-exist", db_path=db)


def test_replay_missing_dispatcher_raises(tmp_path):
    db = tmp_path / "r.sqlite"
    _seed_trace(db, n=1)
    with pytest.raises(RuntimeError):
        replay("src", db_path=db, dispatchers={})


def test_replay_captures_dispatcher_errors(tmp_path):
    db = tmp_path / "r.sqlite"
    _seed_trace(db, n=2)

    def bad(model, messages):
        raise ValueError("boom")

    new_trace = replay("src", db_path=db, dispatchers={"anthropic": bad})
    assert len(new_trace.calls) == 2
    for c in new_trace.calls:
        assert c.metadata.get("replay_error") is True
        assert "boom" in c.response_text
        assert c.input_tokens == 0


def test_replay_persists_to_db(tmp_path):
    db = tmp_path / "r.sqlite"
    _seed_trace(db, n=2)

    def stub(model, messages):
        return ("ok", 1, 1)

    new_trace = replay("src", db_path=db, dispatchers={"anthropic": stub})
    persisted = storage.get_trace(new_trace.name, db_path=db)
    assert persisted is not None
    assert len(persisted.calls) == 2


def test_replay_negative_from_step_raises(tmp_path):
    db = tmp_path / "r.sqlite"
    _seed_trace(db, n=1)
    with pytest.raises(ValueError):
        replay("src", from_step=-1, db_path=db, dispatchers={"anthropic": lambda m, x: ("", 0, 0)})


def test_summary_handles_empty_trace(tmp_path):
    """The summary printer must not crash on a trace with zero calls."""
    db = tmp_path / "r.sqlite"
    storage.insert_trace("empty", "2026-05-05T00:00:00+00:00", db_path=db)
    trace = storage.get_trace("empty", db_path=db)
    from rewind.ui.summary import print_summary
    print_summary(trace)
