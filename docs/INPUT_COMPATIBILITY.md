# Nexus input compatibility record

Recorded 2026-10-23 before further implementation work on `manus/nexus-v1-complete-20261023`.

## Repository state preserved

- Repository: `HEDP40mmx/nexus-agent-runtime`
- Main: `aa6eead48329fc154aba803d41935a1ad75a623d`
- Reviewed PR #5 head before this record: `97663dfc436a2ce0d5b196a389e8bec9dcde26f2`
- Working tree: clean except for the pre-existing untracked `NEXUS_MANUS_FINAL_DELIVERY_2026-10-23.zip`
- PR #5: draft; main was not modified

## Provenance results

| Artifact | Classification | Evidence and decision |
|---|---|---|
| Uploaded `NEXUS_MANUS_HANDOFF_2026-10-23.zip` | **verified** | SHA-256 `1ba506e3d829f645fef59a2cbaa31338402b9ba08dfca848d4d4ce22503220a2`; archive extracted successfully. |
| Handoff `INPUT_PROVENANCE.json` | **verified** | SHA-256 manifest entry passes; identifies main `aa6eead…` and the historical release’s expected digest. |
| Handoff `SHA256SUMS` | **verified** | `sha256sum -c` passed for all 75 supplied entries, including reference sources and nested inputs. |
| `NEXUS_V1_ATOMIC_STATE_2026-10-18.zip` | **verified** | Handoff manifest passes; nested manifest passes for source, tests, wheel, sdist, patch, and Git bundle. |
| Atomic Git bundle | **verified** | `git bundle verify` passes; contains `1ef8f9259fc5110c8232361982220bc2bcad2285` on `refs/heads/recovery/nexus-v1-fresh-20261018` and requires main `aa6eead…`. |
| Requested commit `1ef8f9259fc5110c8232361982220bc2bcad2285` | **verified in supplied bundle; missing from current remote clone** | The object is not in the current repository object database, but it is present and verifiable in the supplied atomic bundle. It is eligible for additive inspection/import, not a reason to rewrite PR history. |
| `nexus-v1.4.240-release.zip` raw archive | **missing from workspace** | No raw ZIP is present in `/home/ubuntu`, `/home/ubuntu/upload`, or the extracted handoff. The provenance record supplies expected SHA-256 `63c2946d9bbdf049cb942605f3642ba477a20e475022b58a5b4a931e50c82613`; this digest was not recomputed locally. |
| Historical v1.4.240 source | **unverified for this task** | The supplied audit reports a prior Drive verification and a 56-file allowlist, but the raw archive is unavailable here. Reference files are explicitly marked legacy and are not fresh-v1 schema/API inputs. No historical release source was imported. |
| `NEXUS_ARCHIVE_RESTORATION_KIT_2026-10-19.zip` | **verified as supplied; incompatible as fresh-v1 source** | Checksums pass, but its purpose is restoring legacy v1.4.240 source. `REFERENCE_BOUNDARIES.md` says not to mix its schema/API with fresh-v1. |
| `nexus-worker-hardened.zip` and worker patch | **verified as supplied; incompatible as whole-tree import** | Checksums pass. They are a separate queue-worker component with a different package/API boundary; useful for behavior ideas only. |

## Compatibility comparison

The atomic checkpoint is the compatible fresh-v1 ancestor of PR #5:

- Same project name/version, Python requirement, dependencies, test extra, package discovery, schema package data, and pytest configuration.
- Same initial source layout for `models.py`, `runtime.py`, `schema.sql`, `service.py`, `store.py`, CLI files, and the five initial test modules.
- PR #5 adds the versioned registry, durable engine, worker facade, approval/cancellation controls, durable signals, automatic heartbeats, expired-lease reconciliation, and corresponding tests. These are additive extensions from the verified atomic checkpoint.
- PR #5 intentionally differs from the atomic checkpoint in `nexus/__init__.py` and `nexus/service.py`; those differences are the newer implementation, not evidence of incompatibility.
- PR #5 has 10 top-level package Python files and 9 test modules versus the atomic checkpoint’s 7 package Python files and 5 test modules. The added files are implementation/test slices, not a schema replacement.
- The atomic checkpoint and PR #5 both use SQLite schema version 1 and the same fresh-v1 database boundary. No legacy v1.4.240 database or source tree was copied into PR #5.

## Implementation decision

The canonical fresh-v1 checkpoint is verified and compatible, so preserve PR #5 and continue additively from `97663df…`. Import only missing components from the supplied atomic bundle when required; do not replace newer PR code with the older checkpoint. Treat the historical v1.4.240 release as unverified and legacy-only until its raw archive is supplied and its expected digest is recomputed.

No historical test result is being claimed from the unavailable raw release. The atomic bundle’s recorded validation is provenance evidence only; fresh validation must be rerun on the current PR head after every implementation slice.
