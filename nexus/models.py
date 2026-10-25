"""Validated immutable workflow specifications and bounded JSON protocol."""
from dataclasses import dataclass, field
import hashlib
import json
import re
import time

MAX_JSON = 65536
MAX_DEPTH = 32
TERMINAL = frozenset(("succeeded", "failed", "cancelled"))


class NexusError(Exception):
    code = "NEXUS_ERROR"


class InvalidSpec(NexusError, ValueError):
    code = "INVALID_SPEC"


class MalformedJSON(InvalidSpec):
    code = "MALFORMED_JSON"


class NotFound(NexusError):
    code = "NOT_FOUND"


class Conflict(NexusError):
    code = "CONFLICT"


class StorageError(NexusError):
    code = "STORAGE_ERROR"


class StorageBusy(StorageError):
    code = "STORAGE_BUSY"


class LeaseLost(NexusError):
    code = "LEASE_LOST"


class RetryableError(NexusError):
    code = "RETRYABLE_ERROR"


class PermanentError(NexusError):
    code = "PERMANENT_ERROR"


def integer(value, name, low, high):
    if type(value) is not int or not low <= value <= high:
        raise InvalidSpec(f"{name} must be an integer in [{low}, {high}]")
    return value


def identifier(value, name="identifier"):
    if not isinstance(value, str) or re.fullmatch(r"[A-Za-z0-9._-]{1,128}", value) is None:
        raise InvalidSpec(f"Invalid {name}")
    return value


def _validate_json(value, depth=0):
    if depth > MAX_DEPTH:
        raise InvalidSpec("JSON exceeds maximum depth")
    if type(value) is dict:
        for k, v in value.items():
            if not isinstance(k, str):
                raise InvalidSpec("JSON object keys must be strings")
            _validate_json(v, depth + 1)
    elif type(value) in (list, tuple):
        for v in value:
            _validate_json(v, depth + 1)
    elif value is not None and type(value) not in (str, bool, int, float):
        raise InvalidSpec("Value is not JSON")


def canonical(value):
    try:
        _validate_json(value)
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":"),
                             ensure_ascii=True, allow_nan=False)
    except (ValueError, TypeError, RecursionError, OverflowError) as exc:
        raise InvalidSpec("Invalid JSON value") from exc
    if len(encoded.encode("utf-8")) > MAX_JSON:
        raise InvalidSpec("JSON exceeds 64 KiB")
    return encoded


def strict_loads(data):
    if not isinstance(data, (bytes, str)):
        raise MalformedJSON("JSON must be UTF-8 bytes or text")
    try:
        raw = data.encode("utf-8", errors="strict") if isinstance(data, str) else data
        if len(raw) > MAX_JSON:
            raise InvalidSpec("JSON exceeds 64 KiB")
        text = raw.decode("utf-8", errors="strict")
        def pairs(items):
            result = {}
            for key, value in items:
                if key in result:
                    raise MalformedJSON("Duplicate object key")
                result[key] = value
            return result
        def constant(_):
            raise MalformedJSON("Nonfinite JSON number")
        value = json.loads(text, object_pairs_hook=pairs, parse_constant=constant)
        canonical(value)
        return value
    except (UnicodeError, json.JSONDecodeError, RecursionError, ValueError) as exc:
        if isinstance(exc, InvalidSpec):
            raise
        raise MalformedJSON("Malformed UTF-8 JSON") from exc


def digest(value):
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def fields(value, allowed, required=()):
    if type(value) is not dict or set(value) - set(allowed) or set(required) - set(value):
        raise InvalidSpec("Invalid or missing object fields")


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 3
    base_delay_ms: int = 1000
    cap_delay_ms: int = 60000

    def __post_init__(self):
        integer(self.max_attempts, "max_attempts", 1, 20)
        integer(self.base_delay_ms, "base_delay_ms", 0, 86400000)
        integer(self.cap_delay_ms, "cap_delay_ms", self.base_delay_ms, 86400000)

    def delay(self, attempt_no):
        return min(self.cap_delay_ms, self.base_delay_ms * 2 ** (attempt_no - 1))

    def to_dict(self):
        return {"max_attempts": self.max_attempts, "base_delay_ms": self.base_delay_ms,
                "cap_delay_ms": self.cap_delay_ms}

    @classmethod
    def from_dict(cls, data):
        fields(data, ("max_attempts", "base_delay_ms", "cap_delay_ms"))
        return cls(**data)


@dataclass(frozen=True, init=False)
class StepSpec:
    id: str
    kind: str
    _json: str = field(repr=False)

    def __init__(self, data):
        if not isinstance(data, dict):
            raise InvalidSpec("Step must be an object")
        kind = data.get("kind")
        if kind == "action":
            fields(data, ("id", "kind", "action", "version", "input", "retry",
                          "require_approval", "approval_ttl_ms", "timeout_ms"),
                   ("id", "kind", "action", "version", "input"))
            identifier(data["action"], "action"); identifier(data["version"], "version")
            if type(data["input"]) is not dict:
                raise InvalidSpec("Action input must be an object")
            retry = RetryPolicy.from_dict(data.get("retry", {}))
            approval = data.get("require_approval", False)
            if type(approval) is not bool:
                raise InvalidSpec("require_approval must be boolean")
            ttl = integer(data.get("approval_ttl_ms", 86400000), "approval_ttl_ms", 1, 604800000)
            timeout = integer(data.get("timeout_ms", 60000), "timeout_ms", 1, 3600000)
            normalized = {**data, "retry": retry.to_dict(), "require_approval": approval,
                          "approval_ttl_ms": ttl, "timeout_ms": timeout}
        elif kind == "wait_signal":
            fields(data, ("id", "kind", "name"), ("id", "kind", "name"))
            identifier(data["name"], "signal name")
            normalized = dict(data)
        else:
            raise InvalidSpec("Unknown step kind")
        identifier(data["id"], "step id")
        object.__setattr__(self, "id", data["id"])
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "_json", canonical(normalized))

    @classmethod
    def action(cls, *, id, action, version, input, retry=None, require_approval=False,
               approval_ttl_ms=86400000, timeout_ms=60000):
        if retry is not None and not isinstance(retry, RetryPolicy):
            raise InvalidSpec("retry must be RetryPolicy")
        return cls(dict(id=id, kind="action", action=action, version=version, input=input,
                        retry=(retry or RetryPolicy()).to_dict(), require_approval=require_approval,
                        approval_ttl_ms=approval_ttl_ms, timeout_ms=timeout_ms))

    @classmethod
    def wait_signal(cls, *, id, name):
        return cls(dict(id=id, kind="wait_signal", name=name))

    def to_dict(self):
        return json.loads(self._json)


@dataclass(frozen=True)
class RunSpec:
    steps: tuple

    def __post_init__(self):
        if not isinstance(self.steps, (list, tuple)) or not 1 <= len(self.steps) <= 100:
            raise InvalidSpec("Run must have 1–100 steps")
        if any(not isinstance(s, StepSpec) for s in self.steps):
            raise InvalidSpec("Run steps must be StepSpec instances")
        if len({s.id for s in self.steps}) != len(self.steps):
            raise InvalidSpec("Duplicate step id")
        object.__setattr__(self, "steps", tuple(self.steps))
        canonical(self.to_dict())

    def to_dict(self):
        return {"steps": [s.to_dict() for s in self.steps]}

    @classmethod
    def from_dict(cls, data):
        fields(data, ("steps",), ("steps",))
        if type(data["steps"]) is not list:
            raise InvalidSpec("steps must be a list")
        return cls(tuple(StepSpec(s) for s in data["steps"]))


@dataclass(frozen=True)
class ActionContext:
    run_id: str
    step_id: str
    attempt_no: int
    lease_epoch: int
    effect_key: str


class SystemClock:
    def now_ms(self):
        return time.time_ns() // 1000000
