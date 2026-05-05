"""SQLite store tests — schema, CRUD, ordering, cascades."""
from __future__ import annotations

import time

import pytest

from rewind import storage
from rewind.types import ProviderCall


def _call(trace_step: int) -> ProviderCall:
    return ProviderCall(
        step=trace_step,
        timestamp=time.time(),
        provider="custom",
        model="m",
        messages=[{"role": "user", "content": f"step {trace_step}"}],
        response_text=f"response-{trace_step}",
        input_tokens=trace_step + 1,
        output_tokens=1,
        cost_usd=0.001 * trace_step,
        latency_ms=10.0 * trace_step,
    )


def test_init_db_creates_tables(tmp_path):
    db = tmp_path / "init.sqlite"
    storage.init_db(db)
    storage.init_db(db)
    assert db.exists()


def test_insert_and_list_traces_ordered_recent_first(tmp_path):
    db = tmp_path / "list.sqlite"
    storage.insert_trace("older", "2026-01-01T00:00:00+00:00", db_path=db)
    storage.insert_trace("newer", "2026-05-01T00:00:00+00:00", db_path=db)
    rows = storage.list_traces(db_path=db)
    assert [r["name"] for r in rows] == ["newer", "older"]


def test_get_calls_returns_step_order(tmp_path):
    db = tmp_path / "order.sqlite"
    storage.insert_trace("ord", "2026-05-05T00:00:00+00:00", db_path=db)
    for s in [2, 0, 1]:
        storage.append_call("ord", _call(s), db_path=db)
    calls = storage.get_calls("ord", db_path=db)
    assert [c.step for c in calls] == [0, 1, 2]


def test_get_trace_returns_none_when_missing(tmp_path):
    db = tmp_path / "missing.sqlite"
    storage.init_db(db)
    assert storage.get_trace("nope", db_path=db) is None


def test_delete_trace_cascades_to_calls(tmp_path):
    db = tmp_path / "cascade.sqlite"
    storage.insert_trace("c", "2026-05-05T00:00:00+00:00", db_path=db)
    for s in range(3):
        storage.append_call("c", _call(s), db_path=db)
    n = storage.delete_trace("c", db_path=db)
    assert n == 1
    assert storage.get_calls("c", db_path=db) == []
    assert storage.get_trace("c", db_path=db) is None


def test_next_step_is_monotonic(tmp_path):
    db = tmp_path / "step.sqlite"
    storage.insert_trace("s", "2026-05-05T00:00:00+00:00", db_path=db)
    assert storage.next_step("s", db_path=db) == 0
    storage.append_call("s", _call(0), db_path=db)
    assert storage.next_step("s", db_path=db) == 1
    storage.append_call("s", _call(7), db_path=db)
    assert storage.next_step("s", db_path=db) == 8


def test_append_call_replaces_on_duplicate_step(tmp_path):
    db = tmp_path / "dup.sqlite"
    storage.insert_trace("d", "2026-05-05T00:00:00+00:00", db_path=db)
    storage.append_call("d", _call(0), db_path=db)
    replacement = ProviderCall(
        step=0, timestamp=time.time(), provider="custom", model="m",
        messages=[{"role": "user", "content": "replaced"}],
        response_text="REPLACED", input_tokens=99, output_tokens=99, latency_ms=0,
    )
    storage.append_call("d", replacement, db_path=db)
    calls = storage.get_calls("d", db_path=db)
    assert len(calls) == 1
    assert calls[0].response_text == "REPLACED"


@pytest.mark.parametrize("messages", [
    [{"role": "user", "content": "plain"}],
    [{"role": "user", "content": [{"type": "text", "text": "structured"}]}],
    [{"role": "system", "content": "sys"}, {"role": "user", "content": "u"}],
])
def test_messages_roundtrip(tmp_path, messages):
    db = tmp_path / "rt.sqlite"
    storage.insert_trace("rt", "2026-05-05T00:00:00+00:00", db_path=db)
    call = ProviderCall(
        step=0, timestamp=time.time(), provider="custom", model="m",
        messages=messages, response_text="r", input_tokens=1, output_tokens=1,
    )
    storage.append_call("rt", call, db_path=db)
    got = storage.get_calls("rt", db_path=db)[0]
    assert got.messages == messages
