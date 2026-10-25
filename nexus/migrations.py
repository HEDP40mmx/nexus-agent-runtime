"""Transactional SQLite schema migrations for the single-host runtime."""
from __future__ import annotations

from .models import Conflict

CURRENT_SCHEMA_VERSION = 2


def _migration_1_to_2(db, failpoint=None):
    """Install durable control-extension tables and migration history.

    SQLite DDL participates in the surrounding transaction.  The failpoint is
    intentionally injectable for qualification tests and is never configured by
    normal callers.
    """
    db.execute("""CREATE TABLE schema_migrations (
        version INTEGER PRIMARY KEY,
        applied_ms INTEGER NOT NULL
    )""")
    db.execute("INSERT INTO schema_migrations(version, applied_ms) VALUES (1, 0)")
    for name, statement in (
        ("capability_grants", """CREATE TABLE capability_grants (
            run_id TEXT NOT NULL, scope TEXT NOT NULL, capability TEXT NOT NULL,
            granted_by TEXT NOT NULL, created_ms INTEGER NOT NULL, revoked_ms INTEGER,
            PRIMARY KEY (run_id, scope, capability)
        )"""),
        ("step_capabilities", """CREATE TABLE step_capabilities (
            run_id TEXT NOT NULL, step_id TEXT NOT NULL, capability TEXT NOT NULL,
            PRIMARY KEY (run_id, step_id, capability)
        )"""),
        ("memory_records", """CREATE TABLE memory_records (
            scope TEXT NOT NULL, key TEXT NOT NULL, revision INTEGER NOT NULL,
            value_json TEXT NOT NULL, owner TEXT NOT NULL, updated_ms INTEGER NOT NULL,
            PRIMARY KEY (scope, key)
        )"""),
        ("budget_accounts", """CREATE TABLE budget_accounts (
            root_id TEXT PRIMARY KEY, limit_credits INTEGER NOT NULL,
            reserved_credits INTEGER NOT NULL DEFAULT 0,
            spent_credits INTEGER NOT NULL DEFAULT 0,
            updated_ms INTEGER NOT NULL
        )"""),
        ("budget_ledger", """CREATE TABLE budget_ledger (
            entry_id TEXT PRIMARY KEY, root_id TEXT NOT NULL, ref_id TEXT NOT NULL,
            kind TEXT NOT NULL, credits INTEGER NOT NULL, created_ms INTEGER NOT NULL,
            UNIQUE (root_id, ref_id, kind)
        )"""),
        ("run_links", """CREATE TABLE run_links (
            parent_run_id TEXT NOT NULL, child_run_id TEXT NOT NULL,
            link_key TEXT NOT NULL, status TEXT NOT NULL, created_ms INTEGER NOT NULL,
            completed_ms INTEGER, PRIMARY KEY (parent_run_id, link_key),
            UNIQUE (child_run_id)
        )"""),
    ):
        db.execute(statement)
        if failpoint == name:
            raise RuntimeError(f"injected migration failure after {name}")
    db.execute("INSERT INTO schema_migrations(version, applied_ms) VALUES (2, 0)")


MIGRATIONS = {2: _migration_1_to_2}


def migrate(db, current, target=CURRENT_SCHEMA_VERSION, failpoint=None):
    if current > target:
        raise Conflict("Database schema is newer than this runtime")
    while current < target:
        next_version = current + 1
        try:
            migration = MIGRATIONS[next_version]
        except KeyError as exc:
            raise Conflict(f"No migration path from schema {current}") from exc
        migration(db, failpoint=failpoint)
        db.execute(f"PRAGMA user_version={next_version}")
        current = next_version


def migration_history(db):
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='schema_migrations'").fetchone():
        return []
    return [dict(row) for row in db.execute(
        "SELECT version, applied_ms FROM schema_migrations ORDER BY version")]
