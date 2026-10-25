import os
import subprocess
import time

from nexus import Engine, Nexus, Registry, RetryPolicy, RunSpec, StepSpec, Store


def _eventually_gone(pid, timeout=2):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        except PermissionError:
            return False
        time.sleep(0.01)
    return False


def test_timeout_is_enforced_and_retryable_error_is_durable(tmp_path):
    with Store(tmp_path / "timeout.sqlite") as store:
        api = Nexus(store)

        def hangs(value, ctx):
            time.sleep(0.3)
            return {"unexpected": True}

        registry = Registry().register("hangs", "1", hangs)
        policy = RetryPolicy(max_attempts=1, base_delay_ms=0, cap_delay_ms=0)
        run_id = api.submit(RunSpec((StepSpec.action(id="a", action="hangs", version="1", input={},
                                                      retry=policy, timeout_ms=40),)),
                            "req-timeout")
        assert Engine(store, registry, lease_ms=500, heartbeat_interval_ms=20).execute_once() is True
        run = api.get_run(run_id)
        assert run["status"] == "failed"
        assert run["error_code"] == "ACTION_TIMEOUT"
        assert run["steps"][0]["attempts_started"] == 1


def test_timeout_terminates_descendant_process_group(tmp_path):
    with Store(tmp_path / "tree.sqlite") as store:
        api = Nexus(store)
        pid_file = tmp_path / "descendant.pid"

        def spawns(value, ctx):
            child = subprocess.Popen(["sleep", "10"])
            pid_file.write_text(str(child.pid))
            time.sleep(10)
            return {"unexpected": True}

        registry = Registry().register("spawns", "1", spawns)
        policy = RetryPolicy(max_attempts=1, base_delay_ms=0, cap_delay_ms=0)
        run_id = api.submit(RunSpec((StepSpec.action(id="a", action="spawns", version="1", input={
            "pid_file": str(pid_file)}, retry=policy, timeout_ms=60),)), "req-tree-kill")
        Engine(store, registry, lease_ms=500, heartbeat_interval_ms=20).execute_once()
        assert pid_file.exists()
        descendant_pid = int(pid_file.read_text())
        assert _eventually_gone(descendant_pid)
        assert api.get_run(run_id)["error_code"] == "ACTION_TIMEOUT"


def test_oversized_child_result_is_rejected(tmp_path):
    with Store(tmp_path / "bounded.sqlite") as store:
        api = Nexus(store)

        def oversized(value, ctx):
            return {"data": "x" * 70000}

        registry = Registry().register("oversized", "1", oversized)
        policy = RetryPolicy(max_attempts=1, base_delay_ms=0, cap_delay_ms=0)
        run_id = api.submit(RunSpec((StepSpec.action(id="a", action="oversized", version="1", input={},
                                                      retry=policy),)), "req-bounded")
        Engine(store, registry).execute_once()
        assert api.get_run(run_id)["status"] == "failed"
        assert api.get_run(run_id)["error_code"] in {"INVALID_SPEC", "ACTION_ERROR"}
