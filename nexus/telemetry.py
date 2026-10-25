"""Small bounded telemetry registry with deterministic snapshots."""
from __future__ import annotations

import threading
import time


class Telemetry:
    def __init__(self, *, max_series=256):
        if type(max_series) is not int or max_series < 1:
            raise ValueError("max_series must be positive")
        self.max_series = max_series
        self._lock = threading.Lock()
        self._counters = {}
        self._gauges = {}
        self._timings = {}

    def _key(self, name, labels):
        if not isinstance(name, str) or not name or len(name) > 128:
            raise ValueError("metric name is invalid")
        if type(labels) is not dict or any(not isinstance(k, str) or not isinstance(v, str) for k, v in labels.items()):
            raise ValueError("metric labels must be string pairs")
        return name, tuple(sorted(labels.items()))

    def _admit(self, collection, key):
        if key not in collection and sum(len(x) for x in (self._counters, self._gauges, self._timings)) >= self.max_series:
            raise ValueError("telemetry series limit exceeded")

    def increment(self, name, amount=1, labels=None):
        if type(amount) is not int or amount < 0:
            raise ValueError("counter amount must be a nonnegative integer")
        key = self._key(name, labels or {})
        with self._lock:
            self._admit(self._counters, key)
            self._counters[key] = self._counters.get(key, 0) + amount

    def gauge(self, name, value, labels=None):
        if not isinstance(value, (int, float)):
            raise ValueError("gauge value must be numeric")
        key = self._key(name, labels or {})
        with self._lock:
            self._admit(self._gauges, key)
            self._gauges[key] = value

    def observe(self, name, value, labels=None):
        if not isinstance(value, (int, float)) or value < 0:
            raise ValueError("timing must be nonnegative")
        key = self._key(name, labels or {})
        with self._lock:
            self._admit(self._timings, key)
            samples = self._timings.setdefault(key, [])
            if len(samples) < 128:
                samples.append(float(value))

    def timed(self, name, labels=None):
        telemetry = self
        class Timer:
            def __enter__(self):
                self.started = time.monotonic(); return self
            def __exit__(self, *_):
                telemetry.observe(name, time.monotonic() - self.started, labels)
        return Timer()

    def snapshot(self):
        with self._lock:
            encode = lambda collection: [
                {"name": key[0], "labels": dict(key[1]), "value": value}
                for key, value in sorted(collection.items(), key=lambda item: item[0])]
            return {"counters": encode(self._counters), "gauges": encode(self._gauges),
                    "timings": encode({key: {"count": len(values), "sum": sum(values),
                                                "max": max(values) if values else 0}
                                        for key, values in self._timings.items()})}
