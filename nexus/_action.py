"""Clean child entry point for importable trusted/restricted actions."""
from __future__ import annotations

import importlib
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


def main():
    if len(sys.argv) != 2:
        return 2
    try:
        raw = sys.stdin.buffer.read(MAX_PROTOCOL_BYTES + 1)
        if len(raw) > MAX_PROTOCOL_BYTES:
            response = _error("permanent", "CHILD_INPUT_LIMIT", "child request exceeded 64 KiB")
        else:
            request = strict_loads(raw)
            handler = _resolve(sys.argv[1])
            result = handler(request["input"], ActionContext(**request["context"]))
            response = canonical({"ok": True, "result": result})
    except RetryableError as exc:
        response = _error("retryable", getattr(exc, "code", "RETRYABLE_ERROR"), exc)
    except BaseException as exc:
        response = _error("permanent", getattr(exc, "code", "ACTION_ERROR"), exc)
    encoded = response.encode("utf-8")
    if len(encoded) > MAX_PROTOCOL_BYTES:
        encoded = _error("permanent", "CHILD_OUTPUT_LIMIT", "child response exceeded 64 KiB").encode()
    sys.stdout.buffer.write(encoded)
    sys.stdout.buffer.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
