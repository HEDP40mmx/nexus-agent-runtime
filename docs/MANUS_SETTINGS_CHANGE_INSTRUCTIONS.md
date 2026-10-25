# Manus instructions: Nexus repository and validation settings

## Purpose

Use this runbook to prepare Nexus for an integration-first completion pass. The goal is to make the repository and validation environment capable of proving the remaining claims without silently merging, publishing, changing owner secrets, or treating historical evidence as current evidence.

The repository is `HEDP40mmx/nexus-agent-runtime`. The default branch is `main`. The current completion branch is `manus/nexus-complete-hardening-20261025`, and PR #6 is intentionally draft.

The current main commit is the baseline. Do not reset, rewrite, force-push, merge, or delete branches. Preserve the existing repository safeguards.

## Copy-paste task for Manus

> Inspect the current Nexus repository and settings before changing anything. Work only on a new feature branch based on the current `main`; do not modify or merge `main`.
>
> First report the exact values of:
>
> - default branch and current main SHA;
> - branch protection/rulesets for `main`;
> - required status checks;
> - GitHub Actions workflow permissions;
> - repository Actions policy and allowed actions;
> - open PRs and their draft/ready state;
> - current CI result at the exact candidate head;
> - available archive, Drive, Manus file, or connector access;
> - Python version and dependency installation path;
> - whether the current environment can run Linux namespace/resource-limit probes.
>
> Do not change settings during this inspection. Produce a before-state report first.
>
> Next, implement only these safe repository settings unless a setting is unavailable:
>
> 1. Protect `main` against force-push and deletion.
> 2. Require pull requests for changes to `main`.
> 3. Require the repository CI test check to pass before merge.
> 4. Require branches to be up to date before merge if this does not cause an unavailable or circular check.
> 5. Keep PR #6 draft. Do not enable auto-merge.
> 6. Keep GitHub Actions default workflow permissions read-only.
> 7. Do not grant write permissions to scheduled or untrusted workflows.
> 8. Review any workflow requesting `contents: write`, pull-request write access, secret access, or deployment access. Report it and leave it unchanged unless the owner explicitly authorizes a separate release workflow.
> 9. Do not add, print, rotate, or expose credentials in source files, logs, Markdown, artifacts, URLs, or PR descriptions.
>
> Then prepare the provenance inputs. Locate the exact Nexus v1.4.240 release archive referenced by the restoration audit:
>
> - filename: `nexus-v1.4.240-release.zip`;
> - SHA-256: `63c2946d9bbdf049cb942605f3642ba477a20e475022b58a5b4a931e50c82613`;
> - Drive file ID: `1_H3ceS_gNZU-wX1_x7vVFrue7ByMRUAj`.
>
> If the archive is unavailable, do not substitute another ZIP. Mark provenance as unavailable and continue only with the current repository candidate. If the archive is available, verify its SHA-256, CRC, path safety, duplicate entries, symlink absence, and contents before extracting anything. Do not overwrite the repository with the archive. Extract it into a separate temporary directory and record:
>
> - archive hash and size;
> - source-tree hash method and result;
> - runtime module list;
> - test-module list;
> - wheel and sdist hashes;
> - validation logs and their interpreter version;
> - any embedded databases, caches, logs, or generated build output that must not enter Git.
>
> Compare the verified archive against the current repository by file path, public API, schema, tests, dependencies, and package version. Produce `docs/INPUT_COMPATIBILITY.md` or update it. Classify every artifact as `verified`, `incompatible`, `missing`, or `unverified`. Do not fabricate a commit association for the archive if it has no Git history.
>
> Prepare a clean Python 3.12 validation environment outside the repository. Install the candidate from source and separately install the wheel and sdist into fresh environments. Run all tests from outside the checkout with source paths removed. Capture:
>
> - Python and SQLite versions;
> - package version and import location;
> - full test count, failures, skips, and warnings;
> - compileall result;
> - wheel and sdist hashes;
> - CLI version and offline demo result;
> - backup and restore result;
> - exact Git SHA under test.
>
> Add or update tests for the integration-first gates in this order:
>
> 1. Versioned transactional migrations using an authentic earlier-version fixture. Inject a mid-migration failure and prove the original database remains usable.
> 2. Capability requirements in workflow specifications. Denied capability admission must create zero attempts, zero child processes, zero budget charges, and a durable denial event.
> 3. Atomic budget reservation with attempt and child allocation. Test concurrency, crash recovery, spent accounting, and conservation.
> 4. Durable delegate/wait-child steps with idempotent creation, restart races, depth/count/cycle limits, completion wake-up, and parent cancellation.
> 5. Secret references resolved only from configured environment/file sources. Prove synthetic secret values are absent from specs, events, memory, errors, logs, HTTP responses, and artifacts, while authorized children receive only explicitly allowed values.
> 6. Durable transition telemetry that reconciles with database outcomes after restart and uses bounded labels/cardinality.
> 7. Mixed multi-worker qualification with at least 1,000 recorded transitions, controlled worker kills, waits, retries, cleanup, and no orphan children.
>
> For each gate, use these statuses only: `implemented and tested locally`, `verified in hosted CI`, `prepared but unverified`, `blocked by named external dependency`, or `not implemented`.
>
> Update `docs/ACCEPTANCE_MATRIX.md`, `DELIVERY_REPORT.md`, `KNOWN_ISSUES.md`, and `RESUME.md` with exact commands, SHAs, test output, failures, and unsupported guarantees. Do not use a completion percentage.
>
> Before any external setting change, show the exact proposed setting, current value, and impact. Ask for confirmation if the change affects branch protection, Actions permissions, secrets, billing, publication, merge state, or external repositories. Never infer approval from silence.
>
> Finish by committing only source, tests, documentation, and reproducible evidence. Exclude databases, credentials, virtual environments, caches, build directories, generated metadata, and unverified archives. Push the feature branch and update the draft PR. Do not mark it ready and do not merge.

## Settings that require explicit owner confirmation

Manus should stop and request confirmation before changing any of the following:

- branch-protection bypass rules or administrator enforcement;
- GitHub Actions permissions or workflow write scopes;
- repository secrets, environment secrets, or external connector credentials;
- release publication, package indexes, Docker registries, or public deployments;
- PR draft/ready state, auto-merge, merge, branch deletion, or force-push;
- access to a private Drive/archive file;
- any paid provider, customer environment, or external service.

The confirmation request should show the exact setting, old value, new value, affected repository/environment, and rollback method.

## Recommended target settings

For the current development phase, use these defaults:

- `main`: pull-request-only, no force-push, no deletion.
- Required check: the repository’s Python 3.12 CI test job at the exact PR head.
- Actions default token: read-only.
- Scheduled workflows: read-only and no access to release secrets.
- Releases: disabled until the candidate passes exact-head source, wheel, sdist, migration, recovery, and installation qualification.
- PR #6: draft, no auto-merge.
- Archive provenance: verified by hash and stored outside Git unless the owner intentionally adds a small manifest.
- Secrets: references only; raw values never in source, test fixtures, reports, logs, or artifacts.
- Public HTTP exposure: disabled; use loopback or an explicitly secured reverse proxy.

## Completion evidence Manus must return

Manus should return a concise report containing the before-state and after-state settings, the exact candidate SHA, PR URL and state, hosted CI run URL and conclusion, archive hash if available, all local validation commands and counts, changed files, remaining failed or unverified gates, and rollback instructions for every changed setting.

A green CI result from an earlier commit does not validate a later commit. Every claim must identify the exact SHA that produced its evidence.
