"""Recorder context-manager tests."""
from __future__ import annotations

import time

import pytest

import rewind
from rewind import storage
from rewind.types import ProviderCall


def _make_call(step: int = -1) -> ProviderCall:
    return ProviderCall(
        step=step,
        timestamp=time.time(),
        provider="custom",
        model="test-model-1",
        messages=[{"role": "user", "content": "hi"}],
        response_text="hello",
        input_tokens=10,
        output_tokens=4,
        latency_ms=42.0,
    )


def test_record_creates_and_finalizes_trace(tmp_path):
    db = tmp_path / "traces.sqlite"
    with rewind.record("run-a", db_path=db) as r:
        r.log_call(_make_call())
    rows = storage.list_traces(db_path=db)
    assert len(rows) == 1
    assert rows[0]["name"] == "run-a"
    assert rows[0]["ended"] is not None
    assert rows[0]["n_calls"] == 1


def test_log_call_inserts_correct_fields(tmp_path):
    db = tmp_path / "traces.sqlite"
    with rewind.record("run-fields", db_path=db) as r:
        r.log_call(_make_call())
    calls = storage.get_calls("run-fields", db_path=db)
    assert len(calls) == 1
    c = calls[0]
    assert c.provider == "custom"
    assert c.model == "test-model-1"
    assert c.input_tokens == 10 and c.output_tokens == 4
    assert c.messages == [{"role": "user", "content": "hi"}]
    assert c.response_text == "hello"


def test_log_call_auto_assigns_steps(tmp_path):
    db = tmp_path / "traces.sqlite"
    with rewind.record("run-steps", db_path=db) as r:
        r.log_call(_make_call(step=-1))
        r.log_call(_make_call(step=-1))
        r.log_call(_make_call(step=-1))
    calls = storage.get_calls("run-steps", db_path=db)
    assert [c.step for c in calls] == [0, 1, 2]


def test_record_rejects_empty_name(tmp_path):
    with pytest.raises(ValueError):
        with rewind.record("", db_path=tmp_path / "x.sqlite"):
            pass


def test_recorder_appends_to_existing_trace(tmp_path):
    db = tmp_path / "traces.sqlite"
    with rewind.record("run-resume", db_path=db) as r:
        r.log_call(_make_call(step=-1))
    with rewind.record("run-resume", db_path=db) as r:
        r.log_call(_make_call(step=-1))
    calls = storage.get_calls("run-resume", db_path=db)
    assert [c.step for c in calls] == [0, 1]


def test_recorder_swallows_integration_failure(tmp_path, monkeypatch):
    """If an integration's install raises, recorder must not crash."""
    from rewind.integrations import anthropic as a_int

    def boom(_recorder):
        raise RuntimeError("simulated SDK breakage")

    monkeypatch.setattr(a_int, "install", boom)
    db = tmp_path / "traces.sqlite"
    with rewind.record("run-broken-int", db_path=db) as r:
        r.log_call(_make_call())
    assert storage.get_trace("run-broken-int", db_path=db) is not None
