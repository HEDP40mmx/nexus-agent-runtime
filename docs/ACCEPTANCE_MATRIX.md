# Nexus acceptance matrix

Updated for PR #5 head `e9b86e8bd3d01c55e215243281aa305a646d0d88` on 2026-10-23. Local Python 3.12 suite: 96 passed; compilation and `git diff --check` passed. Hosted CI for this exact head is pending/not yet observed.

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
| Supervised child action execution | implemented and tested locally | Fork child, fixed internal target, bounded JSON response |
| Action timeout enforcement | implemented and tested locally | Timeout qualification |
| Process-group/descendant cleanup | implemented and tested locally | Descendant sleep process qualification |
| Child protocol output bound | implemented and tested locally | Oversized-result qualification; stderr channel not separately implemented |
| Authenticated HTTP control endpoints | implemented and tested locally | Localhost bearer-token adapter and structured errors |
| HTTP TLS, operator roles, rate limits | not implemented | Current adapter is localhost-oriented bearer auth only |
| Full CLI worker/serve/preflight/demo | partially implemented | Existing CLI; worker/serve/demo/preflight completeness remains |
| Online backup and fresh restore | implemented and tested locally | Existing backup tests; broader concurrent-write rehearsal remains |
| Packaging and installed-package qualification | prepared but unverified at this head | Must rebuild wheel/sdist and run outside-checkout smoke after final changes |
| Delegation, memory, capabilities, budgets, secrets, telemetry | not implemented | Product slices remain |
| Full X01-X16 / 31+16 gates | not complete | Several product and deployment gates remain |
| Hosted CI for final head | prepared but unverified | Query after hosted run for exact `e9b86e8` head |

## Unsupported guarantees

The supervised boundary is a trusted same-user process boundary, not hostile-code sandboxing. The implementation does not claim exactly-once external effects, power-loss safety, TLS/operator-role security, distributed scale, or production readiness. Fork-based supervision currently emits Python’s warning when the parent is multithreaded; this needs a safer process-launch design before production use.
