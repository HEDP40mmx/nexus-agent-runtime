import pytest
from nexus import Engine, Registry, RetryableError, StepSpec, RunSpec


def test_registered_action_completes_run(env):
    store, api, _ = env
    registry = Registry().register("echo", "1", lambda value, ctx: {"echo": value["text"], "key": ctx.effect_key})
    run_id = api.submit(RunSpec((StepSpec.action(id="a", action="echo", version="1", input={"text": "hi"}),)), "req-engine")
    engine = Engine(store, registry)
    assert engine.execute_once() is True
    run = api.get_run(run_id)
    assert run["status"] == "succeeded"
    assert run["steps"][0]["result"]["echo"] == "hi"
    assert run["steps"][0]["attempts_started"] == 1
    assert len([e for e in api.events(run_id) if e["kind"] == "step_succeeded"]) == 1


def test_unknown_action_fails_without_spending_attempt(env):
    store, api, _ = env
    run_id = api.submit(RunSpec((StepSpec.action(id="a", action="missing", version="1", input={}),)), "req-missing")
    assert Engine(store, Registry()).execute_once() is True
    run = api.get_run(run_id)
    assert run["status"] == "failed"
    assert run["steps"][0]["attempts_started"] == 0
    assert run["steps"][0]["error_code"] == "PERMANENT_ERROR"


def test_retry_delay_is_durable_and_deterministic(env):
    store, api, clock = env
    calls = []

    def flaky(value, ctx):
        calls.append(ctx.attempt_no)
        if len(calls) == 1:
            raise RetryableError("temporary")
        return {"ok": True}

    registry = Registry().register("flaky", "1", flaky)
    step = StepSpec.action(id="a", action="flaky", version="1", input={},
                           retry=__import__("nexus").RetryPolicy(max_attempts=2, base_delay_ms=10, cap_delay_ms=15))
    run_id = api.submit(RunSpec((step,)), "req-retry")
    engine = Engine(store, registry)
    engine.execute_once()
    run = api.get_run(run_id)
    assert run["status"] == "retry_wait"
    assert run["steps"][0]["due_at_ms"] == clock.value + 10
    assert engine.execute_once() is False
    clock.value += 10
    assert engine.execute_once() is True
    assert api.get_run(run_id)["status"] == "succeeded"
    assert calls == [1, 2]


def test_stale_owner_cannot_finish_after_epoch_replacement(env):
    store, api, clock = env
    registry = Registry().register("echo", "1", lambda value, ctx: value)
    run_id = api.submit(RunSpec((StepSpec.action(id="a", action="echo", version="1", input={}),)), "req-fence")
    first = Engine(store, registry, lease_ms=5).claim("one")
    first = Engine(store, registry, lease_ms=5).allocate_attempt(first)
    clock.value += 6
    # Reconciliation is deliberately explicit: an expired claim cannot heartbeat or finish.
    with pytest.raises(Exception) as exc:
        Engine(store, registry, lease_ms=5).heartbeat(first)
    assert exc.value.code == "LEASE_LOST"
    assert api.get_run(run_id)["status"] == "running"
