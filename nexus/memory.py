"""Scoped JSON memory broker with bounded values and CAS revisions."""
from __future__ import annotations

import json

from .extensions import ensure_tables
from .models import Conflict, InvalidSpec, canonical, identifier

MAX_VALUE_BYTES = 16384


class MemoryBroker:
    def __init__(self, store, *, max_value_bytes=MAX_VALUE_BYTES):
        if type(max_value_bytes) is not int or max_value_bytes < 1:
            raise ValueError("max_value_bytes must be positive")
        self.store = store
        self.max_value_bytes = max_value_bytes
        ensure_tables(store)

    def _scope(self, scope):
        return identifier(scope, "memory scope")

    def read(self, scope, key, owner):
        self._scope(scope); identifier(key, "memory key"); identifier(owner, "owner")
        with self.store.tx(read=True):
            row = self.store.db.execute("SELECT * FROM memory_records WHERE scope=? AND key=?", (scope, key)).fetchone()
            if row is None:
                return None
            if row["owner"] != owner:
                raise InvalidSpec("memory namespace denied")
            return {"scope": scope, "key": key, "revision": row["revision"],
                    "value": json.loads(row["value_json"]), "owner": owner}

    def write(self, scope, key, value, owner, *, expected_revision=None):
        self._scope(scope); identifier(key, "memory key"); identifier(owner, "owner")
        encoded = canonical(value)
        if len(encoded.encode()) > self.max_value_bytes:
            raise InvalidSpec("memory value exceeds configured limit")
        now = self.store.now_ms()
        with self.store.tx():
            row = self.store.db.execute("SELECT * FROM memory_records WHERE scope=? AND key=?", (scope, key)).fetchone()
            current = None if row is None else row["revision"]
            if expected_revision is not None and expected_revision != current:
                raise Conflict("memory revision conflict")
            if row is not None and row["owner"] != owner:
                raise InvalidSpec("memory namespace denied")
            revision = 1 if current is None else current + 1
            if row is None:
                self.store.db.execute("INSERT INTO memory_records VALUES (?,?,?,?,?,?)",
                                      (scope, key, revision, encoded, owner, now))
            else:
                self.store.db.execute("UPDATE memory_records SET revision=?,value_json=?,owner=?,updated_ms=? WHERE scope=? AND key=?",
                                      (revision, encoded, owner, now, scope, key))
            return {"scope": scope, "key": key, "revision": revision, "value": value, "owner": owner}

    def delete(self, scope, key, owner, *, expected_revision=None):
        row = self.read(scope, key, owner)
        if row is None:
            return False
        if expected_revision is not None and row["revision"] != expected_revision:
            raise Conflict("memory revision conflict")
        with self.store.tx():
            self.store.db.execute("DELETE FROM memory_records WHERE scope=? AND key=? AND owner=? AND revision=?",
                                  (scope, key, owner, row["revision"]))
        return True
