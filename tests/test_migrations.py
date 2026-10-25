import shutil
import sqlite3
from pathlib import Path

import pytest

from nexus import Store
from nexus.migrations import migration_history


FIXTURE = Path(__file__).parent / "fixtures" / "runtime_v1.sqlite"


def copy_fixture(tmp_path, name="runtime.sqlite"):
    path = tmp_path / name
    shutil.copyfile(FIXTURE, path)
    return path


def test_authentic_v1_fixture_migrates_transactionally_and_preserves_state(tmp_path):
    path = copy_fixture(tmp_path)
    with Store(path, journal="delete") as store:
        assert store.settings()["user_version"] == 2
        assert store.db.execute("SELECT count(*) FROM runs WHERE run_id='fixture-run'").fetchone()[0] == 1
        assert store.db.execute("SELECT count(*) FROM events WHERE run_id='fixture-run'").fetchone()[0] == 1
        assert store.db.execute("SELECT count(*) FROM step_capabilities").fetchone()[0] == 0
        assert migration_history(store.db) == [
            {"version": 1, "applied_ms": 0},
            {"version": 2, "applied_ms": 0},
        ]

    with Store(path, journal="delete") as reopened:
        assert reopened.settings()["user_version"] == 2
        assert reopened.db.execute("SELECT spec_json FROM runs WHERE run_id='fixture-run'").fetchone()[0].startswith('{')


def test_mid_migration_failure_rolls_back_schema_and_data(tmp_path):
    path = copy_fixture(tmp_path, "failed.sqlite")
    before = path.read_bytes()

    with pytest.raises(RuntimeError, match="injected migration failure"):
        Store(path, journal="delete", migration_failpoint="step_capabilities")

    assert path.read_bytes() == before
    with sqlite3.connect(path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 1
        assert db.execute("SELECT count(*) FROM runs WHERE run_id='fixture-run'").fetchone()[0] == 1
        assert db.execute("SELECT 1 FROM sqlite_master WHERE name='schema_migrations'").fetchone() is None
        assert db.execute("SELECT 1 FROM sqlite_master WHERE name='capability_grants'").fetchone() is None

    with Store(path, journal="delete") as recovered:
        assert recovered.settings()["user_version"] == 2
        assert migration_history(recovered.db)[-1]["version"] == 2
