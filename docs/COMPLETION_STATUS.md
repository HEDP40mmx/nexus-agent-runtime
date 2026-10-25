# Nexus completion status

This document describes the post-merge completion branch, not a claim that the full blueprint is finished.

## Candidate

- Base: `main` merge commit `641e0fcf8db7bfdda235d7702537b709ffdd46cc`
- Branch: `manus/nexus-complete-hardening-20261025`
- PR: https://github.com/HEDP40mmx/nexus-agent-runtime/pull/6
- Current implementation head: `7835dc09a4c5057653a2ba341d7739318954c7b5`
- Main remains unchanged after PR #5.

## Implemented in this branch

The branch adds a complete operational CLI surface for `init`, `submit`, `inspect`, `events`, `cancel`, `approve`, `signal`, `worker`, `serve`, `preflight`, and an offline `demo`. It also adds structured deployment preflight reporting and installed-package coverage.

It adds tested, durable extension brokers for scoped capability grants, bounded namespaced memory with revision/CAS conflicts, internal-credit budget reservations/spending/releases, reference-only environment/file secret resolution with redaction, bounded counters/gauges/timings, and idempotent parent-child delegation links with completion and cancellation primitives.

Validation at the latest locally tested pre-delegation head was 111 passing tests, compilation clean, wheel build clean, `pip check` clean, and `git diff --check` clean. The delegation commit was pushed after that validation and requires its own hosted-CI result at the exact head.

## Still not complete

The extension brokers are intentionally not yet wired into workflow admission and action dispatch. The remaining integration work includes:

- capability-denied dispatch before attempt/child creation;
- step-level capability declarations and child-grant narrowing;
- budget reservation in the same transaction as attempt/child allocation, crash reconciliation, and root conservation;
- secret-reference fields in workflow specs and authorized child-only injection;
- telemetry instrumentation across durable transitions with bounded labels and reconciliation;
- engine-native delegate/wait-child steps, depth/count/cycle limits, and parent/child restart races;
- migration qualification from an authentic v1 fixture with rollback-on-failure;
- adversarial process escape/resource exhaustion tests;
- mixed 1000-transition multi-worker qualification;
- Docker/service restart and fresh-location restore qualification;
- independent wheel and sdist external-checkout tests;
- TLS/reverse-proxy deployment documentation and owner-action decisions.

The trusted non-importable handler fallback, target-kernel isolated namespace qualification, and unsupported exactly-once external-effect guarantees remain documented limitations.

## Review rule

Do not mark PR #6 ready or merge it as a complete product until the integration rows above have executable tests and exact-head hosted-CI evidence. A green CI run on an earlier commit is not evidence for a later head.
