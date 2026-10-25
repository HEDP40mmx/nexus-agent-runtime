# Nexus v2 release notes

Release target: **Nexus Agent Runtime v2**
Branch: `manus/nexus-v1-integration-qualification`
Prepared: 2026-10-25

## Summary

Nexus v2 advances the single-host, single-tenant Linux runtime from the v1 schema and control foundation toward an integration-qualified alpha. The headline change is a transactional, versioned SQLite schema migration path from v1 to v2, backed by a committed historical fixture and rollback qualification tests.

This release is an integration-qualified alpha, not a claim of hostile-code isolation, exactly-once external effects, distributed execution, or general production readiness.

## Highlights

- Added a versioned migration registry in `nexus/migrations.py`.
- Added automatic v1-to-v2 migration during `Store` initialization.
- Added durable migration history in `schema_migrations`.
- Added v2 control-extension tables for capabilities, memory, budgets, and run links.
- Added fail-closed handling for malformed or unversioned databases.
- Added an authentic committed v1 SQLite fixture containing existing workflow and event data.
- Verified that existing v1 run and event data survives migration unchanged.
- Added mid-migration failure injection proving transactional rollback and byte-identical restoration.
- Preserved durable workflow transitions, leases, epochs, fencing, signals, approvals, supervised child execution, heartbeats, timeouts, HTTP roles, rate limiting, and recovery qualification from the preceding integration work.
- Updated packaging and Store tests for schema version 2.

## Compatibility and upgrade behavior

Opening a valid v1 database with the v2 runtime upgrades it transactionally to schema version 2. The migration creates the v2 extension tables and records migration versions 1 and 2. If migration fails, SQLite rolls back the schema and data changes; the original v1 database remains usable for a later retry.

A database with an unknown schema version, a nonempty unversioned file, or a versioned file missing required runtime metadata is rejected without migration. Downgrading a v2 database to an older runtime is not supported.

The runtime continues to require a local file-backed SQLite database. `journal=auto` follows the existing local journal-selection policy; this qualification environment uses SQLite 3.45.1 and selects DELETE/EXTRA rather than WAL when WAL is outside the configured safe range.

## Qualification evidence

Validation performed in the external Python 3.12 environment on Linux:

- Full test suite: **115 passed**.
- Migration, Store, and packaging subset: **23 passed**.
- Python compilation: passed.
- `pip check`: passed.
- `git diff --check`: passed.
- Real subprocess worker-kill, recovery, timeout, descendant cleanup, heartbeat, signal, authentication, rate-limit, and packaging tests remain included in the full suite.

## Known limitations

- Non-importable handlers retain a trusted same-user fork fallback; this is not a hostile-code sandbox.
- The isolated profile fails closed when the host lacks the required Linux namespace capability; the current qualification sandbox lacks that capability.
- HTTP control remains localhost-oriented and does not provide TLS, token rotation, persistent authentication-failure metrics, or reverse-proxy hardening.
- Approval race breadth, adversarial isolation/escape testing, complete worker/serve/preflight/demo CLI coverage, deployment runbooks, delegation, scoped memory integration, budgets, secrets references, telemetry, and the complete X01-X16 product gate set remain incomplete.
- The implementation does not guarantee exactly-once effects for external systems, power-loss safety, distributed scale, or automatic recovery of non-transactional side effects.

## Upgrade checklist

1. Back up the existing v1 database.
2. Stop writers and workers before the first upgrade attempt.
3. Open the database with the v2 runtime and verify the reported schema version is 2.
4. Confirm existing run and event counts and inspect `schema_migrations`.
5. Resume workers only after the verification succeeds.
6. Retain the pre-upgrade backup until recovery and application-level checks are complete.

See `docs/ACCEPTANCE_MATRIX.md`, `DELIVERY_REPORT.md`, and `RESUME.md` for the current qualification matrix, reproducibility commands, and remaining work.
