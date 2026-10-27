import pytest

from nexus import Store
from nexus.budgets import BudgetBroker
from nexus.capabilities import CapabilityBroker
from nexus.memory import MemoryBroker
from nexus.secrets import SecretResolver, redact
from nexus.telemetry import Telemetry
from nexus.delegation import DelegationBroker
from nexus import Nexus, RunSpec, StepSpec
from nexus.engine import Engine
from nexus.registry import Registry
from nexus.actions import marker_action


def test_capability_grant_revoke_and_denial(tmp_path):
    with Store(tmp_path / "controls.sqlite") as store:
        broker = CapabilityBroker(store)
        row = broker.grant("run", "step", "network.none", "admin")
        assert row["revoked_ms"] is None
        assert broker.allowed("run", "step", "network.none")
        broker.require("run", "step", "network.none")
        assert broker.revoke("run", "step", "network.none", "admin")
        with pytest.raises(Exception) as exc:
            broker.require("run", "step", "network.none")
        assert getattr(exc.value, "code", None) == "CAPABILITY_DENIED"


def test_denied_capability_allocates_no_attempt_and_starts_no_child(tmp_path):
    marker = tmp_path / "child-started"
    with Store(tmp_path / "admission.sqlite") as store:
        api = Nexus(store)
        registry = Registry().register("marker", "1", marker_action)
        engine = Engine(store, registry=registry)
        run_id = api.submit(RunSpec((StepSpec.action(
            id="step", action="marker", version="1", input={"path": str(marker)},
            capabilities=["filesystem.write"]),)), "denial")

        assert engine.execute_once() is False
        run = api.get_run(run_id)
        assert run["status"] == "failed"
        assert run["error_code"] == "CAPABILITY_DENIED"
        assert run["steps"][0]["error_code"] == "CAPABILITY_DENIED"
        assert store.db.execute("SELECT count(*) FROM attempts WHERE run_id=?", (run_id,)).fetchone()[0] == 0
        assert not marker.exists()
        events = api.events(run_id)
        denied = [event for event in events if event["kind"] == "capability_denied"]
        assert len(denied) == 1
        assert denied[0]["payload"]["capabilities"] == ["filesystem.write"]


def test_memory_is_scoped_bounded_and_compare_and_set(tmp_path):
    with Store(tmp_path / "memory.sqlite") as store:
        memory = MemoryBroker(store, max_value_bytes=100)
        saved = memory.write("run-a", "k", {"v": 1}, "owner-a")
        assert memory.read("run-a", "k", "owner-a")["revision"] == 1
        with pytest.raises(Exception):
            memory.read("run-a", "k", "owner-b")
        with pytest.raises(Exception):
            memory.write("run-a", "k", {"v": 2}, "owner-a", expected_revision=0)
        updated = memory.write("run-a", "k", {"v": 2}, "owner-a", expected_revision=saved["revision"])
        assert updated["revision"] == 2


def test_budget_reservation_spend_and_release_conserve_capacity(tmp_path):
    with Store(tmp_path / "budget.sqlite") as store:
        budget = BudgetBroker(store)
        budget.create("root", 10)
        budget.reserve("root", "child-1", 6)
        with pytest.raises(Exception):
            budget.reserve("root", "child-2", 5)
        budget.spend("root", "child-1")
        account = budget.account("root")
        assert account["spent_credits"] == 6
        assert account["reserved_credits"] == 0


def test_secret_references_and_redaction(tmp_path):
    secret_file = tmp_path / "secret"
    secret_file.write_text("file-secret\n", encoding="utf-8")
    resolver = SecretResolver(env={"TOKEN": "env-secret"}, files={"prod": secret_file})
    assert resolver.resolve("env:TOKEN") == "env-secret"
    assert resolver.resolve("file:prod") == "file-secret"
    with pytest.raises(Exception):
        resolver.resolve(f"file:{secret_file}")
    with pytest.raises(Exception) as exc:
        resolver.resolve("file:missing")
    assert getattr(exc.value, "code", None) == "SECRET_UNAVAILABLE"
    text = redact("Authorization: Bearer env-secret", ["env-secret"])
    assert "env-secret" not in text
    assert "REDACTED" in text


def test_telemetry_is_bounded_and_snapshot_is_structured():
    telemetry = Telemetry(max_series=2)
    telemetry.increment("runs", labels={"state": "ok"})
    telemetry.gauge("workers", 1)
    snapshot = telemetry.snapshot()
    assert snapshot["counters"][0]["value"] == 1
    with pytest.raises(ValueError):
        telemetry.increment("third", labels={"state": "new"})


def test_delegation_link_is_idempotent_and_completion_wakes_parent(tmp_path):
    with Store(tmp_path / "delegation.sqlite") as store:
        api = Nexus(store)
        parent = api.submit(RunSpec((StepSpec.wait_signal(id="p", name="done"),)), "parent")
        child = api.submit(RunSpec((StepSpec.wait_signal(id="c", name="child"),)), "child")
        broker = DelegationBroker(store)
        first = broker.link(parent, child, "child-1")
        assert broker.link(parent, child, "child-1")["child_run_id"] == child
        assert first["status"] == "waiting"
        assert broker.complete_child(child, "succeeded")
        assert broker.cancel_descendants(parent, "operator") == 0
