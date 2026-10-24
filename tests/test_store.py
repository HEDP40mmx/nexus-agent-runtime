import sqlite3
import pytest
from nexus import Conflict, StorageError, Store
from .conftest import action, spec


def test_idempotency_and_atomic_submission(env):
    store, n, _ = env
    run = n.submit(spec(), "key")
    assert n.submit(spec(), "key") == run
    assert len(n.events(run)) == 1
    with pytest.raises(Conflict):
        n.submit(spec(action("other")), "key")
    store.db.execute("""CREATE TRIGGER reject_event BEFORE INSERT ON events
                        BEGIN SELECT RAISE(ABORT,'injected'); END""")
    with pytest.raises(StorageError):
        n.submit(spec(), "new")
    assert store.db.execute("SELECT count(*) FROM runs").fetchone()[0] == 1
    assert store.db.execute("SELECT count(*) FROM steps").fetchone()[0] == 1


def test_schema_and_reopen(env):
    store, n, clock = env
    run = n.submit(spec(), "key")
    mode = store.settings()
    assert mode["journal_mode"] in ("wal", "delete")
    assert mode == dict(user_version=1,journal_mode=mode["journal_mode"],
                        synchronous=2 if mode["journal_mode"] == "wal" else 3,
                        foreign_keys=1,busy_timeout=5000)
    with Store(store.path, clock=clock) as reopened:
        from nexus import Nexus
        assert Nexus(reopened).get_run(run)["status"] == "queued"
        assert reopened.settings() == mode


@pytest.mark.parametrize("version", [0, 2, 999])
def test_unknown_database_is_not_modified(tmp_path, version):
    path = tmp_path / "unknown.db"
    with sqlite3.connect(path) as c:
        c.execute("CREATE TABLE valuable(x)")
        c.execute("INSERT INTO valuable VALUES ('keep')")
        c.execute(f"PRAGMA user_version={version}")
    before = path.read_bytes()
    with pytest.raises(Conflict):
        Store(path)
    assert path.read_bytes() == before


def test_existing_journal_cannot_silently_change(tmp_path):
    with Store(tmp_path/"x.db", journal="delete") as s:
        assert s.settings()["synchronous"] == 3
    with Store(tmp_path/"x.db") as s:
        assert s.settings()["journal_mode"] == "delete"
    from nexus.store import wal_safe
    from nexus import InvalidSpec
    with pytest.raises(Conflict if wal_safe(sqlite3.sqlite_version_info) else InvalidSpec):
        Store(tmp_path/"x.db", journal="wal")


@pytest.mark.parametrize("version,safe", [((3,44,5),False),((3,44,6),True),
    ((3,45,0),False),((3,50,6),False),((3,50,7),True),((3,51,0),False),
    ((3,51,2),False),((3,51,3),True),((3,53,1),True)])
def test_journal_version_policy(version,safe):
    from nexus.store import selected_journal
    from nexus import InvalidSpec
    assert selected_journal("auto", version) == ("wal" if safe else "delete")
    if safe:
        assert selected_journal("wal", version) == "wal"
    else:
        with pytest.raises(InvalidSpec):
            selected_journal("wal", version)


def test_storage_contention_does_not_create_a_partial_run(env):
    from nexus import Nexus, StorageBusy
    store,n,clock = env
    with Store(store.path, clock=clock, busy_timeout_ms=10) as other:
        with store.tx():
            with pytest.raises(StorageBusy):
                Nexus(other).submit(spec(),"busy")
        assert other.db.execute("SELECT count(*) FROM runs").fetchone()[0] == 0
        assert other.db.execute("SELECT count(*) FROM events").fetchone()[0] == 0
