# Nexus acceptance matrix

Updated for PR #5 head `3be4b90e805de2889c4172ba0221d17406845bd7` on 2026-10-24. Local Python 3.12 suite: 103 passed; clean-launch, isolated-profile, resource-limit validation, cancellation, compilation, and `git diff --check` checks passed. Hosted CI for this isolated-profile head is pending.

| Gate | Status | Evidence or remaining gap |
|---|---|---|
| Immutable workflow models and bounded canonical JSON | implemented and tested locally | Existing model tests; 64 KiB and depth limits |
| SQLite schema, FK enforcement, transaction boundaries | implemented and tested locally | Store/schema tests; fresh-v1 schema v1 |
| Idempotent submission and conflict semantics | implemented and tested locally | Service tests |
| Durable claims, epochs, stale-owner fencing | implemented and tested locally | Engine and qualification tests |
| Deterministic retries and spent-attempt accounting | implemented and tested locally | Engine and recovery tests |
| Durable signals, FIFO consumption, replay/conflict | implemented and tested locally | Signal tests |
| Approvals and cancellation fencing | implemented and tested locally | Control tests; expiry/race breadth remains limited |
| Automatic heartbeat during active action | implemented and tested locally | Separate SQLite connection and long-action test |
| Expired lease reconciliation | implemented and tested locally | Explicit `reconcile_expired()` plus worker-poll qualification |
| Worker kill after durable allocation | implemented and tested locally | Real subprocess qualification |
| Stale completion after replacement | implemented and tested locally | Real recovery qualification |
| Supervised child action execution | partially implemented and tested locally | Importable handlers use `python -I -m nexus._action` with fixed args, minimal environment, closed descriptors, and bounded streams; non-importable handlers still use trusted fork fallback |
| Action timeout enforcement | implemented and tested locally | Timeout qualification |
| Process-group/descendant cleanup | implemented and tested locally | Clean and trusted paths terminate process groups; adversarial escape tests remain |
| Active termination on cancellation/lease loss | implemented and tested locally | Clean child is terminated when heartbeat fencing reports loss |
| Isolated CPU/memory/file limits | implemented and tested locally | `ResourceLimits` maps to `RLIMIT_CPU`, `RLIMIT_AS`, and `RLIMIT_FSIZE` |
| Isolated filesystem boundary | fail-closed and capability-qualified | Absolute root plus `unshare` namespace probe and child `chroot`; this sandbox lacks the required namespace capability |
| Child protocol output bound | implemented and tested locally | Oversized-result qualification; stderr channel not separately implemented |
| Authenticated HTTP control endpoints | implemented and tested locally | Localhost bearer-token adapter and structured errors |
| Role-based authorization | implemented and tested locally | Independent reader/operator/admin tokens; reader is read-only; audit principal comes from matched role |
| Per-client rate limiting and request bounds | implemented and tested locally | Sliding-window 429 limiter, bounded handler concurrency, socket timeout, 64 KiB body limit |
| HTTP TLS and external/public deployment security | not implemented | Must remain localhost-only or sit behind a properly secured TLS reverse proxy |
| Full CLI worker/serve/preflight/demo | partially implemented | Existing CLI; worker/serve/demo/preflight completeness remains |
| Online backup and fresh restore | implemented and tested locally | Existing backup tests; broader concurrent-write rehearsal remains |
| Packaging and installed-package qualification | implemented and tested locally | Fresh wheel/sdist build and outside-checkout schema/import smoke passed |
| Delegation, memory, capabilities, budgets, secrets, telemetry | not implemented | Product slices remain |
| Full X01-X16 / 31+16 gates | not complete | Several product and deployment gates remain |
| Hosted CI for final head | pending | Must query the run for exact `3be4b90` head |

## Unsupported guarantees

The clean launch is a controlled same-user subprocess boundary, not hostile-code sandboxing. Non-importable handlers still use a trusted fork fallback, so the no-fork release gate is not complete. CPU, address-space, and file-size limits are implemented for clean children; filesystem isolation is opt-in and fails closed when namespace capability is unavailable. The implementation does not claim exactly-once external effects, power-loss safety, TLS, distributed scale, or production readiness. Role authentication and local rate limiting are implemented, but token rotation, persistent auth-file management, authentication-failure metrics, adversarial escape testing, and reverse-proxy hardening remain future work.
