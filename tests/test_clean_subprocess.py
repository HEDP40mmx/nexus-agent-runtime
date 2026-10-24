import threading
import time

from nexus import Engine, Nexus, Registry, RunSpec, StepSpec, Store
from nexus.actions import echo, environment_probe, sleep_action


def test_importable_action_uses_clean_subprocess(tmp_path):
    with Store(tmp_path / "clean.sqlite") as store:
        api = Nexus(store)
        registry = Registry().register("echo", "1", echo)
        run_id = api.submit(RunSpec((StepSpec.action(id="a", action="echo", version="1", input={"ok": True}),)),
                            "clean-action")
        assert Engine(store, registry).execute_once() is True
        run = api.get_run(run_id)
        assert run["status"] == "succeeded"
        assert run["steps"][0]["result"] == {"value": {"ok": True}, "attempt_no": 1}


def test_clean_subprocess_does_not_inherit_parent_credentials(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "parent-secret")
    monkeypatch.setenv("NEXUS_BEARER_TOKEN", "parent-token")
    with Store(tmp_path / "environment.sqlite") as store:
        api = Nexus(store)
        registry = Registry().register("probe", "1", environment_probe)
        run_id = api.submit(RunSpec((StepSpec.action(id="a", action="probe", version="1", input={}),)),
                            "clean-environment")
        assert Engine(store, registry).execute_once() is True
        assert api.get_run(run_id)["steps"][0]["result"] == {
            "has_openai_key": False,
            "has_nexus_token": False,
        }


def test_cancellation_terminates_running_clean_child(tmp_path):
    path = tmp_path / "cancel.sqlite"
    with Store(path) as control_store:
        api = Nexus(control_store)
        registry = Registry().register("sleep", "1", sleep_action)
        run_id = api.submit(RunSpec((StepSpec.action(id="a", action="sleep", version="1",
                                                     input={"seconds": 5}, timeout_ms=5000),)),
                            "clean-cancel")
    def run_worker():
        with Store(path) as worker_store:
            Engine(worker_store, registry, lease_ms=100, heartbeat_interval_ms=20).execute_once()

    thread = threading.Thread(target=run_worker)
    started = time.monotonic()
    thread.start()
    with Store(path) as observer_store:
        observer = Nexus(observer_store)
        deadline = time.monotonic() + 2
        while observer.get_run(run_id)["status"] != "running" and time.monotonic() < deadline:
            time.sleep(0.01)
        with Store(path) as cancel_store:
            Nexus(cancel_store).cancel(run_id, "operator")
        thread.join(timeout=2)
        assert not thread.is_alive()
        assert time.monotonic() - started < 2
        assert observer.get_run(run_id)["status"] == "cancelled"
