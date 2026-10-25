"""Lazy, idempotent tables for versioned control extensions."""


def ensure_tables(store):
    with store.tx():
        store.db.executescript("""
        CREATE TABLE IF NOT EXISTS capability_grants (
            run_id TEXT NOT NULL, scope TEXT NOT NULL, capability TEXT NOT NULL,
            granted_by TEXT NOT NULL, created_ms INTEGER NOT NULL, revoked_ms INTEGER,
            PRIMARY KEY (run_id, scope, capability)
        );
        CREATE TABLE IF NOT EXISTS memory_records (
            scope TEXT NOT NULL, key TEXT NOT NULL, revision INTEGER NOT NULL,
            value_json TEXT NOT NULL, owner TEXT NOT NULL, updated_ms INTEGER NOT NULL,
            PRIMARY KEY (scope, key)
        );
        CREATE TABLE IF NOT EXISTS budget_accounts (
            root_id TEXT PRIMARY KEY, limit_credits INTEGER NOT NULL,
            reserved_credits INTEGER NOT NULL DEFAULT 0,
            spent_credits INTEGER NOT NULL DEFAULT 0,
            updated_ms INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS budget_ledger (
            entry_id TEXT PRIMARY KEY, root_id TEXT NOT NULL, ref_id TEXT NOT NULL,
            kind TEXT NOT NULL, credits INTEGER NOT NULL, created_ms INTEGER NOT NULL,
            UNIQUE (root_id, ref_id, kind)
        );
        CREATE TABLE IF NOT EXISTS run_links (
            parent_run_id TEXT NOT NULL, child_run_id TEXT NOT NULL,
            link_key TEXT NOT NULL, status TEXT NOT NULL, created_ms INTEGER NOT NULL,
            completed_ms INTEGER, PRIMARY KEY (parent_run_id, link_key),
            UNIQUE (child_run_id)
        );
        """)
