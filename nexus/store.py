"""Explicit SQLite transactions, journal/version guards and online backup."""
from contextlib import contextmanager, closing
from importlib import resources
import json
import os
from pathlib import Path
import sqlite3
from .models import (Conflict, InvalidSpec, StorageError, StorageBusy, SystemClock,
                     canonical)


def wal_safe(version):
    return ((3, 44, 6) <= version < (3, 45, 0) or
            (3, 50, 7) <= version < (3, 51, 0) or version >= (3, 51, 3))


def selected_journal(requested, version=None):
    if requested not in ("auto", "wal", "delete"):
        raise InvalidSpec("journal must be auto, wal or delete")
    safe = wal_safe(version or sqlite3.sqlite_version_info)
    if requested == "wal" and not safe:
        raise InvalidSpec("WAL requires a verified SQLite WAL-reset fix")
    return ("wal" if safe else "delete") if requested == "auto" else requested


class Store:
    """One instance/connection belongs to one thread and process."""
    def __init__(self, path, journal="auto", clock=None, busy_timeout_ms=5000):
        if str(path) == ":memory:" or not str(path).strip():
            raise InvalidSpec("A local file database is required")
        self.path = str(Path(path).absolute())
        self.clock = clock or SystemClock()
        self.db = None
        try:
            self.db = sqlite3.connect(self.path, autocommit=True, timeout=busy_timeout_ms / 1000)
            self.db.row_factory = sqlite3.Row
            self.db.execute("PRAGMA foreign_keys=ON")
            self.db.execute(f"PRAGMA busy_timeout={int(busy_timeout_ms)}")
            self._initialize(journal)
        except BaseException as exc:
            if self.db is not None:
                self.db.close()
            if isinstance(exc, sqlite3.Error):
                self._raise_storage(exc)
            raise

    @staticmethod
    def _raise_storage(exc):
        code = getattr(exc, "sqlite_errorcode", 0) & 0xff
        if code in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
            raise StorageBusy("Database is busy; retry the operation") from exc
        raise StorageError("SQLite operation failed") from exc

    def _initialize(self, requested):
        # Inspect before changing any persistent PRAGMA on an existing file.
        version = self.db.execute("PRAGMA user_version").fetchone()[0]
        nonempty = self.db.execute("SELECT 1 FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'").fetchone()
        if version not in (0, 1) or (version == 0 and nonempty):
            raise Conflict("Unknown or unversioned database; no migration performed")
        if version == 0:
            mode = selected_journal(requested)
            actual = self.db.execute(f"PRAGMA journal_mode={mode}").fetchone()[0]
            if actual != mode:
                raise StorageError("Could not select the requested journal")
        else:
            mode = self.db.execute("SELECT value FROM runtime_meta WHERE key='journal'").fetchone()
            if mode is None or mode[0] not in ("wal", "delete"):
                raise Conflict("Invalid journal metadata")
            mode = mode[0]
            selected_journal(mode)
            if requested != "auto" and selected_journal(requested) != mode:
                raise Conflict("Existing journal mode must not be changed")
            if self.db.execute("PRAGMA journal_mode").fetchone()[0] != mode:
                raise Conflict("Journal mode differs from durable metadata")
        self.db.execute("PRAGMA synchronous=" + ("FULL" if mode == "wal" else "EXTRA"))
        with self.tx():
            # Another initializer may have won the lock.
            v = self.db.execute("PRAGMA user_version").fetchone()[0]
            if v == 0:
                if self.db.execute("SELECT 1 FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'").fetchone():
                    raise Conflict("Nonempty unversioned database")
                sql = resources.files("nexus").joinpath("schema.sql").read_text()
                statement = ""
                for line in sql.splitlines():
                    statement += line + "\n"
                    if sqlite3.complete_statement(statement):
                        self.db.execute(statement)
                        statement = ""
                self.db.execute("INSERT INTO runtime_meta VALUES ('journal',?)", (mode,))
                self.db.execute("PRAGMA user_version=1")
            elif v != 1:
                raise Conflict("Unsupported schema version")

    def now_ms(self):
        return self.clock.now_ms()

    @contextmanager
    def tx(self, *, read=False):
        try:
            self.db.execute("BEGIN" if read else "BEGIN IMMEDIATE")
            try:
                yield self.db
                self.db.execute("COMMIT")
            except BaseException:
                if self.db.in_transaction:
                    self.db.execute("ROLLBACK")
                raise
        except sqlite3.Error as exc:
            self._raise_storage(exc)

    def event(self, run_id, kind, now, payload=None, step_id=None):
        self.db.execute("INSERT INTO events(run_id,step_id,kind,at_ms,payload_json) VALUES (?,?,?,?,?)",
                        (run_id, step_id, kind, now, canonical(payload or {})))

    def settings(self):
        return {key: self.db.execute("PRAGMA " + key).fetchone()[0]
                for key in ("user_version", "journal_mode", "synchronous", "foreign_keys", "busy_timeout")}

    def backup(self, output):
        destination = Path(output).absolute()
        try:
            fd = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError as exc:
            raise Conflict("Backup destination already exists") from exc
        os.close(fd)
        try:
            with closing(sqlite3.connect(destination, autocommit=True)) as target:
                self.db.backup(target, pages=128)
                integrity = target.execute("PRAGMA integrity_check").fetchall()
                fk = target.execute("PRAGMA foreign_key_check").fetchall()
                if integrity != [("ok",)] or fk:
                    raise StorageError("Backup integrity check failed")
            return str(destination)
        except BaseException:
            destination.unlink(missing_ok=True)
            raise

    def close(self):
        if self.db is not None:
            self.db.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
