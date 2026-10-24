import subprocess
import sys
import time

import pytest

from nexus import Engine, LeaseLost, Nexus, Registry, RetryPolicy, RunSpec, StepSpec, Store, Worker


def _wait_for(path, timeout=3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            return
        time.sleep(0.01)
    raise AssertionError(f"timed out waiting for {path}")


def test_worker_kill_after_attempt_allocation_recovers_spent_attempt(tmp_path):
    database = tmp_path / "killed.sqlite"
    marker = tmp_path / "allocated"
    with Store(database) as store:
        api = Nexus(store)
        policy = RetryPolicy(max_attempts=2, base_delay_ms=0, cap_delay_ms=0)
        spec = RunSpec((StepSpec.action(id="a", action="echo", version="1", input={}, retry=policy),))
        run_id = api.submit(spec, "req-kill-recovery")

    child = subprocess.Popen([
        sys.executable, "-c", """
import sys, time
from nexus import Engine, Registry, Store
store = Store(sys.argv[1])
engine = Engine(store, Registry(), lease_ms=50)
claim = engine.claim('killed-worker')
claim = engine.allocate_attempt(claim)
open(sys.argv[2], 'w').close()
time.sleep(10)
""", str(database), str(marker)])
    try:
        _wait_for(marker)
        child.terminate()
        child.wait(timeout=3)
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=3)

    time.sleep(0.08)
    with Store(database) as store:
        engine = Engine(store, Registry(), lease_ms=50)
        assert engine.reconcile_expired() == 1
        run = store.db.execute("SELECT status FROM runs WHERE run_id=?", (run_id,)).fetchone()
        attempt = store.db.execute("""SELECT attempt_no,status FROM attempts
            WHERE run_id=? ORDER BY attempt_no""", (run_id,)).fetchall()
        assert run[0] == "retry_wait"
        assert [(row[0], row[1]) for row in attempt] == [(1, "abandoned")]
        # With zero backoff, the spent attempt is immediately eligible for a new claim.
        claim = engine.claim("recovery-worker")
        assert claim is not None
        claim = engine.allocate_attempt(claim)
        assert claim.attempt_no == 2


def test_stale_completion_is_rejected_after_reconciliation(env):
    store, api, clock = env
    policy = RetryPolicy(max_attempts=2, base_delay_ms=0, cap_delay_ms=0)
    spec = RunSpec((StepSpec.action(id="a", action="echo", version="1", input={}, retry=policy),))
    run_id = api.submit(spec, "req-stale-recovery")
    engine = Engine(store, Registry(), lease_ms=5)
    old = engine.claim("old-worker")
    old = engine.allocate_attempt(old)
    clock.value += 6
    assert engine.reconcile_expired() == 1
    fresh = engine.claim("fresh-worker")
    fresh = engine.allocate_attempt(fresh)
    with pytest.raises(LeaseLost):
        engine.succeed(old, {"stale": True})
    engine.succeed(fresh, {"fresh": True})
    assert api.get_run(run_id)["status"] == "succeeded"
    assert api.get_run(run_id)["steps"][0]["result"] == {"fresh": True}


def test_worker_poll_reconciles_expired_attempts(env):
    store, api, clock = env
    registry = Registry().register("echo", "1", lambda value, ctx: {"attempt": ctx.attempt_no})
    policy = RetryPolicy(max_attempts=2, base_delay_ms=0, cap_delay_ms=0)
    run_id = api.submit(RunSpec((StepSpec.action(id="a", action="echo", version="1", input={},
                                                  retry=policy),)),
                        "req-worker-reconcile")
    old = Engine(store, registry, lease_ms=5).allocate_attempt(Engine(store, registry, lease_ms=5).claim("old"))
    clock.value += 6
    worker = Worker(store, registry, lease_ms=5, heartbeat_interval_ms=1)
    assert worker.run_once() is True
    assert api.get_run(run_id)["status"] == "succeeded"
    attempts = store.db.execute("SELECT attempt_no,status FROM attempts WHERE run_id=? ORDER BY attempt_no",
                                (run_id,)).fetchall()
    assert [(row[0], row[1]) for row in attempts] == [(1, "abandoned"), (2, "succeeded")]
