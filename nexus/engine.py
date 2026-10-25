"""Durable workflow transitions for claims, attempts, retries and fencing."""
from dataclasses import dataclass
import sqlite3
import threading
import uuid
from .models import (ActionContext, LeaseLost, PermanentError, RetryableError,
                     TERMINAL, digest, canonical)
from .supervisor import execute as execute_supervised
from .extensions import ensure_tables

LEASE_MS = 30_000


@dataclass(frozen=True)
class Claim:
    run_id: str
    step_id: str
    owner: str
    epoch: int
    attempt_no: int | None
    timeout_ms: int
    action: str | None
    version: str | None
    input: dict
    effect_key: str | None
    kind: str = "action"
    signal_name: str | None = None


class Engine:
    def __init__(self, store, registry=None, lease_ms=LEASE_MS, heartbeat_interval_ms=None,
                 execution_profile="trusted", resource_limits=None):
        self.store = store
        self.db = store.db
        self.registry = registry
        self.lease_ms = lease_ms
        self.heartbeat_interval_ms = heartbeat_interval_ms or max(1, lease_ms // 6)
        self.execution_profile = execution_profile
        self.resource_limits = resource_limits
        ensure_tables(store)
        if self.heartbeat_interval_ms >= lease_ms:
            raise ValueError("heartbeat interval must be shorter than lease duration")

    def _claim_row(self, owner=None):
        now = self.store.now_ms()
        owner = owner or uuid.uuid4().hex
        with self.store.tx():
            row = self.db.execute("""SELECT r.*, s.step_id, s.kind, s.status step_status,
                    s.action_name, s.action_version, s.signal_name, s.input_json, s.timeout_ms,
                    s.effect_digest, s.require_approval, s.approval_ttl_ms,
                    s.attempts_started, s.max_attempts
                FROM runs r JOIN steps s ON s.run_id=r.run_id AND s.ordinal=r.next_step
                WHERE r.status IN ('queued','retry_wait') AND r.ready_at_ms<=?
                ORDER BY r.ready_at_ms,r.created_ms,r.run_id LIMIT 1""", (now,)).fetchone()
            if row is None:
                return None
            denied = self.db.execute("""SELECT sc.capability FROM step_capabilities sc
                WHERE sc.run_id=? AND sc.step_id=? AND NOT EXISTS (
                    SELECT 1 FROM capability_grants cg
                    WHERE cg.run_id=sc.run_id AND cg.scope=sc.step_id
                      AND cg.capability=sc.capability AND cg.revoked_ms IS NULL)
                ORDER BY sc.capability""", (row["run_id"], row["step_id"])).fetchall()
            if denied:
                capabilities = [item["capability"] for item in denied]
                self.db.execute("UPDATE steps SET status='failed',error_code='CAPABILITY_DENIED' WHERE run_id=? AND step_id=?",
                                (row["run_id"], row["step_id"]))
                self.db.execute("""UPDATE runs SET status='failed',error_code='CAPABILITY_DENIED',
                    lease_owner=NULL,lease_until_ms=NULL,updated_ms=? WHERE run_id=?""",
                                (now, row["run_id"]))
                self.store.event(row["run_id"], "capability_denied", now,
                                 {"capabilities": capabilities}, row["step_id"])
                return None
            if row["kind"] == "action" and row["require_approval"]:
                approval = self.db.execute("SELECT * FROM approvals WHERE run_id=? AND step_id=?",
                                           (row["run_id"], row["step_id"])).fetchone()
                if approval is None or approval["decision"] == "pending":
                    if approval is not None and now >= approval["expires_ms"]:
                        self.db.execute("UPDATE approvals SET decision='expired',decided_ms=?,decided_by='system' WHERE approval_id=?",
                                        (now, approval["approval_id"]))
                    approval_id = uuid.uuid4().hex
                    if approval is None:
                        self.db.execute("""INSERT INTO approvals(approval_id,run_id,step_id,effect_digest,
                            decision,created_ms,expires_ms) VALUES (?,?,?,?,'pending',?,?)""",
                                        (approval_id, row["run_id"], row["step_id"], row["effect_digest"],
                                         now, now + row["approval_ttl_ms"]))
                    self.db.execute("""UPDATE runs SET status='waiting_approval',lease_owner=NULL,
                        lease_until_ms=NULL,updated_ms=? WHERE run_id=?""", (now, row["run_id"]))
                    self.db.execute("UPDATE steps SET status='waiting_approval' WHERE run_id=? AND step_id=?",
                                    (row["run_id"], row["step_id"]))
                    self.store.event(row["run_id"], "approval_requested", now,
                                     {"approval_id": approval_id}, row["step_id"])
                    return None
            epoch = row["lease_epoch"] + 1
            until = now + self.lease_ms
            self.db.execute("""UPDATE runs SET status='running', lease_owner=?, lease_epoch=?,
                lease_until_ms=?, updated_ms=? WHERE run_id=? AND status IN ('queued','retry_wait')
                AND ready_at_ms<=?""", (owner, epoch, until, now, row["run_id"], now))
            if self.db.execute("SELECT changes()").fetchone()[0] != 1:
                return None
            self.store.event(row["run_id"], "lease_claimed", now,
                             {"owner": owner, "lease_epoch": epoch}, row["step_id"])
            return self.db.execute("""SELECT r.*, s.step_id, s.kind, s.status step_status,
                    s.action_name, s.action_version, s.signal_name, s.input_json, s.timeout_ms,
                    s.effect_digest, s.attempts_started, s.max_attempts
                FROM runs r JOIN steps s ON s.run_id=r.run_id AND s.ordinal=r.next_step
                WHERE r.run_id=?""", (row["run_id"],)).fetchone()

    def claim(self, owner=None):
        row = self._claim_row(owner)
        if row is None:
            return None
        import json
        return Claim(row["run_id"], row["step_id"], row["lease_owner"], row["lease_epoch"],
                     None, row["timeout_ms"], row["action_name"], row["action_version"],
                     json.loads(row["input_json"]),
                     "nexus-v1:" + digest({"run_id": row["run_id"], "step_id": row["step_id"],
                                              "effect_digest": row["effect_digest"]}),
                     row["kind"], row["signal_name"])

    def consume_signal(self, claim):
        now = self.store.now_ms()
        with self.store.tx():
            run = self.db.execute("SELECT * FROM runs WHERE run_id=?", (claim.run_id,)).fetchone()
            self._assert_lease(run, claim, now)
            signal = self.db.execute("""SELECT * FROM signals WHERE run_id=? AND name=?
                AND consumed_by_step_id IS NULL ORDER BY seq LIMIT 1""",
                                     (claim.run_id, claim.signal_name)).fetchone()
            if signal is None:
                self.db.execute("UPDATE steps SET status='waiting_signal' WHERE run_id=? AND step_id=?",
                                (claim.run_id, claim.step_id))
                self.db.execute("""UPDATE runs SET status='waiting_signal',lease_owner=NULL,
                    lease_until_ms=NULL,updated_ms=? WHERE run_id=?""", (now, claim.run_id))
                self.store.event(claim.run_id, "signal_waiting", now,
                                 {"name": claim.signal_name}, claim.step_id)
                return False
            self.db.execute("""UPDATE signals SET consumed_by_step_id=?,consumed_ms=?
                WHERE seq=? AND consumed_by_step_id IS NULL""",
                            (claim.step_id, now, signal["seq"]))
            self.db.execute("UPDATE steps SET status='succeeded',result_json=? WHERE run_id=? AND step_id=?",
                            (signal["payload_json"], claim.run_id, claim.step_id))
            nxt = run["next_step"] + 1
            count = self.db.execute("SELECT count(*) FROM steps WHERE run_id=?", (claim.run_id,)).fetchone()[0]
            status = "succeeded" if nxt >= count else "queued"
            self.db.execute("""UPDATE runs SET status=?,next_step=?,lease_owner=NULL,
                lease_until_ms=NULL,ready_at_ms=?,updated_ms=? WHERE run_id=?""",
                            (status, nxt, now, now, claim.run_id))
            self.store.event(claim.run_id, "signal_consumed", now,
                             {"message_id": signal["message_id"], "name": signal["name"]}, claim.step_id)
            if status == "succeeded":
                self.store.event(claim.run_id, "run_succeeded", now, {})
            return True

    def reconcile_expired(self):
        """Recover claims whose persisted lease expired before a worker returned."""
        now = self.store.now_ms()
        recovered = 0
        with self.store.tx():
            rows = self.db.execute("""SELECT r.*, s.step_id, s.max_attempts, s.base_delay_ms,
                    s.cap_delay_ms, s.attempts_started
                FROM runs r JOIN steps s ON s.run_id=r.run_id AND s.ordinal=r.next_step
                WHERE r.status='running' AND r.lease_until_ms<=?
                ORDER BY r.lease_until_ms,r.run_id""", (now,)).fetchall()
            for row in rows:
                attempt = self.db.execute("""SELECT * FROM attempts WHERE run_id=? AND step_id=?
                    AND status='running' ORDER BY attempt_no DESC LIMIT 1""",
                                          (row["run_id"], row["step_id"])).fetchone()
                if attempt is None:
                    self.db.execute("""UPDATE runs SET status='queued',lease_owner=NULL,
                        lease_until_ms=NULL,ready_at_ms=?,updated_ms=? WHERE run_id=?""",
                                    (now, now, row["run_id"]))
                    self.store.event(row["run_id"], "claim_requeued", now,
                                     {"reason": "expired_before_attempt"}, row["step_id"])
                    recovered += 1
                    continue
                attempt_no = attempt["attempt_no"]
                self.db.execute("""UPDATE attempts SET status='abandoned',finished_ms=?,
                    error_code='LEASE_EXPIRED' WHERE run_id=? AND step_id=? AND attempt_no=?
                    AND status='running'""", (now, row["run_id"], row["step_id"], attempt_no))
                if row["attempts_started"] < row["max_attempts"]:
                    delay = min(row["cap_delay_ms"], row["base_delay_ms"] * 2 ** (attempt_no - 1))
                    due = row["lease_until_ms"] + delay
                    self.db.execute("""UPDATE steps SET status='retry_wait',due_at_ms=?,
                        error_code='LEASE_EXPIRED' WHERE run_id=? AND step_id=?""",
                                    (due, row["run_id"], row["step_id"]))
                    self.db.execute("""UPDATE runs SET status='retry_wait',ready_at_ms=?,
                        lease_owner=NULL,lease_until_ms=NULL,updated_ms=? WHERE run_id=?""",
                                    (due, now, row["run_id"]))
                    self.store.event(row["run_id"], "attempt_abandoned", now,
                                     {"attempt_no": attempt_no, "due_at_ms": due}, row["step_id"])
                else:
                    self.db.execute("""UPDATE steps SET status='failed',error_code='ATTEMPTS_EXHAUSTED'
                        WHERE run_id=? AND step_id=?""", (row["run_id"], row["step_id"]))
                    self.db.execute("""UPDATE runs SET status='failed',error_code='ATTEMPTS_EXHAUSTED',
                        lease_owner=NULL,lease_until_ms=NULL,updated_ms=? WHERE run_id=?""",
                                    (now, row["run_id"]))
                    self.store.event(row["run_id"], "run_failed", now,
                                     {"error_code": "ATTEMPTS_EXHAUSTED"}, row["step_id"])
                recovered += 1
        return recovered

    def allocate_attempt(self, claim):
        now = self.store.now_ms()
        with self.store.tx():
            row = self.db.execute("""SELECT r.*, s.* FROM runs r JOIN steps s ON s.run_id=r.run_id
                WHERE r.run_id=? AND s.step_id=?""", (claim.run_id, claim.step_id)).fetchone()
            self._assert_lease(row, claim, now)
            if row["attempts_started"] >= row["max_attempts"]:
                raise PermanentError("attempt budget exhausted")
            attempt = row["attempts_started"] + 1
            self.db.execute("UPDATE steps SET status='running', attempts_started=? WHERE run_id=? AND step_id=?",
                            (attempt, claim.run_id, claim.step_id))
            self.db.execute("""INSERT INTO attempts(run_id,step_id,attempt_no,lease_owner,lease_epoch,
                status,started_ms) VALUES (?,?,?,?,?,'running',?)""",
                            (claim.run_id, claim.step_id, attempt, claim.owner, claim.epoch, now))
            self.store.event(claim.run_id, "attempt_allocated", now,
                             {"attempt_no": attempt, "lease_epoch": claim.epoch}, claim.step_id)
            return Claim(**{**claim.__dict__, "attempt_no": attempt})

    def heartbeat(self, claim):
        now = self.store.now_ms()
        with self.store.tx():
            cur = self.db.execute("""UPDATE runs SET lease_until_ms=?,updated_ms=?
                WHERE run_id=? AND status='running' AND lease_owner=? AND lease_epoch=?
                AND lease_until_ms>?""", (now + self.lease_ms, now, claim.run_id, claim.owner,
                                            claim.epoch, now))
            if cur.rowcount != 1:
                raise LeaseLost("lease is no longer current")

    def succeed(self, claim, result):
        now = self.store.now_ms()
        payload = canonical(result)
        with self.store.tx():
            row = self.db.execute("SELECT * FROM runs WHERE run_id=?", (claim.run_id,)).fetchone()
            self._assert_lease(row, claim, now)
            attempt = self.db.execute("""SELECT * FROM attempts WHERE run_id=? AND step_id=?
                AND attempt_no=? AND status='running'""", (claim.run_id, claim.step_id, claim.attempt_no)).fetchone()
            if attempt is None:
                raise LeaseLost("attempt is no longer current")
            self.db.execute("UPDATE attempts SET status='succeeded',finished_ms=? WHERE run_id=? AND step_id=? AND attempt_no=?",
                            (now, claim.run_id, claim.step_id, claim.attempt_no))
            self.db.execute("UPDATE steps SET status='succeeded',result_json=?,due_at_ms=NULL WHERE run_id=? AND step_id=?",
                            (payload, claim.run_id, claim.step_id))
            nxt = row["next_step"] + 1
            count = self.db.execute("SELECT count(*) FROM steps WHERE run_id=?", (claim.run_id,)).fetchone()[0]
            status = "succeeded" if nxt >= count else "queued"
            self.db.execute("UPDATE runs SET status=?,next_step=?,lease_owner=NULL,lease_until_ms=NULL,updated_ms=?,ready_at_ms=? WHERE run_id=?",
                            (status, nxt, now, now, claim.run_id))
            self.store.event(claim.run_id, "step_succeeded", now, {"attempt_no": claim.attempt_no}, claim.step_id)
            if status == "succeeded":
                self.store.event(claim.run_id, "run_succeeded", now, {}, None)

    def fail(self, claim, error, retryable=False):
        now = self.store.now_ms()
        code = getattr(error, "code", "ACTION_ERROR")
        with self.store.tx():
            row = self.db.execute("SELECT * FROM runs WHERE run_id=?", (claim.run_id,)).fetchone()
            self._assert_lease(row, claim, now)
            attempt = None if claim.attempt_no is None else self.db.execute(
                "SELECT * FROM attempts WHERE run_id=? AND step_id=? AND attempt_no=? AND status='running'",
                (claim.run_id, claim.step_id, claim.attempt_no)).fetchone()
            if claim.attempt_no is not None and attempt is None:
                raise LeaseLost("attempt is no longer current")
            if claim.attempt_no is None:
                self.db.execute("UPDATE steps SET status='failed',error_code=? WHERE run_id=? AND step_id=?",
                                (code, claim.run_id, claim.step_id))
                self.db.execute("UPDATE runs SET status='failed',error_code=?,lease_owner=NULL,lease_until_ms=NULL,updated_ms=? WHERE run_id=?",
                                (code, now, claim.run_id))
                self.store.event(claim.run_id, "run_failed", now, {"error_code": code}, claim.step_id)
                return
            self.db.execute("UPDATE attempts SET status='failed',finished_ms=?,error_code=? WHERE run_id=? AND step_id=? AND attempt_no=?",
                            (now, code, claim.run_id, claim.step_id, claim.attempt_no))
            step = self.db.execute("SELECT * FROM steps WHERE run_id=? AND step_id=?", (claim.run_id, claim.step_id)).fetchone()
            retry = retryable and claim.attempt_no < step["max_attempts"]
            if retry:
                delay = min(step["cap_delay_ms"], step["base_delay_ms"] * 2 ** (claim.attempt_no - 1))
                due = now + delay
                self.db.execute("UPDATE steps SET status='retry_wait',due_at_ms=?,error_code=? WHERE run_id=? AND step_id=?",
                                (due, code, claim.run_id, claim.step_id))
                self.db.execute("UPDATE runs SET status='retry_wait',ready_at_ms=?,lease_owner=NULL,lease_until_ms=NULL,updated_ms=? WHERE run_id=?",
                                (due, now, claim.run_id))
                self.store.event(claim.run_id, "attempt_retry_wait", now, {"attempt_no": claim.attempt_no, "due_at_ms": due, "error_code": code}, claim.step_id)
            else:
                self.db.execute("UPDATE steps SET status='failed',error_code=? WHERE run_id=? AND step_id=?",
                                (code, claim.run_id, claim.step_id))
                self.db.execute("UPDATE runs SET status='failed',error_code=?,lease_owner=NULL,lease_until_ms=NULL,updated_ms=? WHERE run_id=?",
                                (code, now, claim.run_id))
                self.store.event(claim.run_id, "run_failed", now, {"error_code": code}, claim.step_id)

    def execute_once(self):
        claim = self.claim()
        if claim is None:
            return False
        if claim.kind == "wait_signal":
            return self.consume_signal(claim)
        if claim.action is None:
            self.fail(claim, PermanentError("wait_signal not yet implemented"), False)
            return True
        try:
            handler = self.registry.require(claim.action, claim.version)
            claim = self.allocate_attempt(claim)
            stop = threading.Event()
            lost = threading.Event()
            heartbeat = threading.Thread(target=self._heartbeat_loop,
                                         args=(claim, stop, lost),
                                         name="nexus-heartbeat", daemon=True)
            heartbeat.start()
            try:
                result = execute_supervised(
                    handler, claim, claim.timeout_ms,
                    action_ref=self.registry.import_reference(claim.action, claim.version),
                    stop_event=lost,
                    profile=self.execution_profile,
                    resource_limits=self.resource_limits,
                )
                if lost.is_set():
                    raise LeaseLost("lease renewal was lost during action execution")
            finally:
                stop.set()
                heartbeat.join(timeout=max(0.1, self.heartbeat_interval_ms / 1000 * 2))
            canonical(result)
            self.succeed(claim, result)
        except LeaseLost:
            # Never convert a stale action into a committed result. Reconciliation
            # owns the still-running durable attempt after the lease expires.
            return True
        except KeyError as exc:
            self.fail(claim, PermanentError("UNKNOWN_ACTION"), False)
        except RetryableError as exc:
            self.fail(claim, exc, True)
        except BaseException as exc:
            self.fail(claim, exc, False)
        return True

    def _heartbeat_loop(self, claim, stop, lost):
        conn = None
        try:
            # The action thread must not share the Store connection. This
            # connection is opened in the heartbeat thread and is closed there.
            conn = sqlite3.connect(self.store.path, autocommit=True, timeout=5.0)
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA busy_timeout=5000")
            while not stop.wait(self.heartbeat_interval_ms / 1000):
                now = self.store.now_ms()
                try:
                    conn.execute("BEGIN IMMEDIATE")
                    cur = conn.execute("""UPDATE runs SET lease_until_ms=?,updated_ms=?
                        WHERE run_id=? AND status='running' AND lease_owner=? AND lease_epoch=?
                        AND lease_until_ms>?""", (now + self.lease_ms, now, claim.run_id,
                                                     claim.owner, claim.epoch, now))
                    if cur.rowcount != 1:
                        conn.execute("ROLLBACK")
                        lost.set()
                        return
                    conn.execute("COMMIT")
                except BaseException:
                    if conn.in_transaction:
                        conn.execute("ROLLBACK")
                    lost.set()
                    return
        except BaseException:
            lost.set()
        finally:
            if conn is not None:
                conn.close()

    @staticmethod
    def _assert_lease(row, claim, now):
        if row is None or row["status"] != "running" or row["lease_owner"] != claim.owner \
                or row["lease_epoch"] != claim.epoch or row["lease_until_ms"] is None \
                or row["lease_until_ms"] <= now:
            raise LeaseLost("lease is no longer current")
