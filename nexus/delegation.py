"""Durable parent-child run links and bounded cascade transitions."""
from __future__ import annotations

import uuid

from .extensions import ensure_tables
from .models import Conflict, InvalidSpec, NotFound, identifier


class DelegationBroker:
    def __init__(self, store, *, max_depth=8, max_children=32):
        self.store = store
        self.max_depth = max_depth
        self.max_children = max_children
        ensure_tables(store)

    def link(self, parent_run_id, child_run_id, link_key):
        identifier(parent_run_id, "parent run id"); identifier(child_run_id, "child run id"); identifier(link_key, "link key")
        if parent_run_id == child_run_id:
            raise InvalidSpec("a run cannot delegate to itself")
        now = self.store.now_ms()
        with self.store.tx():
            if self.store.db.execute("SELECT 1 FROM runs WHERE run_id=?", (parent_run_id,)).fetchone() is None:
                raise NotFound("parent run not found")
            if self.store.db.execute("SELECT 1 FROM runs WHERE run_id=?", (child_run_id,)).fetchone() is None:
                raise NotFound("child run not found")
            old = self.store.db.execute("SELECT * FROM run_links WHERE parent_run_id=? AND link_key=?",
                                        (parent_run_id, link_key)).fetchone()
            if old:
                if old["child_run_id"] != child_run_id:
                    raise Conflict("delegation link key already binds another child")
                return dict(old)
            count = self.store.db.execute("SELECT count(*) FROM run_links WHERE parent_run_id=?", (parent_run_id,)).fetchone()[0]
            if count >= self.max_children:
                raise InvalidSpec("delegation child limit exceeded")
            if self.store.db.execute("SELECT 1 FROM run_links WHERE child_run_id=?", (child_run_id,)).fetchone():
                raise Conflict("child already has a parent")
            self.store.db.execute("INSERT INTO run_links VALUES (?,?,?,?,?,NULL)",
                                  (parent_run_id, child_run_id, link_key, "waiting", now))
            return dict(self.store.db.execute("SELECT * FROM run_links WHERE parent_run_id=? AND link_key=?",
                                              (parent_run_id, link_key)).fetchone())

    def complete_child(self, child_run_id, status):
        if status not in ("succeeded", "failed", "cancelled"):
            raise InvalidSpec("invalid child terminal status")
        with self.store.tx():
            row = self.store.db.execute("SELECT * FROM run_links WHERE child_run_id=?", (child_run_id,)).fetchone()
            if row is None:
                return False
            if row["status"] == status:
                return True
            now = self.store.now_ms()
            self.store.db.execute("UPDATE run_links SET status=?,completed_ms=? WHERE child_run_id=? AND status='waiting'",
                                  (status, now, child_run_id))
            parent = self.store.db.execute("SELECT * FROM runs WHERE run_id=?", (row["parent_run_id"],)).fetchone()
            if parent and parent["status"] == "waiting_child":
                next_status = "queued" if status == "succeeded" else "failed"
                self.store.db.execute("UPDATE runs SET status=?,ready_at_ms=?,error_code=?,updated_ms=? WHERE run_id=?",
                                      (next_status, now, None if status == "succeeded" else "CHILD_" + status.upper(), now, row["parent_run_id"]))
            return True

    def cancel_descendants(self, parent_run_id, principal):
        identifier(principal, "principal")
        with self.store.tx():
            children = self.store.db.execute("SELECT child_run_id FROM run_links WHERE parent_run_id=? AND status='waiting'",
                                             (parent_run_id,)).fetchall()
            now = self.store.now_ms()
            for child in children:
                self.store.db.execute("UPDATE runs SET status='cancelled',lease_epoch=lease_epoch+1,lease_owner=NULL,lease_until_ms=NULL,error_code='PARENT_CANCELLED',updated_ms=? WHERE run_id=? AND status NOT IN ('succeeded','failed','cancelled')",
                                      (now, child["child_run_id"]))
                self.store.db.execute("UPDATE run_links SET status='cancelled',completed_ms=? WHERE parent_run_id=? AND child_run_id=? AND status='waiting'",
                                      (now, parent_run_id, child["child_run_id"]))
            return len(children)
