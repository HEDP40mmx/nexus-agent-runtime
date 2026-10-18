import json
import multiprocessing
import sqlite3

import pytest

from nexus import Runtime


@pytest.fixture
def runtime(tmp_path):
    now = [100.0]
    with Runtime(tmp_path / 'jobs.sqlite', clock=lambda: now[0]) as instance:
        yield instance, now


def test_persistence(tmp_path):
    path = tmp_path / 'jobs.sqlite'
    with Runtime(path) as r:
        job = r.submit({'task': 'x'})
    with Runtime(path) as r:
        assert r.get(job)['state'] == 'queued'
        assert json.loads(r.get(job)['payload']) == {'task': 'x'}


def test_claim_complete_and_owner(runtime):
    r, _ = runtime
    job = r.submit({'x': 1})
    claim = r.claim('worker')
    assert claim['id'] == job
    assert claim['owner'] == 'worker'
    assert not r.complete(job, 'worker', {})
    assert not r.complete(job, 'wrong-token', {})
    assert r.complete(job, claim['lease_token'], {'ok': True})
    assert r.get(job)['lease_token'] is None
    assert r.claim('worker') is None
    assert not r.complete(job, claim['lease_token'], {'late': True})


def test_retry_backoff_and_terminal(runtime):
    r, now = runtime
    job = r.submit({}, max_attempts=3)
    claim = r.claim('a')
    assert r.fail(job, claim['lease_token'], 'first failure')
    assert r.get(job)['available_at'] == 102.0
    assert r.claim('a') is None
    now[0] = 102.0
    claim = r.claim('a')
    assert claim['attempts'] == 2
    assert r.fail(job, claim['lease_token'], 'second failure')
    assert r.get(job)['available_at'] == 106.0
    now[0] = 106.0
    claim = r.claim('a')
    assert r.fail(job, claim['lease_token'], 'last failure')
    assert r.get(job)['state'] == 'failed'
    assert r.claim('a') is None


@pytest.mark.parametrize('second_owner', ['a', 'b'])
def test_reclaimed_lease_rejects_all_stale_transitions(runtime, second_owner):
    r, now = runtime
    job = r.submit({})
    first = r.claim('a', lease_seconds=5)
    now[0] = 105.0
    second = r.claim(second_owner)
    assert second['attempts'] == 2
    assert first['lease_token'] != second['lease_token']
    before = r.get(job)
    assert not r.heartbeat(job, first['lease_token'])
    assert not r.fail(job, first['lease_token'], 'stale error')
    assert not r.complete(job, first['lease_token'], {'stale': True})
    assert r.get(job) == before
    assert r.complete(job, second['lease_token'], {'fresh': True})


@pytest.mark.parametrize('budget', [1, 2, 3])
def test_repeated_crashes_consume_attempt_budget(runtime, budget):
    r, now = runtime
    job = r.submit({}, max_attempts=budget)
    for attempt in range(1, budget + 1):
        claim = r.claim('same-worker', lease_seconds=1)
        assert claim['attempts'] == attempt
        now[0] += 1
    assert r.claim('same-worker') is None
    row = r.get(job)
    assert row['state'] == 'failed'
    assert row['attempts'] == budget
    assert row['lease_token'] is None
    assert row['error'] == 'Attempt budget exhausted'
    now[0] += 1000
    assert r.claim('same-worker') is None
    assert r.get(job)['attempts'] == budget


def test_final_active_attempt_can_finish_before_expiry(runtime):
    r, now = runtime
    job = r.submit({}, max_attempts=1)
    claim = r.claim('a', lease_seconds=5)
    now[0] = 104.0
    assert r.claim('b') is None
    assert r.get(job)['state'] == 'running'
    assert r.complete(job, claim['lease_token'], {})


@pytest.mark.parametrize('operation', ['heartbeat', 'complete', 'fail'])
def test_expired_token_is_rejected_before_reclaim(runtime, operation):
    r, now = runtime
    job = r.submit({})
    claim = r.claim('a', lease_seconds=1)
    now[0] = 101.0
    args = [] if operation == 'heartbeat' else [{}]
    assert not getattr(r, operation)(job, claim['lease_token'], *args)
    assert r.get(job)['state'] == 'running'


def test_heartbeat_extends_current_lease(runtime):
    r, now = runtime
    job = r.submit({})
    claim = r.claim('a', lease_seconds=5)
    now[0] = 104.0
    assert r.heartbeat(job, claim['lease_token'], lease_seconds=10)
    assert r.get(job)['lease_until'] == 114.0
    now[0] = 106.0
    assert r.claim('b') is None
    assert r.complete(job, claim['lease_token'], {})


def test_retry_deadline_and_fencing_survive_reopen(tmp_path):
    path = tmp_path / 'jobs.sqlite'
    now = [100.0]
    with Runtime(path, clock=lambda: now[0]) as r:
        job = r.submit({})
        first = r.claim('a')
        assert r.fail(job, first['lease_token'], 'retry')
    with Runtime(path, clock=lambda: now[0]) as r:
        assert r.claim('a') is None
        now[0] = 102.0
        second = r.claim('a')
        assert second['attempts'] == 2
        assert not r.complete(job, first['lease_token'], {})
        assert r.complete(job, second['lease_token'], {})
        assert r.get(job)['error'] is None


def test_crash_budget_survives_reopen(tmp_path):
    path = tmp_path / 'jobs.sqlite'
    now = [100.0]
    with Runtime(path, clock=lambda: now[0]) as r:
        job = r.submit({}, max_attempts=1)
        r.claim('worker', lease_seconds=1)
    now[0] = 101.0
    with Runtime(path, clock=lambda: now[0]) as r:
        assert r.claim('worker') is None
        assert r.get(job)['state'] == 'failed'
        assert r.get(job)['attempts'] == 1


def test_exhausted_job_does_not_block_other_work(runtime):
    r, now = runtime
    exhausted = r.submit({}, job_id='a', max_attempts=1)
    r.claim('worker', lease_seconds=1)
    healthy = r.submit({}, job_id='b')
    now[0] = 101.0
    assert r.claim('worker')['id'] == healthy
    assert r.get(exhausted)['state'] == 'failed'


def test_failed_attempts_and_crashes_share_one_budget(runtime):
    r, now = runtime
    job = r.submit({}, max_attempts=2)
    claim = r.claim('worker')
    assert r.fail(job, claim['lease_token'], 'retry')
    now[0] = 102.0
    assert r.claim('worker', lease_seconds=1)['attempts'] == 2
    now[0] = 103.0
    assert r.claim('worker') is None
    assert r.get(job)['state'] == 'failed'


@pytest.mark.parametrize('base_delay', [7200, 1e308])
def test_backoff_is_capped(runtime, base_delay):
    r, _ = runtime
    job = r.submit({})
    claim = r.claim('worker')
    assert r.fail(job, claim['lease_token'], 'retry', base_delay=base_delay)
    assert r.get(job)['available_at'] == 3700.0


@pytest.mark.parametrize('value', [True, 0, -1, 101, 1.5, '3', None])
def test_invalid_attempt_budget_is_rejected(runtime, value):
    r, _ = runtime
    with pytest.raises(ValueError):
        r.submit({}, max_attempts=value)
    assert r.claim('worker') is None


@pytest.mark.parametrize('value', [True, 0, -1, float('nan'), float('inf'), '30'])
def test_invalid_lease_is_rejected_without_consuming_attempt(runtime, value):
    r, _ = runtime
    job = r.submit({})
    with pytest.raises(ValueError):
        r.claim('worker', lease_seconds=value)
    assert r.get(job)['attempts'] == 0
    assert r.get(job)['state'] == 'queued'


def test_signals_survive_reopen(tmp_path):
    path = tmp_path / 'jobs.sqlite'
    with Runtime(path) as r:
        job = r.submit({})
        r.signal(job, 'notice', {'yes': True})
    with Runtime(path) as r:
        assert r.read_signal(job, 'notice') == {'yes': True}
        assert r.read_signal(job, 'missing') is None
        with pytest.raises(KeyError):
            r.signal('absent-job', 'notice', {})


def test_legacy_schema_preserves_jobs_and_fences_old_claims(tmp_path):
    path = tmp_path / 'legacy.sqlite'
    with sqlite3.connect(path) as db:
        db.execute('''CREATE TABLE jobs (
            id TEXT PRIMARY KEY, payload TEXT NOT NULL, state TEXT NOT NULL,
            attempts INTEGER NOT NULL DEFAULT 0, max_attempts INTEGER NOT NULL,
            available_at REAL NOT NULL, lease_until REAL, owner TEXT,
            result TEXT, error TEXT)''')
        db.execute('''INSERT INTO jobs
            (id,payload,state,attempts,max_attempts,available_at,lease_until,owner)
            VALUES ('old','{}','running',1,3,100,105,'worker')''')
        db.execute('''CREATE TABLE signals (
            job_id TEXT NOT NULL, name TEXT NOT NULL, payload TEXT NOT NULL,
            PRIMARY KEY(job_id,name))''')
        db.execute("INSERT INTO signals VALUES ('old','notice','42')")
    now = [100.0]
    with Runtime(path, clock=lambda: now[0]) as r:
        assert r.get('old')['lease_token'] is None
        assert r.read_signal('old', 'notice') == 42
        assert not r.complete('old', 'worker', {})
        assert not r.complete('old', None, {})
        assert r.claim('worker') is None
        now[0] = 105.0
        claim = r.claim('worker')
        assert claim['attempts'] == 2
        assert r.complete('old', claim['lease_token'], {'migrated': True})
    with Runtime(path) as r:
        assert r.get('old')['state'] == 'completed'


def _contend_for_job(path, ready, start, results):
    with Runtime(path) as r:
        ready.put(True)
        if not start.wait(10):
            raise TimeoutError('claim barrier timed out')
        claimed = r.claim('same-worker', lease_seconds=60)
        results.put(None if claimed is None else claimed['lease_token'])


def test_two_processes_cannot_claim_same_job(tmp_path):
    path = str(tmp_path / 'jobs.sqlite')
    with Runtime(path) as r:
        job = r.submit({})
    ctx = multiprocessing.get_context('spawn')
    ready, results, start = ctx.Queue(), ctx.Queue(), ctx.Event()
    processes = [ctx.Process(target=_contend_for_job, args=(path, ready, start, results))
                 for _ in range(2)]
    try:
        for process in processes:
            process.start()
        for _ in processes:
            assert ready.get(timeout=15) is True
        start.set()
        claims = [results.get(timeout=15) for _ in processes]
        assert sum(token is not None for token in claims) == 1
        for process in processes:
            process.join(timeout=15)
            assert process.exitcode == 0
        with Runtime(path) as r:
            assert r.get(job)['attempts'] == 1
            assert r.get(job)['lease_token'] in claims
    finally:
        for process in processes:
            if process.pid is not None:
                if process.is_alive():
                    process.terminate()
                process.join(timeout=5)
        ready.close()
        results.close()
