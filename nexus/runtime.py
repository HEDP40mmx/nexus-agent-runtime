"""Single-host SQLite job state with bounded claims and per-claim fencing."""

import json
import math
import sqlite3
import time
import uuid


def _positive_seconds(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f'{name} must be a positive finite number')
    try:
        valid = math.isfinite(value) and value > 0
    except OverflowError:
        valid = False
    if not valid:
        raise ValueError(f'{name} must be a positive finite number')
    return value


class Runtime:
    """Durable job queue; callers must use each claim's opaque lease_token.

    owner is a diagnostic label, not authority to modify a running job.
    A lease protects database transitions, not external side effects.
    """

    def __init__(self, path='nexus.db', clock=time.time):
        self.path = str(path)
        self.clock = clock
        self.db = sqlite3.connect(self.path, isolation_level=None, timeout=10)
        self.db.row_factory = sqlite3.Row
        try:
            # The legacy job queue and v1 workflow engine have distinct schemas.
            # Refuse before changing journal mode or touching either's tables.
            if self.db.execute('PRAGMA user_version').fetchone()[0] != 0:
                raise ValueError('Runtime requires its legacy job database; use Store for v1 workflows')
            self.db.execute('PRAGMA busy_timeout=10000')
            self.db.execute('PRAGMA journal_mode=WAL')
            self.db.execute('BEGIN IMMEDIATE')
            self.db.execute('''
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY, payload TEXT NOT NULL, state TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0, max_attempts INTEGER NOT NULL,
                    available_at REAL NOT NULL, lease_until REAL, owner TEXT,
                    result TEXT, error TEXT, lease_token TEXT)
            ''')
            columns = {row['name'] for row in self.db.execute('PRAGMA table_info(jobs)')}
            if 'lease_token' not in columns:
                # Old claims get no new authority and must expire normally.
                self.db.execute('ALTER TABLE jobs ADD COLUMN lease_token TEXT')
            self.db.execute('''
                CREATE TABLE IF NOT EXISTS signals (
                    job_id TEXT NOT NULL, name TEXT NOT NULL, payload TEXT NOT NULL,
                    PRIMARY KEY(job_id, name))
            ''')
            self.db.execute('COMMIT')
        except Exception:
            if self.db.in_transaction:
                self.db.execute('ROLLBACK')
            self.db.close()
            raise

    def submit(self, payload, max_attempts=3, job_id=None):
        if type(max_attempts) is not int or not 1 <= max_attempts <= 100:
            raise ValueError('max_attempts must be an integer between 1 and 100')
        job_id = job_id or str(uuid.uuid4())
        self.db.execute(
            'INSERT INTO jobs(id,payload,state,max_attempts,available_at) VALUES(?,?,?,?,?)',
            (job_id, json.dumps(payload, allow_nan=False), 'queued', max_attempts, self.clock()),
        )
        return job_id

    def get(self, job_id):
        row = self.db.execute('SELECT * FROM jobs WHERE id=?', (job_id,)).fetchone()
        return dict(row) if row else None

    def claim(self, owner, lease_seconds=30):
        if not isinstance(owner, str) or not owner.strip():
            raise ValueError('owner must be a nonempty string')
        _positive_seconds(lease_seconds, 'lease_seconds')
        now = self.clock()
        lease_until = now + lease_seconds
        if not math.isfinite(lease_until):
            raise ValueError('lease deadline must be finite')
        self.db.execute('BEGIN IMMEDIATE')
        try:
            # Crashed attempts consume the same persisted budget as failures.
            self.db.execute('''
                UPDATE jobs SET state='failed', error='Attempt budget exhausted',
                    owner=NULL, lease_until=NULL, lease_token=NULL
                WHERE attempts>=max_attempts AND
                    (state='queued' OR (state='running' AND lease_until<=?))
            ''', (now,))
            row = self.db.execute('''
                SELECT id FROM jobs WHERE attempts<max_attempts AND
                    ((state='queued' AND available_at<=?) OR
                     (state='running' AND lease_until<=?))
                ORDER BY available_at, id LIMIT 1
            ''', (now, now)).fetchone()
            if row is None:
                self.db.execute('COMMIT')
                return None
            self.db.execute('''
                UPDATE jobs SET state='running', owner=?, lease_until=?,
                    lease_token=?, attempts=attempts+1 WHERE id=?
            ''', (owner, lease_until, uuid.uuid4().hex, row['id']))
            result = self.get(row['id'])
            self.db.execute('COMMIT')
            return result
        except Exception:
            self.db.execute('ROLLBACK')
            raise

    def heartbeat(self, job_id, lease_token, lease_seconds=30):
        _positive_seconds(lease_seconds, 'lease_seconds')
        now = self.clock()
        lease_until = now + lease_seconds
        if not math.isfinite(lease_until):
            raise ValueError('lease deadline must be finite')
        result = self.db.execute('''
            UPDATE jobs SET lease_until=? WHERE id=? AND lease_token=?
                AND state='running' AND lease_until>?
        ''', (lease_until, job_id, lease_token, now))
        return result.rowcount == 1

    def complete(self, job_id, lease_token, result):
        changed = self.db.execute('''
            UPDATE jobs SET state='completed', result=?, error=NULL,
                owner=NULL, lease_until=NULL, lease_token=NULL
            WHERE id=? AND lease_token=? AND state='running' AND lease_until>?
        ''', (json.dumps(result, allow_nan=False), job_id, lease_token, self.clock()))
        return changed.rowcount == 1

    def fail(self, job_id, lease_token, error, base_delay=2):
        _positive_seconds(base_delay, 'base_delay')
        now = self.clock()
        self.db.execute('BEGIN IMMEDIATE')
        try:
            row = self.db.execute('''
                SELECT attempts, max_attempts FROM jobs WHERE id=? AND lease_token=?
                    AND state='running' AND lease_until>?
            ''', (job_id, lease_token, now)).fetchone()
            if row is None:
                self.db.execute('COMMIT')
                return False
            exhausted = row['attempts'] >= row['max_attempts']
            try:
                delay = min(3600.0, math.ldexp(float(base_delay),
                                            min(row['attempts'] - 1, 1100)))
            except OverflowError:
                delay = 3600.0
            self.db.execute('''
                UPDATE jobs SET state=?, available_at=?, error=?, owner=NULL,
                    lease_until=NULL, lease_token=NULL WHERE id=?
            ''', ('failed' if exhausted else 'queued', now + delay, str(error), job_id))
            self.db.execute('COMMIT')
            return True
        except Exception:
            self.db.execute('ROLLBACK')
            raise

    def signal(self, job_id, name, payload):
        if self.get(job_id) is None:
            raise KeyError(job_id)
        self.db.execute(
            'INSERT OR REPLACE INTO signals VALUES(?,?,?)',
            (job_id, name, json.dumps(payload, allow_nan=False)),
        )

    def read_signal(self, job_id, name):
        row = self.db.execute(
            'SELECT payload FROM signals WHERE job_id=? AND name=?', (job_id, name),
        ).fetchone()
        return json.loads(row['payload']) if row else None

    def close(self):
        self.db.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()
