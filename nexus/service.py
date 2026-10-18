"""Durable control operations shared by the SDK, CLI and HTTP adapter."""
import json
import uuid
from .models import (Conflict, InvalidSpec, NotFound, RunSpec, TERMINAL,
                     canonical, digest, identifier, integer)


class Nexus:
    def __init__(self, store):
        self.store = store
        self.db = store.db

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
