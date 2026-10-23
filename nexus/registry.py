"""Explicit versioned registry for trusted local action handlers."""
from .models import InvalidSpec, identifier


class Registry:
    def __init__(self):
        self._handlers = {}

    def register(self, name, version, handler):
        identifier(name, "action")
        identifier(version, "version")
        if not callable(handler):
            raise InvalidSpec("action handler must be callable")
        key = (name, version)
        if key in self._handlers:
            raise InvalidSpec(f"action already registered: {name}/{version}")
        self._handlers[key] = handler
        return self

    def resolve(self, name, version):
        return self._handlers.get((name, version))

    def require(self, name, version):
        handler = self.resolve(name, version)
        if handler is None:
            raise KeyError(f"unknown action: {name}/{version}")
        return handler

    def copy(self):
        result = Registry()
        result._handlers.update(self._handlers)
        return result

    def __contains__(self, key):
        return key in self._handlers
