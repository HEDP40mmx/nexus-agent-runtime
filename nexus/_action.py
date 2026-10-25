"""Clean child entry point for importable actions."""
from __future__ import annotations

import importlib
import os
import resource
import sys

from .models import ActionContext, RetryableError, canonical, strict_loads
from .supervisor import MAX_PROTOCOL_BYTES


def _error(kind, code, message):
    return canonical({"ok": False, "kind": kind, "code": code, "message": str(message)[:4096]})


def _resolve(reference):
    module_name, separator, qualname = reference.partition(":")
    if not separator or not module_name or not qualname or "<" in qualname:
        raise ValueError("invalid action reference")
    value = importlib.import_module(module_name)
    for part in qualname.split("."):
        value = getattr(value, part)
    if not callable(value):
        raise TypeError("action reference is not callable")
    return value


def _set_limit(kind, value):
    if type(value) is not int or value <= 0:
        raise ValueError(f"invalid {kind} limit")
    current_soft, current_hard = resource.getrlimit(kind)
    hard = value if current_hard == resource.RLIM_INFINITY else min(value, current_hard)
    resource.setrlimit(kind, (min(value, hard), hard))


def _apply_limits(request):
    limits = request.get("limits") or {}
    if "cpu_seconds" in limits:
        _set_limit(resource.RLIMIT_CPU, limits["cpu_seconds"])
    if "memory_bytes" in limits:
        _set_limit(resource.RLIMIT_AS, limits["memory_bytes"])
    if "file_bytes" in limits:
        _set_limit(resource.RLIMIT_FSIZE, limits["file_bytes"])
    if "max_processes" in limits and hasattr(resource, "RLIMIT_NPROC"):
        _set_limit(resource.RLIMIT_NPROC, limits["max_processes"])


def _enter_filesystem_root(root):
    if not isinstance(root, str) or not os.path.isabs(root) or not os.path.isdir(root):
        raise RuntimeError("isolated filesystem root is unavailable")
    if os.geteuid() != 0:
        raise RuntimeError("isolated filesystem root requires an OS-enforced root boundary")
    os.chroot(root)
    os.chdir("/")


def main():
    if len(sys.argv) != 2:
        return 2
    try:
        raw = sys.stdin.buffer.read(MAX_PROTOCOL_BYTES + 1)
        if len(raw) > MAX_PROTOCOL_BYTES:
            response = _error("permanent", "CHILD_INPUT_LIMIT", "child request exceeded 64 KiB")
        else:
            request = strict_loads(raw)
            _apply_limits(request)
            handler = _resolve(request["action_ref"])
            if request.get("profile") == "isolated":
                _enter_filesystem_root(request.get("filesystem_root"))
            result = handler(request["input"], ActionContext(**request["context"]))
            response = canonical({"ok": True, "result": result})
    except RetryableError as exc:
        response = _error("retryable", getattr(exc, "code", "RETRYABLE_ERROR"), exc)
    except BaseException as exc:
        response = _error("permanent", "ISOLATION_ERROR" if "isolated" in locals().get("request", {}).get("profile", "") else getattr(exc, "code", "ACTION_ERROR"), exc)
    encoded = response.encode("utf-8")
    if len(encoded) > MAX_PROTOCOL_BYTES:
        encoded = _error("permanent", "CHILD_OUTPUT_LIMIT", "child response exceeded 64 KiB").encode()
    sys.stdout.buffer.write(encoded)
    sys.stdout.buffer.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
