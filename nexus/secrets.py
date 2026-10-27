"""Reference-only secret resolution; raw values never enter workflow state."""
from __future__ import annotations

import os
import re
from pathlib import Path

from .models import InvalidSpec, identifier

_SECRET = re.compile(r"(?i)(bearer\s+|token|secret|password|api[_-]?key)([=:]\s*|\s+)([^\s,;]+)")


class SecretResolver:
    def __init__(self, *, env=None, files=None):
        self.env = dict(os.environ if env is None else env)
        self.files = {str(k): Path(v) for k, v in (files or {}).items()}

    def resolve(self, reference):
        if not isinstance(reference, str) or ":" not in reference:
            raise InvalidSpec("secret must be an env: or file: reference")
        if reference.startswith("env:"):
            name = reference[4:]
            identifier(name, "environment secret name")
            value = self.env.get(name)
        elif reference.startswith("file:"):
            name = reference[5:]
            identifier(name, "file secret name")
            path = self.files.get(name)
            try:
                value = path.read_text(encoding="utf-8").rstrip("\r\n") if path is not None else None
            except OSError:
                value = None
        else:
            raise InvalidSpec("secret must be an env: or file: reference")
        if not value:
            error = InvalidSpec("secret reference is unavailable")
            error.code = "SECRET_UNAVAILABLE"
            raise error
        return value

    def resolve_many(self, references):
        if type(references) is not list or len(references) > 32:
            raise InvalidSpec("secret references must be a bounded list")
        return {ref: self.resolve(ref) for ref in references}


def redact(value, secrets=()):
    text = str(value)
    for secret in secrets:
        if secret:
            text = text.replace(str(secret), "[REDACTED]")
    return _SECRET.sub(lambda match: match.group(1) + match.group(2) + "[REDACTED]", text)
