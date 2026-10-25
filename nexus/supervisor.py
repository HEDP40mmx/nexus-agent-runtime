"""Trusted and clean subprocess supervision for registered actions."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import multiprocessing
import os
import selectors
import signal
import subprocess
import sys
import time

from .models import ActionContext, LeaseLost, PermanentError, RetryableError, canonical, strict_loads

MAX_PROTOCOL_BYTES = 65536
MAX_STDERR_BYTES = 32768
GRACE_MS = 100
PROFILES = {"trusted", "restricted", "isolated"}


@dataclass(frozen=True)
class ResourceLimits:
    """OS-enforced limits for a clean child.

    `filesystem_root` is mandatory for the isolated profile. The child enters
    it with chroot inside a user/mount namespace; if that boundary cannot be
    established, the child fails closed instead of running unrestricted.
    """

    cpu_seconds: int = 2
    memory_bytes: int = 256 * 1024 * 1024
    file_bytes: int = 8 * 1024 * 1024
    max_processes: int = 16
    filesystem_root: str | None = None
    network_mode: str = "none"

    def validate(self, profile):
        if profile not in PROFILES:
            raise ValueError("unknown execution profile")
        for name in ("cpu_seconds", "memory_bytes", "file_bytes", "max_processes"):
            value = getattr(self, name)
            if type(value) is not int or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        if profile == "isolated":
            if not isinstance(self.filesystem_root, str) or not os.path.isabs(self.filesystem_root):
                raise ValueError("isolated profile requires an absolute filesystem_root")
            if self.network_mode != "none":
                raise ValueError("isolated profile requires network_mode='none'")


def _error_payload(kind, code, message):
    return canonical({"ok": False, "kind": kind, "code": code, "message": str(message)[:4096]})


def _raise_response(response):
    if response.get("ok") is True:
        return response["result"]
    message = response.get("message", "child action failed")
    if response.get("kind") == "retryable":
        error = RetryableError(message)
        error.code = response.get("code", "RETRYABLE_ERROR")
        raise error
    error = PermanentError(message)
    error.code = response.get("code", "ACTION_ERROR")
    raise error


def _kill_popen(process):
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=GRACE_MS / 1000)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=1)


def _clean_environment():
    # Do not inherit bearer tokens, provider credentials, or arbitrary user
    # configuration. PATH is retained only to locate the interpreter itself;
    # the child command uses an absolute executable path.
    path = os.environ.get("PATH", "/usr/bin:/bin")
    return {
        "PATH": path,
        "PYTHONNOUSERSITE": "1",
        "PYTHONUNBUFFERED": "1",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
    }


def _execute_clean(action_ref, claim, timeout_ms, stop_event=None, profile="restricted", limits=None):
    limits = limits or ResourceLimits()
    limits.validate(profile)
    request = canonical({
        "action_ref": action_ref,
        "profile": profile,
        "limits": asdict(limits),
        "filesystem_root": limits.filesystem_root,
        "input": claim.input,
        "context": asdict(ActionContext(claim.run_id, claim.step_id, claim.attempt_no,
                                         claim.epoch, claim.effect_key)),
    }).encode("utf-8")
    command = [sys.executable, "-I", "-m", "nexus._action", action_ref]
    if profile == "isolated":
        unshare = "/usr/bin/unshare"
        if not os.path.exists(unshare) or not limits.filesystem_root or not os.path.isdir(limits.filesystem_root):
            error = PermanentError("isolated execution requires unshare")
            error.code = "ISOLATION_UNAVAILABLE"
            raise error
        try:
            probe = subprocess.run(
                [unshare, "--user", "--map-root-user", "--mount", "--pid", "--net", "--fork", "/bin/true"],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                env=_clean_environment(), close_fds=True, timeout=1,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            error = PermanentError("isolated namespace capability is unavailable")
            error.code = "ISOLATION_UNAVAILABLE"
            raise error from exc
        if probe.returncode != 0:
            error = PermanentError("isolated namespace capability is unavailable")
            error.code = "ISOLATION_UNAVAILABLE"
            raise error
        command = [unshare, "--user", "--map-root-user", "--mount", "--pid", "--net", "--fork"] + command
    process = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=_clean_environment(),
        close_fds=True,
        start_new_session=True,
    )
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ, "stdout")
    selector.register(process.stderr, selectors.EVENT_READ, "stderr")
    stdout = bytearray()
    stderr = bytearray()
    try:
        process.stdin.write(request)
        process.stdin.close()
        deadline = time.monotonic() + timeout_ms / 1000
        streams = {process.stdout, process.stderr}
        while streams or process.poll() is None:
            if stop_event is not None and stop_event.is_set():
                _kill_popen(process)
                raise LeaseLost("lease was lost or action was cancelled")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                _kill_popen(process)
                error = RetryableError("action timed out")
                error.code = "ACTION_TIMEOUT"
                raise error
            events = selector.select(min(remaining, 0.05))
            for key, _ in events:
                chunk = key.fileobj.read(8192)
                if not chunk:
                    selector.unregister(key.fileobj)
                    streams.discard(key.fileobj)
                    continue
                target = stdout if key.data == "stdout" else stderr
                limit = MAX_PROTOCOL_BYTES if key.data == "stdout" else MAX_STDERR_BYTES
                target.extend(chunk)
                if len(target) > limit:
                    _kill_popen(process)
                    error = PermanentError("child output exceeded configured limit")
                    error.code = "CHILD_OUTPUT_LIMIT"
                    raise error
        if process.returncode != 0 and not stdout:
            error = PermanentError("child exited without a response")
            error.code = "CHILD_PROTOCOL_ERROR"
            raise error
        try:
            response = strict_loads(bytes(stdout))
        except BaseException as exc:
            error = PermanentError("invalid child JSON response")
            error.code = "CHILD_PROTOCOL_ERROR"
            raise error from exc
        return _raise_response(response)
    finally:
        selector.close()
        if process.poll() is None:
            _kill_popen(process)
        for stream in (process.stdin, process.stdout, process.stderr):
            try:
                stream.close()
            except (AttributeError, OSError):
                pass


def _child_entry(handler, request_json, sender):
    """Legacy trusted same-user fallback for non-importable test handlers."""
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


def _execute_fork(handler, claim, timeout_ms, stop_event=None):
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
            if stop_event is not None and stop_event.is_set():
                _kill_group(process)
                raise LeaseLost("lease was lost or action was cancelled")
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
                return _raise_response(strict_loads(raw))
            if not process.is_alive() and not receiver.poll():
                raise PermanentError("CHILD_PROTOCOL_ERROR")
    finally:
        receiver.close()
        if process.is_alive():
            _kill_group(process)
        else:
            process.join(1)


def execute(handler, claim, timeout_ms, *, action_ref=None, stop_event=None,
            profile="trusted", resource_limits=None):
    """Execute under an explicit profile; isolated always fails closed."""
    if profile not in PROFILES:
        raise ValueError("unknown execution profile")
    if profile == "isolated" and not action_ref:
        error = PermanentError("isolated profile requires an importable action")
        error.code = "ISOLATION_UNAVAILABLE"
        raise error
    if action_ref:
        return _execute_clean(action_ref, claim, timeout_ms, stop_event, profile, resource_limits)
    if profile != "trusted":
        error = PermanentError("non-importable action is not allowed outside trusted profile")
        error.code = "ISOLATION_UNAVAILABLE"
        raise error
    return _execute_fork(handler, claim, timeout_ms, stop_event)
