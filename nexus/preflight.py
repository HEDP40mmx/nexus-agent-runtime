"""Deterministic deployment preflight checks for the Nexus CLI."""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

from .store import Store
from .supervisor import ResourceLimits


def _check(name, fn):
    try:
        value = fn()
        return {"name": name, "ok": True, "detail": value}
    except Exception as exc:
        return {"name": name, "ok": False, "detail": str(exc),
                "code": getattr(exc, "code", "PREFLIGHT_FAILED")}


def run(database, *, isolated_root=None):
    path = Path(database).expanduser()
    checks = []
    checks.append(_check("python", lambda: {
        "version": ".".join(map(str, sys.version_info[:3])),
        "required": "3.12",
    } if sys.version_info[:2] == (3, 12) else (_ for _ in ()).throw(
        RuntimeError("Python 3.12 is required"))))
    checks.append(_check("database_parent", lambda: _writable_parent(path)))
    checks.append(_check("schema", lambda: _schema(path)))
    checks.append(_check("isolated_profile", lambda: _isolated(isolated_root)))
    return {"ok": all(item["ok"] for item in checks), "database": str(path), "checks": checks}


def _writable_parent(path):
    parent = path.parent
    parent.mkdir(parents=True, exist_ok=True)
    if not os.access(parent, os.W_OK):
        raise PermissionError(f"database parent is not writable: {parent}")
    return {"parent": str(parent), "writable": True}


def _schema(path):
    with Store(path) as store:
        return store.settings()


def _isolated(root):
    if root is None:
        return {"available": False, "reason": "no isolated filesystem root configured"}
    limits = ResourceLimits(filesystem_root=str(Path(root).expanduser()))
    limits.validate("isolated")
    if not os.path.isdir(limits.filesystem_root):
        raise FileNotFoundError(limits.filesystem_root)
    unshare = shutil.which("unshare")
    if not unshare:
        raise RuntimeError("unshare is unavailable")
    return {"available": True, "root": limits.filesystem_root,
            "network_mode": limits.network_mode, "unshare": unshare}
