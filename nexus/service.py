"""Durable control operations shared by the SDK, CLI and HTTP adapter."""
import json
import uuid
from .models import (Conflict, InvalidSpec, NotFound, RunSpec, TERMINAL,
                     canonical, digest, identifier, integer)
from .extensions import ensure_tables


class Nexus:
    def __init__(self, store):
        self.store = store
        self.db = store.db
        ensure_tables(store)

    def submit_result(self, spec, request_key):
        identifier(request_key, "request key")
        if not isinstance(spec, RunSpec):
            spec = RunSpec.from_dict(spec)
        body = spec.to_dict()
        spec_hash = digest(body)
        with self.store.tx():
            old = self.db.execute("SELECT run_id,spec_digest FROM runs WHERE request_key=?", (request_key,)).fetchone()
            if old:
                if old["spec_digest"] != spec_hash:
                    raise Conflict("Request key already binds different content")
                return old["run_id"], False
            now = self.store.now_ms()
            run_id = uuid.uuid4().hex
            self.db.execute("""INSERT INTO runs(run_id,request_key,spec_json,spec_digest,status,
                            ready_at_ms,created_ms,updated_ms) VALUES (?,?,?,?,'queued',?,?,?)""",
                            (run_id, request_key, canonical(body), spec_hash, now, now, now))
            for ordinal, obj in enumerate(spec.steps):
                s = obj.to_dict()
                effect = digest({k: s[k] for k in ("action", "version", "input")}) if s["kind"] == "action" else None
                retry = s.get("retry", {})
                self.db.execute("""INSERT INTO steps(run_id,step_id,ordinal,kind,status,
                    action_name,action_version,signal_name,input_json,effect_digest,require_approval,
                    approval_ttl_ms,max_attempts,base_delay_ms,cap_delay_ms,timeout_ms)
                    VALUES (?,?,?,?,'pending',?,?,?,?,?,?,?,?,?,?,?)""",
                    (run_id, s["id"], ordinal, s["kind"], s.get("action"), s.get("version"), s.get("name"),
                     canonical(s.get("input", {})), effect, int(s.get("require_approval", False)),
                     s.get("approval_ttl_ms", 86400000), retry.get("max_attempts", 3),
                     retry.get("base_delay_ms", 1000), retry.get("cap_delay_ms", 60000), s.get("timeout_ms", 60000)))
                for capability in s.get("capabilities", []):
                    self.db.execute("INSERT INTO step_capabilities(run_id,step_id,capability) VALUES (?,?,?)",
                                    (run_id, s["id"], capability))
            self.store.event(run_id, "run_submitted", now, {"spec_digest": spec_hash})
            return run_id, True

    def submit(self, spec, request_key):
        return self.submit_result(spec, request_key)[0]

    def _run(self, run_id):
        row = self.db.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
        if row is None:
            raise NotFound("Run not found")
        return row

    def get_run(self, run_id):
        with self.store.tx(read=True):
            r = dict(self._run(run_id))
            r["spec"] = json.loads(r.pop("spec_json"))
            r["steps"] = []
            for row in self.db.execute("SELECT * FROM steps WHERE run_id=? ORDER BY ordinal", (run_id,)):
                step = dict(row)
                step["input"] = json.loads(step.pop("input_json"))
                saved = step.pop("result_json")
                step["result"] = json.loads(saved) if saved is not None else None
                r["steps"].append(step)
            r["approvals"] = [dict(x) for x in self.db.execute("SELECT * FROM approvals WHERE run_id=? ORDER BY created_ms,approval_id", (run_id,))]
            return r

    def events(self, run_id, after=0, limit=100):
        integer(after, "after", 0, 2**63-1); integer(limit, "limit", 1, 100)
        with self.store.tx(read=True):
            self._run(run_id)
            result = []
            for row in self.db.execute("SELECT * FROM events WHERE run_id=? AND event_id>? ORDER BY event_id LIMIT ?", (run_id, after, limit)):
                e = dict(row); e["payload"] = json.loads(e.pop("payload_json")); result.append(e)
            return result

    def decide(self, approval_id, decision, principal):
        identifier(approval_id, "approval id")
        if decision not in ("approved", "denied") or not isinstance(principal, str) or not principal:
            raise InvalidSpec("invalid approval decision")
        with self.store.tx():
            approval = self.db.execute("SELECT * FROM approvals WHERE approval_id=?", (approval_id,)).fetchone()
            if approval is None:
                raise NotFound("Approval not found")
            now = self.store.now_ms()
            if approval["decision"] == decision:
                return dict(approval)
            if approval["decision"] != "pending" or now >= approval["expires_ms"]:
                raise Conflict("approval is no longer decidable")
            self.db.execute("UPDATE approvals SET decision=?,decided_ms=?,decided_by=? WHERE approval_id=?",
                            (decision, now, principal, approval_id))
            status = "queued" if decision == "approved" else "failed"
            error = None if decision == "approved" else "APPROVAL_DENIED"
            self.db.execute("""UPDATE runs SET status=?,error_code=?,ready_at_ms=?,updated_ms=?
                WHERE run_id=? AND status='waiting_approval'""",
                            (status, error, now, now, approval["run_id"]))
            self.db.execute("""UPDATE steps SET status=?,error_code=? WHERE run_id=? AND step_id=?
                AND status='waiting_approval'""", ("pending" if decision == "approved" else "failed", error,
                                                     approval["run_id"], approval["step_id"]))
            self.store.event(approval["run_id"], "approval_decided", now,
                             {"approval_id": approval_id, "decision": decision, "principal": principal}, approval["step_id"])
            return dict(self.db.execute("SELECT * FROM approvals WHERE approval_id=?", (approval_id,)).fetchone())

    def cancel(self, run_id, principal):
        if not isinstance(principal, str) or not principal:
            raise InvalidSpec("principal is required")
        with self.store.tx():
            run = self._run(run_id)
            if run["status"] in TERMINAL:
                return dict(run)
            now = self.store.now_ms()
            self.db.execute("""UPDATE runs SET status='cancelled',lease_epoch=lease_epoch+1,lease_owner=NULL,
                lease_until_ms=NULL,error_code='CANCELLED',updated_ms=? WHERE run_id=?""", (now, run_id))
            self.db.execute("""UPDATE steps SET status='cancelled',error_code='CANCELLED' WHERE run_id=?
                AND status NOT IN ('succeeded','failed','cancelled')""", (run_id,))
            self.store.event(run_id, "run_cancelled", now, {"principal": principal})
            return dict(self._run(run_id))

    def signal(self, run_id, name, message_id, payload):
        identifier(run_id, "run id")
        identifier(name, "signal name")
        identifier(message_id, "message id")
        payload_json = canonical(payload)
        payload_digest = digest({"name": name, "payload": payload})
        with self.store.tx():
            run = self._run(run_id)
            if run["status"] in TERMINAL:
                raise Conflict("Cannot signal a terminal run")
            old = self.db.execute("SELECT * FROM signals WHERE run_id=? AND message_id=?",
                                  (run_id, message_id)).fetchone()
            if old:
                if old["name"] != name or old["payload_digest"] != payload_digest:
                    raise Conflict("Message id already binds different content")
                return dict(old)
            now = self.store.now_ms()
            self.db.execute("""INSERT INTO signals(run_id,message_id,name,payload_json,payload_digest,created_ms)
                VALUES (?,?,?,?,?,?)""", (run_id, message_id, name, payload_json, payload_digest, now))
            self.store.event(run_id, "signal_received", now,
                             {"message_id": message_id, "name": name})
            if run["status"] == "waiting_signal":
                step = self.db.execute("""SELECT * FROM steps WHERE run_id=? AND ordinal=?
                    AND kind='wait_signal' AND status='waiting_signal'""",
                                       (run_id, run["next_step"])).fetchone()
                if step is not None and step["signal_name"] == name:
                    self.db.execute("UPDATE runs SET status='queued',ready_at_ms=?,updated_ms=? WHERE run_id=?",
                                    (now, now, run_id))
                    self.db.execute("UPDATE steps SET status='pending' WHERE run_id=? AND step_id=?",
                                    (run_id, step["step_id"]))
            return dict(self.db.execute("""SELECT * FROM signals WHERE run_id=? AND message_id=?""",
                                        (run_id, message_id)).fetchone())
