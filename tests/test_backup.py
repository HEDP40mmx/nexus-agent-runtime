import sqlite3
import pytest
from nexus import Conflict, Nexus, Store
from .conftest import spec


def test_backup_reopens_committed_state(env,tmp_path):
    store,n,clock = env
    run = n.submit(spec(),"keep")
    path = store.backup(tmp_path/"backup.db")
    with Store(path,clock=clock) as restored:
        assert Nexus(restored).get_run(run) == n.get_run(run)
        assert Nexus(restored).events(run) == n.events(run)
        assert tuple(restored.db.execute("PRAGMA integrity_check").fetchone()) == ("ok",)
        assert restored.db.execute("PRAGMA foreign_key_check").fetchall() == []


def test_backup_never_overwrites(env,tmp_path):
    path = tmp_path/"existing.db"
    path.write_bytes(b"preserve")
    with pytest.raises(Conflict):
        env[0].backup(path)
    assert path.read_bytes() == b"preserve"
