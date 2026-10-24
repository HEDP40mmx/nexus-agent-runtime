"""Trusted same-user child-process execution for registered actions."""
from __future__ import annotations

import json
import multiprocessing
import os
import signal
import time
from dataclasses import asdict

from .models import ActionContext, InvalidSpec, PermanentError, RetryableError, canonical, strict_loads

MAX_PROTOCOL_BYTES = 65536
GRACE_MS = 100


def _error_payload(kind, code, message):
    return canonical({"ok": False, "kind": kind, "code": code, "message": str(message)[:4096]})


def _child_entry(handler, request_json, sender):
    """Run one trusted handler in a separate process with a fixed target."""
    try:
        os.setsid()
        request = strict_loads(request_json)
        context = ActionContext(**request["context"])
        result = handler(request["input"], context)
        response = canonical({"ok": True, "result": result})
    except RetryableError as exc:
        response = _error_payload("retryable", getattr(exc, "code", "RETRYABLE_ERROR"), exc)
    except BaseException as exc:
        response = _error_payload("permanent", getattr(exc, "code", "ACTION_ERROR"), exc)
    try:
        encoded = response.encode("utf-8")
        if len(encoded) > MAX_PROTOCOL_BYTES:
            encoded = _error_payload("permanent", "CHILD_OUTPUT_LIMIT", "child response exceeded 64 KiB").encode()
        sender.send_bytes(encoded)
    finally:
        sender.close()


def _kill_group(process):
    if process.pid is None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    deadline = time.monotonic() + GRACE_MS / 1000
    while process.is_alive() and time.monotonic() < deadline:
        process.join(0.01)
    if process.is_alive():
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.join(1)


def execute(handler, claim, timeout_ms):
    """Execute one handler and return its JSON result, or raise a Nexus error."""
    if "fork" not in multiprocessing.get_all_start_methods():
        raise PermanentError("SUPERVISION_UNAVAILABLE")
    request = canonical({
        "input": claim.input,
        "context": asdict(ActionContext(claim.run_id, claim.step_id, claim.attempt_no,
                                         claim.epoch, claim.effect_key)),
    })
    context = multiprocessing.get_context("fork")
    receiver, sender = context.Pipe(duplex=False)
    process = context.Process(target=_child_entry, args=(handler, request, sender),
                              name="nexus-action-child")
    process.start()
    sender.close()
    try:
        deadline = time.monotonic() + timeout_ms / 1000
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                _kill_group(process)
                error = RetryableError("action timed out")
                error.code = "ACTION_TIMEOUT"
                raise error
            if receiver.poll(min(remaining, 0.02)):
                try:
                    raw = receiver.recv_bytes(MAX_PROTOCOL_BYTES + 1)
                except (EOFError, OSError) as exc:
                    raise PermanentError("CHILD_PROTOCOL_ERROR") from exc
                if len(raw) > MAX_PROTOCOL_BYTES:
                    raise PermanentError("CHILD_OUTPUT_LIMIT")
                response = strict_loads(raw)
                if response.get("ok") is True:
                    return response["result"]
                kind = response.get("kind")
                message = response.get("message", "child action failed")
                if kind == "retryable":
                    error = RetryableError(message)
                    error.code = response.get("code", "RETRYABLE_ERROR")
                    raise error
                error = PermanentError(message)
                error.code = response.get("code", "ACTION_ERROR")
                raise error
            if not process.is_alive() and not receiver.poll():
                raise PermanentError("CHILD_PROTOCOL_ERROR")
    finally:
        receiver.close()
        if process.is_alive():
            _kill_group(process)
        else:
            process.join(1)
