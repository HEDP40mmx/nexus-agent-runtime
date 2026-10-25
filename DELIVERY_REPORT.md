# Nexus delivery report

Recorded 2026-10-23 for branch `manus/nexus-v1-complete-20261023`.

## Repository and commits

The implementation is based on `main` commit `aa6eead48329fc154aba803d41935a1ad75a623d`. The current implementation head is `dfedfcb2abc437f6d825db373f61f513b6aea350`. Draft PR: https://github.com/HEDP40mmx/nexus-agent-runtime/pull/5. `main` was not modified.

The branch contains the imported checkpoint as `794e998`, the registry/engine/worker milestone as `8043a6d`, approval/cancellation controls as `97974a9`, durable signals as `326039e`, supervised execution/provenance as `b32de44`, and HTTP/reconciliation controls as `e9b86e8`.

## Validation actually performed

Using an external Python 3.12.3 virtual environment on Linux with SQLite 3.45.1, the checkpoint baseline passed 76 tests. The current full suite passes 103 tests, including signal, heartbeat, worker-kill/recovery, clean child launch, credential-hygiene, active cancellation, isolated-profile validation, role authorization, and rate-limit tests. `pip check`, `compileall`, and `git diff --check` passed. The local database policy reports foreign keys enabled, a 5000 ms busy timeout, and the checkpoint’s journal selection behavior; this environment uses SQLite 3.45.1, which is not in the blueprint’s safe WAL range, so new databases select DELETE/EXTRA under `journal=auto`.

Hosted CI run `40073393260` succeeded at isolated-profile head `3be4b90`; the process/network head `dfedfcb` is awaiting its own hosted run. The pre-import failure `40001799576` is historical and not used as current evidence.

## Requirement status

| Area | Status | Evidence or gap |
|---|---|---|
| Immutable models, strict JSON, canonical digests | implemented and tested locally | Imported checkpoint tests |
| Atomic SQLite schema, submission replay/conflict, events, backup | implemented and tested locally | Imported checkpoint tests |
| Versioned action registry | implemented and tested locally | `nexus/registry.py`, engine tests |
| Durable claims, lease epoch, heartbeat fencing | implemented and tested locally; fork warning remains | `nexus/engine.py`; independent heartbeat connection and long-action regression test |
| Attempt allocation, deterministic retries, and expired-lease recovery | implemented and tested locally | `nexus/engine.py`, `tests/test_qualification.py`; worker poll schedules reconciliation |
| Supervised child processes and bounded protocol | partially implemented and tested locally | Importable handlers use clean `python -I -m nexus._action`; non-importable handlers retain trusted fork fallback; bounded protocol and process cleanup tests pass |
| Credential hygiene and active cancellation | implemented and tested locally for clean handlers | Minimal environment excludes tested parent credentials; heartbeat lease loss/cancellation actively terminates clean child |
| Isolated CPU/memory/file/process limits | implemented and tested locally | `ResourceLimits` maps to POSIX `RLIMIT_CPU`, `RLIMIT_AS`, `RLIMIT_FSIZE`, and `RLIMIT_NPROC` |
| Isolated filesystem/network boundary | fail-closed and capability-qualified | Absolute root, user/mount/PID/network namespace probe, no inherited network interfaces, and child `chroot`; current sandbox lacks required namespace capability |
| Approvals and cancellation | implemented and tested locally | `nexus/service.py`, `tests/test_controls.py`; expiry/mismatch races remain |
| Durable signals and consuming waits | implemented and tested locally | FIFO consumption, replay/conflict handling, early delivery, and wait wake-up |
| HTTP API and bearer authentication | implemented and tested locally | `nexus/api.py`; localhost-only bearer authentication with structured errors |
| HTTP roles and rate limiting | implemented and tested locally | Reader/operator/admin hierarchy, constant-time token matching, per-client sliding-window 429 limiter, bounded concurrency and socket timeout |
| Complete CLI, preflight and offline demo | partially implemented | Checkpoint CLI only; worker/serve/preflight/demo remain |
| Delegation, scoped memory, capabilities, budgets, secrets, telemetry | not implemented | Planned follow-up slices |
| Packaging | implemented and tested locally | Fresh wheel/sdist build and outside-checkout schema/import smoke passed |
| Deployment examples and full runbooks | not implemented | Existing recovery documentation preserved |
| Wheel/sdist installed-package qualification | implemented and tested locally | Python 3.12 wheel/sdist installs and schema/import smoke passed |
| Complete-product X01–X16 | not complete | Most controls and qualification remain outstanding |

## Known defects and safety boundaries

Importable actions now use a clean `python -I -m nexus._action` child with a fixed argument vector, minimal environment, closed descriptors, bounded streams, POSIX CPU/address-space/file-size/process-count limits, timeout, process-group cleanup, and active cancellation/lease-loss termination. The opt-in isolated profile requires a filesystem root and successful Linux user/mount/PID/network namespace capability probe, then applies `chroot` with no inherited network interfaces; it fails closed when unavailable. Non-importable handlers still use the trusted same-user fork fallback and continue to emit Python’s multithreaded-fork warning; migrating that fallback is a release gate. The HTTP adapter has local role-based bearer authentication, per-client rate limiting, bounded request concurrency, socket timeouts, and 64 KiB request limits; it remains localhost-only and lacks TLS, token rotation/auth-file management, and persistent authentication-failure metrics. Adversarial escape/resource-exhaustion tests, approval expiry/races, complete CLI/preflight/demo, deployment, delegation, memory, capabilities, budgets, secrets, telemetry, and complete-product gates remain unfinished.

Do not interpret the local test count as proof of exactly-once external effects, power-loss safety, hostile-code isolation, hosted CI success, or production readiness.
