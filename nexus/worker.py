"""Single-host worker loop over the durable workflow engine."""
import threading
import time
from .engine import Engine


class Worker:
    def __init__(self, store, registry, *, poll_interval=0.1, lease_ms=30_000,
                 heartbeat_interval_ms=None):
        self.engine = Engine(store, registry, lease_ms=lease_ms,
                             heartbeat_interval_ms=heartbeat_interval_ms)
        self.poll_interval = poll_interval
        self.stop_event = threading.Event()

    def run_once(self):
        return self.engine.execute_once()

    def stop(self):
        self.stop_event.set()

    def run_forever(self):
        while not self.stop_event.is_set():
            if not self.run_once():
                self.stop_event.wait(self.poll_interval)
