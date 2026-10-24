import pytest
from nexus import Conflict, Engine, Registry, RunSpec, StepSpec


def test_signal_waits_then_early_message_is_consumed(env):
    store, api, _ = env
    run_id = api.submit(RunSpec((StepSpec.wait_signal(id="review", name="review"),)), "req-signal-early")
    engine = Engine(store, Registry())
    assert engine.execute_once() is False
    assert api.get_run(run_id)["status"] == "waiting_signal"
    api.signal(run_id, "review", "m-1", {"approved": True})
    assert api.get_run(run_id)["status"] == "queued"
    assert engine.execute_once() is True
    run = api.get_run(run_id)
    assert run["status"] == "succeeded"
    assert run["steps"][0]["result"] == {"approved": True}
    consumed = store.db.execute("SELECT consumed_by_step_id FROM signals WHERE run_id=?", (run_id,)).fetchone()
    assert consumed[0] == "review"


def test_signal_replay_is_idempotent_and_changed_content_conflicts(env):
    store, api, _ = env
    run_id = api.submit(RunSpec((StepSpec.wait_signal(id="review", name="review"),)), "req-signal-replay")
    first = api.signal(run_id, "review", "m-1", {"n": 1})
    second = api.signal(run_id, "review", "m-1", {"n": 1})
    assert first["seq"] == second["seq"]
    with pytest.raises(Conflict):
        api.signal(run_id, "review", "m-1", {"n": 2})


def test_signals_are_consumed_fifo_and_distinct_waits(env):
    store, api, _ = env
    spec = RunSpec((StepSpec.wait_signal(id="one", name="review"),
                    StepSpec.wait_signal(id="two", name="review")))
    run_id = api.submit(spec, "req-signal-fifo")
    api.signal(run_id, "review", "m-1", {"n": 1})
    api.signal(run_id, "review", "m-2", {"n": 2})
    engine = Engine(store, Registry())
    assert engine.execute_once() is True
    assert engine.execute_once() is True
    run = api.get_run(run_id)
    assert run["status"] == "succeeded"
    assert [s["result"] for s in run["steps"]] == [{"n": 1}, {"n": 2}]
    rows = store.db.execute("SELECT message_id,consumed_by_step_id FROM signals WHERE run_id=? ORDER BY seq", (run_id,)).fetchall()
    assert [(r[0], r[1]) for r in rows] == [("m-1", "one"), ("m-2", "two")]


def test_terminal_run_rejects_late_signal(env):
    store, api, _ = env
    run_id = api.submit(RunSpec((StepSpec.wait_signal(id="review", name="review"),)), "req-signal-terminal")
    engine = Engine(store, Registry())
    engine.execute_once()
    api.signal(run_id, "review", "m-1", {})
    engine.execute_once()
    with pytest.raises(Conflict):
        api.signal(run_id, "review", "m-2", {})
