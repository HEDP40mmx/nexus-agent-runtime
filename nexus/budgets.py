"""Durable internal execution-credit accounting."""
from __future__ import annotations

import uuid

from .extensions import ensure_tables
from .models import Conflict, InvalidSpec, identifier, integer


class BudgetBroker:
    def __init__(self, store):
        self.store = store
        ensure_tables(store)

    def create(self, root_id, limit_credits):
        identifier(root_id, "root budget")
        integer(limit_credits, "limit_credits", 1, 2**63 - 1)
        with self.store.tx():
            old = self.store.db.execute("SELECT * FROM budget_accounts WHERE root_id=?", (root_id,)).fetchone()
            if old:
                if old["limit_credits"] != limit_credits:
                    raise Conflict("budget already exists with different limit")
                return dict(old)
            now = self.store.now_ms()
            self.store.db.execute("INSERT INTO budget_accounts VALUES (?,?,0,0,?)", (root_id, limit_credits, now))
            return dict(self.store.db.execute("SELECT * FROM budget_accounts WHERE root_id=?", (root_id,)).fetchone())

    def reserve(self, root_id, ref_id, credits):
        identifier(root_id, "root budget"); identifier(ref_id, "budget reference")
        integer(credits, "credits", 1, 2**63 - 1)
        with self.store.tx():
            account = self.store.db.execute("SELECT * FROM budget_accounts WHERE root_id=?", (root_id,)).fetchone()
            if account is None:
                raise InvalidSpec("unknown budget")
            old = self.store.db.execute("SELECT * FROM budget_ledger WHERE root_id=? AND ref_id=? AND kind='reserved'",
                                        (root_id, ref_id)).fetchone()
            if old:
                if old["credits"] != credits:
                    raise Conflict("budget reference already reserved differently")
                return dict(old)
            if account["reserved_credits"] + account["spent_credits"] + credits > account["limit_credits"]:
                error = InvalidSpec("budget exhausted")
                error.code = "BUDGET_EXHAUSTED"
                raise error
            now = self.store.now_ms(); entry = uuid.uuid4().hex
            self.store.db.execute("UPDATE budget_accounts SET reserved_credits=reserved_credits+?,updated_ms=? WHERE root_id=?",
                                  (credits, now, root_id))
            self.store.db.execute("INSERT INTO budget_ledger VALUES (?,?,?,?,?,?)",
                                  (entry, root_id, ref_id, "reserved", credits, now))
            return dict(self.store.db.execute("SELECT * FROM budget_ledger WHERE entry_id=?", (entry,)).fetchone())

    def spend(self, root_id, ref_id):
        with self.store.tx():
            row = self.store.db.execute("SELECT * FROM budget_ledger WHERE root_id=? AND ref_id=? AND kind='reserved'",
                                        (root_id, ref_id)).fetchone()
            if row is None:
                raise InvalidSpec("unknown budget reservation")
            spent = self.store.db.execute("SELECT * FROM budget_ledger WHERE root_id=? AND ref_id=? AND kind='spent'",
                                          (root_id, ref_id)).fetchone()
            if spent:
                return dict(spent)
            now = self.store.now_ms(); entry = uuid.uuid4().hex
            self.store.db.execute("UPDATE budget_accounts SET reserved_credits=reserved_credits-?,spent_credits=spent_credits+?,updated_ms=? WHERE root_id=?",
                                  (row["credits"], row["credits"], now, root_id))
            self.store.db.execute("INSERT INTO budget_ledger VALUES (?,?,?,?,?,?)",
                                  (entry, root_id, ref_id, "spent", row["credits"], now))
            return dict(self.store.db.execute("SELECT * FROM budget_ledger WHERE entry_id=?", (entry,)).fetchone())

    def release(self, root_id, ref_id):
        with self.store.tx():
            row = self.store.db.execute("SELECT * FROM budget_ledger WHERE root_id=? AND ref_id=? AND kind='reserved'",
                                        (root_id, ref_id)).fetchone()
            if row is None:
                return False
            spent = self.store.db.execute("SELECT 1 FROM budget_ledger WHERE root_id=? AND ref_id=? AND kind='spent'",
                                          (root_id, ref_id)).fetchone()
            if spent:
                raise Conflict("spent budget cannot be released")
            self.store.db.execute("UPDATE budget_accounts SET reserved_credits=reserved_credits-?,updated_ms=? WHERE root_id=?",
                                  (row["credits"], self.store.now_ms(), root_id))
            self.store.db.execute("DELETE FROM budget_ledger WHERE entry_id=?", (row["entry_id"],))
            return True

    def account(self, root_id):
        row = self.store.db.execute("SELECT * FROM budget_accounts WHERE root_id=?", (root_id,)).fetchone()
        return None if row is None else dict(row)
