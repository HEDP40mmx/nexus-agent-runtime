import pytest
from nexus import Engine, Registry, RunSpec, StepSpec


def gated():
    return RunSpec((StepSpec.action(id="a", action="echo", version="1", input={"x": 1}, require_approval=True),))


def test_approval_blocks_dispatch_then_approved_action_runs(env):
    store, api, _ = env
    run_id = api.submit(gated(), "req-approval")
    registry = Registry().register("echo", "1", lambda value, ctx: value)
    engine = Engine(store, registry)
    assert engine.execute_once() is False
    run = api.get_run(run_id)
    assert run["status"] == "waiting_approval"
    assert run["steps"][0]["attempts_started"] == 0
    approval = run["approvals"][0]
    api.decide(approval["approval_id"], "approved", "operator")
    assert engine.execute_once() is True
    assert api.get_run(run_id)["status"] == "succeeded"


def test_denied_approval_is_terminal_without_dispatch(env):
    store, api, _ = env
    run_id = api.submit(gated(), "req-denied")
    engine = Engine(store, Registry())
    engine.execute_once()
    approval_id = api.get_run(run_id)["approvals"][0]["approval_id"]
    api.decide(approval_id, "denied", "operator")
    run = api.get_run(run_id)
    assert run["status"] == "failed"
    assert run["steps"][0]["attempts_started"] == 0
    assert engine.execute_once() is False


def test_cancel_fences_queued_run(env):
    store, api, _ = env
    run_id = api.submit(gated(), "req-cancel")
    run = api.cancel(run_id, "operator")
    assert run["status"] == "cancelled"
    assert Engine(store, Registry()).execute_once() is False
    assert api.cancel(run_id, "operator")["status"] == "cancelled"
