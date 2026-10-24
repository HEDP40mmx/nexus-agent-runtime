# Nexus delivery report

Recorded 2026-10-23 for branch `manus/nexus-v1-complete-20261023`.

## Repository and commits

The implementation is based on `main` commit `aa6eead48329fc154aba803d41935a1ad75a623d`. The implementation head is `97974a9639bcc89cf3a00cc0ac9c94c30b8b247b`; the final documentation head is `f7f302f3e9d5e3e4479c7fd10119302f1e7c2cb8`. Draft PR: https://github.com/HEDP40mmx/nexus-agent-runtime/pull/5. `main` was not modified.

The branch contains the imported checkpoint as `794e998`, the registry/engine/worker milestone as `8043a6d`, and approval/cancellation controls as `97974a9`.

## Validation actually performed

Using an external Python 3.12.3 virtual environment on Linux with SQLite 3.45.1, the checkpoint baseline passed 76 tests. After the engine milestone, the full suite passed 80 tests. After approval and cancellation controls, the full suite passed 83 tests. After durable signal consumption and automatic heartbeats, the full suite passed 88 tests. After subprocess kill/recovery qualification, the full suite passed 90 tests, including real kill-after-allocation, abandoned-attempt recovery, and stale-completion tests. `pip check`, the required-file safeguard, `compileall`, and `git diff --check` passed. The local database policy reports foreign keys enabled, a 5000 ms busy timeout, and the checkpoint’s journal selection behavior; this environment uses SQLite 3.45.1, which is not in the blueprint’s safe WAL range, so new databases select DELETE/EXTRA under `journal=auto`.

Hosted CI run `40001799576` failed at the pre-import head `3659cff` because the required package paths were absent at that historical commit. Hosted CI run `40002328861` succeeded at head `8043a6d`, and hosted CI run `40002530774` succeeded at head `97974a9`. The later documentation-only head `f7f302f` has not had a separate hosted run recorded; the implementation code is unchanged after the successful implementation run.

## Requirement status

| Area | Status | Evidence or gap |
|---|---|---|
| Immutable models, strict JSON, canonical digests | implemented and tested locally | Imported checkpoint tests |
| Atomic SQLite schema, submission replay/conflict, events, backup | implemented and tested locally | Imported checkpoint tests |
| Versioned action registry | implemented and tested locally | `nexus/registry.py`, engine tests |
| Durable claims, lease epoch, heartbeat fencing | implemented and tested locally; full recovery still pending | `nexus/engine.py`; independent heartbeat connection and long-action regression test |
| Attempt allocation, deterministic retries, and explicit expired-lease recovery | implemented and tested locally | `nexus/engine.py`, `tests/test_qualification.py`; worker-loop reconciliation scheduling remains pending |
| Supervised child processes and bounded protocol | not implemented | Current engine still invokes trusted handlers in-process |
| Approvals and cancellation | implemented and tested locally | `nexus/service.py`, `tests/test_controls.py`; expiry/mismatch races remain |
| Durable signals and consuming waits | implemented and tested locally | FIFO consumption, replay/conflict handling, early delivery, and wait wake-up |
| HTTP API, authentication, roles, rate limits | not implemented | Existing checkpoint has no `api.py` |
| Complete CLI, preflight and offline demo | partially implemented | Checkpoint CLI only; worker/serve/preflight/demo remain |
| Delegation, scoped memory, capabilities, budgets, secrets, telemetry | not implemented | Planned follow-up slices |
| Packaging | prepared but not freshly built in this checkpoint | `pyproject.toml` and package data exist; artifact build is included separately if successful |
| Deployment examples and full runbooks | not implemented | Existing recovery documentation preserved |
| Wheel/sdist installed-package qualification | pending artifact run | Must be rerun from outside checkout |
| Complete-product X01–X16 | not complete | Most controls and qualification remain outstanding |

## Known defects and safety boundaries

The worker currently executes trusted registry handlers in the worker process rather than a shell-free supervised child. Automatic renewal now runs on a separate SQLite connection while an action is active. Explicit expired-lease reconciliation and real subprocess kill/stale-completion tests now pass, but the long-lived worker does not yet schedule reconciliation automatically, and timeout enforcement and child cleanup are not yet implemented. Durable signal waits are implemented and tested. Approval expiry and mismatched approval binding need more tests and a migration/extension design. HTTP, preflight, complete CLI, deployment, and the complete-product controls are unfinished.

Do not interpret the local test count as proof of exactly-once external effects, power-loss safety, hostile-code isolation, hosted CI success, or production readiness.
