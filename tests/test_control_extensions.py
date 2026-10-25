import pytest

from nexus import Store
from nexus.budgets import BudgetBroker
from nexus.capabilities import CapabilityBroker
from nexus.memory import MemoryBroker
from nexus.secrets import SecretResolver, redact
from nexus.telemetry import Telemetry


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
