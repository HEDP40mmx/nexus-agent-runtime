CREATE TABLE runtime_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE runs (
    run_id TEXT PRIMARY KEY,
    request_key TEXT NOT NULL UNIQUE,
    spec_json TEXT NOT NULL,
    spec_digest TEXT NOT NULL CHECK (length(spec_digest) = 64),
    status TEXT NOT NULL CHECK (status IN
      ('queued','running','retry_wait','waiting_approval','waiting_signal',
       'succeeded','failed','cancelled')),
    next_step INTEGER NOT NULL DEFAULT 0 CHECK (next_step >= 0),
    lease_owner TEXT,
    lease_epoch INTEGER NOT NULL DEFAULT 0 CHECK (lease_epoch >= 0),
    lease_until_ms INTEGER,
    ready_at_ms INTEGER NOT NULL,
    created_ms INTEGER NOT NULL,
    updated_ms INTEGER NOT NULL,
    error_code TEXT,
    CHECK ((lease_owner IS NULL) = (lease_until_ms IS NULL)),
    CHECK ((status = 'running') = (lease_owner IS NOT NULL))
);

CREATE TABLE steps (
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    step_id TEXT NOT NULL,
    ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
    kind TEXT NOT NULL CHECK (kind IN ('action','wait_signal')),
    status TEXT NOT NULL CHECK (status IN
      ('pending','running','retry_wait','waiting_approval','waiting_signal',
       'succeeded','failed','cancelled')),
    action_name TEXT,
    action_version TEXT,
    signal_name TEXT,
    input_json TEXT NOT NULL,
    effect_digest TEXT,
    require_approval INTEGER NOT NULL DEFAULT 0 CHECK (require_approval IN (0,1)),
    approval_ttl_ms INTEGER NOT NULL DEFAULT 86400000 CHECK (approval_ttl_ms > 0),
    max_attempts INTEGER NOT NULL DEFAULT 3 CHECK (max_attempts BETWEEN 1 AND 20),
    attempts_started INTEGER NOT NULL DEFAULT 0
      CHECK (attempts_started BETWEEN 0 AND max_attempts),
    base_delay_ms INTEGER NOT NULL DEFAULT 1000 CHECK (base_delay_ms >= 0),
    cap_delay_ms INTEGER NOT NULL DEFAULT 60000 CHECK (cap_delay_ms >= base_delay_ms),
    timeout_ms INTEGER NOT NULL DEFAULT 60000 CHECK (timeout_ms > 0),
    due_at_ms INTEGER,
    result_json TEXT,
    error_code TEXT,
    PRIMARY KEY (run_id, step_id),
    UNIQUE (run_id, ordinal),
    CHECK (
      (kind = 'action' AND action_name IS NOT NULL AND action_version IS NOT NULL
       AND effect_digest IS NOT NULL AND length(effect_digest) = 64
       AND signal_name IS NULL)
      OR
      (kind = 'wait_signal' AND signal_name IS NOT NULL AND action_name IS NULL
       AND action_version IS NULL AND effect_digest IS NULL AND require_approval = 0)
    )
);

CREATE TABLE attempts (
    run_id TEXT NOT NULL,
    step_id TEXT NOT NULL,
    attempt_no INTEGER NOT NULL CHECK (attempt_no >= 1),
    lease_owner TEXT NOT NULL,
    lease_epoch INTEGER NOT NULL CHECK (lease_epoch >= 1),
    status TEXT NOT NULL CHECK (status IN
      ('running','succeeded','failed','abandoned','cancelled')),
    started_ms INTEGER NOT NULL,
    finished_ms INTEGER,
    error_code TEXT,
    PRIMARY KEY (run_id, step_id, attempt_no),
    FOREIGN KEY (run_id, step_id) REFERENCES steps(run_id, step_id)
);
CREATE UNIQUE INDEX one_running_attempt
    ON attempts(run_id, step_id) WHERE status = 'running';

CREATE TABLE approvals (
    approval_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    step_id TEXT NOT NULL,
    effect_digest TEXT NOT NULL CHECK (length(effect_digest) = 64),
    decision TEXT NOT NULL CHECK (decision IN ('pending','approved','denied','expired')),
    created_ms INTEGER NOT NULL,
    expires_ms INTEGER NOT NULL,
    decided_ms INTEGER,
    decided_by TEXT,
    UNIQUE (run_id, step_id),
    FOREIGN KEY (run_id, step_id) REFERENCES steps(run_id, step_id),
    CHECK (expires_ms > created_ms),
    CHECK ((decision = 'pending') = (decided_ms IS NULL)),
    CHECK ((decided_ms IS NULL) = (decided_by IS NULL))
);

CREATE TABLE signals (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    message_id TEXT NOT NULL,
    name TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    payload_digest TEXT NOT NULL CHECK (length(payload_digest) = 64),
    created_ms INTEGER NOT NULL,
    consumed_by_step_id TEXT,
    consumed_ms INTEGER,
    UNIQUE (run_id, message_id),
    FOREIGN KEY (run_id, consumed_by_step_id) REFERENCES steps(run_id, step_id),
    CHECK ((consumed_by_step_id IS NULL) = (consumed_ms IS NULL))
);
CREATE UNIQUE INDEX one_signal_per_wait
    ON signals(run_id, consumed_by_step_id) WHERE consumed_by_step_id IS NOT NULL;

CREATE TABLE events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    step_id TEXT,
    kind TEXT NOT NULL,
    at_ms INTEGER NOT NULL,
    payload_json TEXT NOT NULL,
    FOREIGN KEY (run_id, step_id) REFERENCES steps(run_id, step_id)
);
CREATE INDEX runnable_runs ON runs(status, ready_at_ms, created_ms, run_id);
CREATE INDEX approval_expiry ON approvals(decision, expires_ms);
CREATE INDEX signal_inbox ON signals(run_id, name, seq)
    WHERE consumed_by_step_id IS NULL;
CREATE INDEX run_events ON events(run_id, event_id);
