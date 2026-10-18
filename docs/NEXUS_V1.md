# Nexus v1 atomic-state milestone

This is the first implementation milestone from the fresh-v1 plan. It provides
an installable Python 3.12 package, immutable linear workflow specifications,
strict bounded JSON, atomic submission and audit events, request-key
idempotency, coherent inspection, schema/journal guards and verified snapshot
backup. It does not yet execute workflow steps.

The saved `Runtime` job-queue API and its 35 existing tests are retained. That
legacy queue uses a different database schema. The new `Store` refuses to modify
an unversioned legacy database; `Runtime` refuses a versioned workflow database.
Use separate paths. No automatic conversion is implemented. The legacy API's
existing lease, retry and last-value signal semantics remain separate from the
planned workflow engine.

## Install and inspect

```sh
python3.12 -m pip install -e '.[test]'
python3.12 -m nexus --version
python3.12 -m nexus init --database /tmp/nexus-workflow.db --journal auto
python3.12 -m pytest -q
```

```python
from nexus import Store, Nexus, RunSpec, StepSpec

with Store('/tmp/nexus-workflow.db') as store:
    client = Nexus(store)
    specification = RunSpec((
        StepSpec.action(id='hello', action='echo', version='1',
                        input={'text': 'hello'}),
        StepSpec.wait_signal(id='receipt', name='receipt'),
    ))
    run_id = client.submit(specification, request_key='example-1')
    print(client.get_run(run_id))
    print(client.events(run_id))
```

One `Store` instance belongs to one thread/process. State transitions and their
events commit in explicit SQLite transactions. Inputs are frozen at construction,
normalized specifications are persisted, and replay of a request key with
different normalized content raises `Conflict`. No execution occurs on submit.

New databases choose WAL/FULL on the documented fixed SQLite release families,
otherwise DELETE/EXTRA. Existing workflow databases retain their recorded mode.
Unsafe explicit WAL, unknown schema versions and nonempty unversioned databases
are rejected. Runtime-owned tables and schema metadata initialize in one
transaction. This is a single-host local-file design.

`Store.backup(new_path)` uses SQLite online backup and checks integrity and
foreign keys. Existing destinations are never overwritten. This milestone tests
a committed snapshot; live-write/worker-continuation qualification comes later.

## Remaining acceptance work

The remaining plan requires fenced workflow claims/attempts, supervised trusted
handlers and heartbeat, deterministic recovery/retries, approval decisions,
signal inbox consumption, cancellation, authenticated HTTP, preflight, complete
CLI commands, installed end-to-end demo and the specified crash/concurrency
tests. Models may specify approval and retry requirements, but no worker exists
in this milestone to consume them. No such runtime behavior is claimed.

The distribution version `1.0.0a1` identifies this development candidate; it is
not a published alpha release. The `nexus` CLI currently exposes `init` and
`--version`. Other commands are added only as their behavior is implemented.

All existing upstream files are preserved. No workflow, repository setting,
main-branch commit, merge or release is included in this checkpoint.
