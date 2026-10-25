# White-paper 370-test evidence map

**Document audited:** `Nexus Investor White Paper`, October 18, 2026, technical baseline 1.4.240.

**Audit conclusion:** The white paper’s 370-test result is supported by a preserved v1.4.240 archive and its validation logs, but it cannot be attributed to an exact commit in the current Git repository. The current repository contains a different fresh-v1 line. The 370-test archive source and tests are not present on `main`, PR #5’s merged history, or PR #6’s completion branch.

## Provenance of the 370-test claim

The preserved restoration audit identifies the source artifact as `nexus-v1.4.240-release.zip`, Drive file ID `1_H3ceS_gNZU-wX1_x7vVFrue7ByMRUAj`, with SHA-256 `63c2946d9bbdf049cb942605f3642ba477a20e475022b58a5b4a931e50c82613`. The audit records 17 runtime Python files, 33 test modules, and 370 discovered test methods. The same audit records the fresh source result as 370 tests passed in 57.039 seconds under Python 3.12.14, and the installed-wheel result as 369 passed plus one expected skip.

The preserved unittest log ends with `Ran 370 tests in 57.039s` and `OK`. Its individual output contains 33 historical modules and 313 visible unittest method lines; the difference is consistent with parameterized/subtest expansion and is why the total must be taken from the runner summary rather than summing visible method names. The atomic fresh-v1 checkpoint is a different artifact: its `source-tests.xml` records only 76 tests on October 18, 2026.

No repository ref, tag, or commit in the available Git history contains the v1.4.240 source tree or the 33 historical test modules. The available `copilot/recoverv14240` branches contain preservation workflows and documentation, not the release source. Therefore the 370-test result is **archive-verified but commit-unattributed** in this repository.

## Claim-level map

| White paper claim | Evidence artifact | Exact current repository commit/test mapping | Status |
|---|---|---|---|
| 17 runtime modules, 33 test modules, built wheel | v1.4.240 restoration audit; archive SHA above | No current commit contains the 17/33 archive layout. The current fresh-v1 line began at `794e998` and has a different module/test layout. | Archive-verified; current commit mapping unavailable |
| 370 source tests passed on Python 3.12.14 | `validation/source-unittest.log`; summary `Ran 370 tests in 57.039s` | No current commit contains the historical 33 test modules. Current branch validation is separate and must not be substituted. | Historical archive evidence |
| Installed wheel recorded 370 tests | `validation/installed-wheel-unittest.log`; audit says 369 passed and one expected source-only skip | No current commit maps to the archived 1.4.240 wheel. | Historical archive evidence |
| 241 tasks and 723 actions completed with zero workload failures | `validation/current-qualification.json`, version `1.4.240`, `completed_tasks=241`, `completed_actions=723`, `failures=0` | No current branch test reproduces this exact qualification workload. `tests/test_qualification.py` was introduced at `97663df`, but it is a smaller fresh-v1 recovery suite. | Historical synthetic evidence; not current-head evidence |
| Runtime recovery, leases, approvals, signals, backup/restore, worker limits, and telemetry are exercised | 33 historical modules listed below | Current analogues exist across `794e998`, `8043a6d`, `97974a9`, `326039e`, `b32de44`, `e9b86e8`, `3be4b90`, and `1370032`, but they are not the archived 370-test suite. | Partially reproduced on current branch; not equivalent evidence |
| Malformed preflight auth mode defect reproduced | Restoration audit §“Reproduced defect”; proposed patch changes `nexus/preflight.py`, `tests/test_preflight.py`, and `pyproject.toml` | Current branch’s `nexus/preflight.py` was introduced at `1b85370`, but it is a different implementation and does not contain the historical `tests/test_preflight.py`. | Historical defect verified; current fix not equivalent |
| Wheel integrity matched the checkpoint digest | Restoration audit records wheel SHA-256 `33fede...92b40e` | No current commit produces that archive wheel. Current branch has separate wheel builds from `1b85370` onward. | Archive-only artifact evidence |
| Hosted CI and production readiness were not established | White paper explicitly says hosted CI, release integration, customer pilots, security audit, SLA, and large-scale production were not established | Current PR #6 is still draft; its hosted checks are separate from the October 18 archive. | Correct limitation |

## Historical 33-module inventory and current mapping

The following table maps every historical test module named in the 370-test log to the closest current repository evidence. “No equivalent” means the current branch does not contain a test with the same scope; it does not mean the historical claim is false.

| Historical module | Visible methods in log | Historical scope | Closest current file and introducing commit | Assessment |
|---|---:|---|---|---|
| `test_api` | 13 | HTTP framing, bearer auth, malformed JSON | `tests/test_api.py`, `e9b86e8`; role/rate-limit additions at `2b87426` | Current partial equivalent |
| `test_audit_reconciliation` | 5 | Audit event reconciliation and ambiguity | No current equivalent | Archive-only |
| `test_auth_rate_limit` | 5 | Failure throttling and bounded client tracking | `tests/test_api.py`, `2b87426` | Narrow current equivalent |
| `test_auth_reload` | 3 | Atomic credential reload and generation handling | No current equivalent | Archive-only |
| `test_backup_restore` | 6 | Online backup, restore, integrity, CLI round trip | `tests/test_backup.py`, `794e998` | Core current equivalent, narrower scope |
| `test_build_runner` | 1 | Test floor before artifact creation | No current equivalent | Archive-only |
| `test_control_audit` | 3 | Mutation audit records and reconciliation | No current equivalent | Archive-only |
| `test_credit_adjustments` | 8 | Durable credit adjustment API and audit | No current equivalent; current `tests/test_control_extensions.py` is a simpler broker test from `1370032` | Not equivalent |
| `test_credit_recovery` | 11 | Credit reservation, crash recovery, unfunded-attempt prevention | No current equivalent; current `nexus/budgets.py` and its test were added at `1370032` but are not Engine-integrated | Not equivalent |
| `test_diagnostics` | 2 | Secret-free diagnostics and storage settings | `tests/test_cli.py`, `1b85370`, only partial | Not equivalent |
| `test_fault_qualification` | 4 | Process death, workspace reuse, machine-readable qualification | `tests/test_qualification.py`, `97663df`, smaller scope | Partial current equivalent |
| `test_graceful_shutdown` | 7 | Signal shutdown, request capacity, timeouts, cleanup | No current equivalent | Archive-only |
| `test_http_telemetry` | 2 | Bounded HTTP telemetry and log redaction | `tests/test_api.py`, `e9b86e8`, partial | Not equivalent |
| `test_lease_heartbeat` | 10 | Lease renewal, takeover, process death, long actions | `tests/test_engine.py`, `df21e7f`; `tests/test_qualification.py`, `97663df` | Core current equivalent, narrower scope |
| `test_migration_rehearsal` | 9 | Version migration, backup, rollback, injected failure | No current equivalent | Archive-only; major current gap |
| `test_operator_auth` | 8 | Auth files, permissions, principal validation | `tests/test_api.py`, `2b87426`, partial | Not equivalent |
| `test_platform_qualification` | 11 | Linux/service/platform/credential isolation | `tests/test_isolated_profile.py`, `3be4b90`; process/network additions at `dfedfcb` | Narrow current equivalent |
| `test_preflight` | 8 | Typed preflight config, auth files, no-network checks | Current `nexus/preflight.py` and `tests/test_cli.py`, `1b85370` | Different implementation; not equivalent |
| `test_qualification` | 19 | Bounded workload, artifact safety, latency, cleanup | `tests/test_qualification.py`, `97663df` | Partial current equivalent |
| `test_reliability` | 10 | Cancellation, concurrent dispatch, stale commits, scheduler recovery | `tests/test_engine.py`, `8043a6d`; `tests/test_controls.py`, `97974a9`; `tests/test_qualification.py`, `97663df` | Distributed across current tests; narrower |
| `test_resources` | 4 | Resource snapshots and bounded metrics | `tests/test_isolated_profile.py`, `3be4b90` | Narrow current equivalent |
| `test_retention` | 5 | Retention/pruning and protected history | No current equivalent | Archive-only |
| `test_retention_qualification` | 4 | Retention qualification workspace safety | No current equivalent | Archive-only |
| `test_runtime` | 48 | Main runtime: capabilities, memory, budgets, delegation, command workers, schedules, migration | Current core split across `tests/test_runtime.py`, `794e998`, plus `1370032` and `7835dc0` extension tests | Not equivalent; current extensions are not fully Engine-integrated |
| `test_runtime_metrics` | 5 | Durable runtime metrics aggregation | Current `tests/test_control_extensions.py`, `1370032`, only in-process telemetry | Not equivalent |
| `test_scheduler_telemetry` | 24 | Scheduler lifecycle and outcome telemetry | No current equivalent | Archive-only |
| `test_server_credentials` | 4 | Owner-only credential files and source selection | No current equivalent | Archive-only |
| `test_side_effect_fencing` | 17 | Delegation/memory fencing under cancellation and stale workers | Current `tests/test_control_extensions.py`, `1370032`, `7835dc0`, only primitive broker tests | Not equivalent |
| `test_signal_recovery` | 8 | Signal acknowledgement rollback, replay, stale owner protection | `tests/test_signals.py`, `326039e` | Core current equivalent, narrower scope |
| `test_soak` | 5 | Bounded soak workload and interruption resume | No current equivalent | Archive-only |
| `test_soak_safeguards` | 3 | Storage/free-space safeguards | No current equivalent | Archive-only |
| `test_unknown_action_recovery` | 5 | Unknown-action durable blocking and operator recovery | `tests/test_engine.py`, `8043a6d`, only basic unknown-action behavior | Partial current equivalent |
| `test_worker_telemetry` | 36 | Command worker protocol, output limits, cleanup, telemetry | `tests/test_supervisor.py`, `b32de44`; `tests/test_clean_subprocess.py`, `bc4e310`; isolated controls at `3be4b90` and `dfedfcb` | Partial current equivalent |

## Exact current-branch commit map

These are the exact current repository commits that implement the closest fresh-v1 equivalents, not the historical 1.4.240 evidence:

- `794e998` — initial fresh-v1 package, models, Store, service, schema, legacy Runtime, backup/model/store/runtime tests.
- `8043a6d` — fenced action execution, registry/Engine integration, and `tests/test_engine.py`.
- `97974a9` — approval and cancellation controls with `tests/test_controls.py`.
- `326039e` — durable signal consumption with `tests/test_signals.py`.
- `df21e7f` — background lease heartbeat.
- `97663df` — expired-lease reconciliation and subprocess kill/recovery qualification with `tests/test_qualification.py`.
- `b32de44` — bounded supervised child execution and `tests/test_supervisor.py`.
- `e9b86e8` — authenticated HTTP controls and `tests/test_api.py`.
- `2b87426` — role hierarchy, rate limiting, and HTTP security additions.
- `bc4e310` — clean importable subprocess boundary and `tests/test_clean_subprocess.py`.
- `3be4b90` — isolated execution profile and POSIX resource-limit tests.
- `dfedfcb` — process-count and network-deny configuration.
- `1b85370` — operational CLI, preflight, offline demo, and `tests/test_cli.py`.
- `1370032` — standalone capability, memory, budget, secret, and telemetry brokers with `tests/test_control_extensions.py`.
- `7835dc0` — durable parent-child delegation link primitives.

## Bottom line

The white paper’s 370-test claim is a valid statement about the preserved v1.4.240 archive and its local validation record, subject to the archive’s stated limitations. It is not a claim that can be attached to a current Git commit in this repository. The current repository has a separate fresh-v1 history with materially fewer and differently organized tests. The correct release documentation must preserve both facts and must not use the historical 370 count as current-head evidence.
