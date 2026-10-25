"""Scoped capability grants for dispatch admission."""
from __future__ import annotations

from .extensions import ensure_tables
from .models import Conflict, InvalidSpec, identifier


class CapabilityBroker:
    def __init__(self, store):
        self.store = store
        ensure_tables(store)

    def grant(self, run_id, scope, capability, principal):
        for value, name in ((run_id, "run id"), (scope, "scope"), (capability, "capability"), (principal, "principal")):
            identifier(value, name)
        now = self.store.now_ms()
        with self.store.tx():
            old = self.store.db.execute(
                "SELECT * FROM capability_grants WHERE run_id=? AND scope=? AND capability=?",
                (run_id, scope, capability)).fetchone()
            if old and old["revoked_ms"] is None:
                if old["granted_by"] != principal:
                    raise Conflict("capability already granted by another principal")
                return dict(old)
            if old:
                self.store.db.execute("UPDATE capability_grants SET granted_by=?,created_ms=?,revoked_ms=NULL WHERE run_id=? AND scope=? AND capability=?",
                                      (principal, now, run_id, scope, capability))
            else:
                self.store.db.execute("INSERT INTO capability_grants VALUES (?,?,?,?,?,NULL)",
                                      (run_id, scope, capability, principal, now))
            return dict(self.store.db.execute("SELECT * FROM capability_grants WHERE run_id=? AND scope=? AND capability=?",
                                              (run_id, scope, capability)).fetchone())

    def revoke(self, run_id, scope, capability, principal):
        identifier(principal, "principal")
        now = self.store.now_ms()
        with self.store.tx():
            row = self.store.db.execute("SELECT * FROM capability_grants WHERE run_id=? AND scope=? AND capability=?",
                                        (run_id, scope, capability)).fetchone()
            if row is None or row["revoked_ms"] is not None:
                return False
            if row["granted_by"] != principal:
                raise Conflict("only the granting principal may revoke capability")
            self.store.db.execute("UPDATE capability_grants SET revoked_ms=? WHERE run_id=? AND scope=? AND capability=?",
                                  (now, run_id, scope, capability))
            return True

    def allowed(self, run_id, scope, capability):
        row = self.store.db.execute("SELECT 1 FROM capability_grants WHERE run_id=? AND scope=? AND capability=? AND revoked_ms IS NULL",
                                    (run_id, scope, capability)).fetchone()
        return row is not None

    def require(self, run_id, scope, capability):
        if not self.allowed(run_id, scope, capability):
            error = InvalidSpec("capability denied")
            error.code = "CAPABILITY_DENIED"
            raise error
