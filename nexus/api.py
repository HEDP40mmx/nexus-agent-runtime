"""Authenticated localhost HTTP control adapter for the fresh-v1 service."""
from __future__ import annotations

from collections import deque
from contextlib import contextmanager
import hmac
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from .models import Conflict, InvalidSpec, NotFound, canonical
from .service import Nexus
from .store import Store

MAX_BODY = 65536
ROLE_LEVEL = {"reader": 1, "operator": 2, "admin": 3}


def _status(exc):
    if isinstance(exc, NotFound):
        return 404
    if isinstance(exc, Conflict):
        return 409
    if isinstance(exc, InvalidSpec):
        return 400
    return 500


class RateLimiter:
    """Thread-safe fixed sliding-window limiter keyed by peer address."""

    def __init__(self, max_requests=60, window_seconds=60):
        if type(max_requests) is not int or max_requests < 1:
            raise ValueError("max_requests must be a positive integer")
        if type(window_seconds) not in (int, float) or window_seconds <= 0:
            raise ValueError("window_seconds must be positive")
        self.max_requests = max_requests
        self.window_seconds = float(window_seconds)
        self._lock = threading.Lock()
        self._hits = {}

    def allow(self, key, now=None):
        now = time.monotonic() if now is None else now
        cutoff = now - self.window_seconds
        with self._lock:
            hits = self._hits.setdefault(key, deque())
            while hits and hits[0] <= cutoff:
                hits.popleft()
            if len(hits) >= self.max_requests:
                retry_after = max(1, int(hits[0] + self.window_seconds - now + 0.999))
                return False, retry_after
            hits.append(now)
            return True, 0


class _BoundedHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, handler, *, max_workers, socket_timeout):
        if type(max_workers) is not int or max_workers < 1:
            raise ValueError("max_workers must be a positive integer")
        self._slots = threading.BoundedSemaphore(max_workers)
        self.socket_timeout = float(socket_timeout)
        super().__init__(address, handler)

    def get_request(self):
        request, address = super().get_request()
        request.settimeout(self.socket_timeout)
        return request, address

    def process_request(self, request, client_address):
        if not self._slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self._slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._slots.release()


def _normalize_tokens(auth_tokens):
    # A string remains accepted as an operator token for compatibility, but
    # new deployments should provide independent reader/operator/admin tokens.
    if isinstance(auth_tokens, str):
        auth_tokens = {"operator": auth_tokens}
    if type(auth_tokens) is not dict or not auth_tokens:
        raise ValueError("auth_tokens must be a non-empty role/token mapping")
    normalized = {}
    seen = set()
    for role, token in auth_tokens.items():
        if role not in ROLE_LEVEL or not isinstance(token, str) or not token:
            raise ValueError("auth_tokens must contain non-empty known roles and tokens")
        if token in seen:
            raise ValueError("role tokens must be distinct")
        seen.add(token)
        normalized[role] = token
    return normalized


def make_server(host, port, service, auth_tokens, *, max_requests=60,
                window_seconds=60, max_workers=16, socket_timeout=5):
    if host not in ("127.0.0.1", "::1", "localhost"):
        raise ValueError("HTTP control must bind to localhost")
    tokens = _normalize_tokens(auth_tokens)
    limiter = RateLimiter(max_requests, window_seconds)

    class Handler(BaseHTTPRequestHandler):
        server_version = "NexusHTTP/1"

        def _send(self, status, body, headers=None):
            raw = canonical(body).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            for key, value in (headers or {}).items():
                self.send_header(key, str(value))
            self.end_headers()
            self.wfile.write(raw)

        def _error(self, status, code, message, headers=None):
            self._send(status, {"error": {"code": code, "message": str(message)[:4096]}}, headers)

        def _rate_limit(self, path):
            if path == "/healthz":
                return True
            allowed, retry_after = limiter.allow(self.client_address[0])
            if not allowed:
                self._error(429, "RATE_LIMITED", "request rate limit exceeded",
                            {"Retry-After": retry_after})
            return allowed

        def _authenticate(self, required_role):
            if not self._rate_limit(urlsplit(self.path).path):
                return None
            value = self.headers.get("Authorization", "")
            supplied = value[7:] if value.startswith("Bearer ") else ""
            matched = None
            # Compare against every configured token to avoid early-exit timing.
            for role, token in tokens.items():
                if supplied and hmac.compare_digest(supplied, token):
                    matched = role
            if matched is None:
                self._error(401, "UNAUTHORIZED", "valid bearer token required",
                            {"WWW-Authenticate": "Bearer"})
                return None
            if ROLE_LEVEL[matched] < ROLE_LEVEL[required_role]:
                self._error(403, "FORBIDDEN", f"{required_role} role required")
                return None
            return matched

        def _body(self):
            try:
                length = int(self.headers.get("Content-Length", "-1"))
            except ValueError:
                raise InvalidSpec("invalid content length")
            if length < 0 or length > MAX_BODY:
                raise InvalidSpec("request body exceeds 64 KiB")
            raw = self.rfile.read(length)
            try:
                value = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise InvalidSpec("malformed JSON") from exc
            if not isinstance(value, dict):
                raise InvalidSpec("JSON body must be an object")
            return value

        @contextmanager
        def _service(self):
            # Store connections belong to one thread/process. HTTP handlers
            # therefore open a request-local connection against the same path.
            with Store(service.store.path) as store:
                yield Nexus(store)

        def do_GET(self):
            parsed = urlsplit(self.path)
            if parsed.path == "/healthz":
                self._send(200, {"ok": True})
                return
            if self._authenticate("reader") is None:
                return
            try:
                parts = parsed.path.strip("/").split("/")
                with self._service() as current:
                    if len(parts) == 3 and parts[:2] == ["v1", "runs"]:
                        self._send(200, current.get_run(parts[2]))
                    elif len(parts) == 4 and parts[:2] == ["v1", "runs"] and parts[3] == "events":
                        query = parse_qs(parsed.query)
                        after = int(query.get("after", [0])[0])
                        limit = int(query.get("limit", [100])[0])
                        self._send(200, {"events": current.events(parts[2], after, limit)})
                    else:
                        self._error(404, "NOT_FOUND", "endpoint not found")
            except BaseException as exc:
                self._error(_status(exc), getattr(exc, "code", "NEXUS_ERROR"), exc)

        def do_POST(self):
            role = self._authenticate("operator")
            if role is None:
                return
            try:
                parts = urlsplit(self.path).path.strip("/").split("/")
                body = self._body()
                with self._service() as current:
                    if parts == ["v1", "runs"]:
                        run_id, created = current.submit_result(body["spec"], body["request_key"])
                        self._send(201 if created else 200, {"run_id": run_id, "created": created})
                    elif len(parts) == 4 and parts[:2] == ["v1", "runs"] and parts[3] == "signals":
                        signal = current.signal(parts[2], body["name"], body["message_id"], body.get("payload"))
                        self._send(201, signal)
                    elif len(parts) == 4 and parts[:2] == ["v1", "runs"] and parts[3] == "cancel":
                        self._send(200, current.cancel(parts[2], role))
                    elif len(parts) == 4 and parts[:2] == ["v1", "approvals"] and parts[3] == "decision":
                        self._send(200, current.decide(parts[2], body["decision"], role))
                    else:
                        self._error(404, "NOT_FOUND", "endpoint not found")
            except KeyError as exc:
                self._error(400, "INVALID_SPEC", f"missing field: {exc.args[0]}")
            except BaseException as exc:
                self._error(_status(exc), getattr(exc, "code", "NEXUS_ERROR"), exc)

        def log_message(self, *_args):
            return

    return _BoundedHTTPServer((host, port), Handler, max_workers=max_workers,
                              socket_timeout=socket_timeout)


def serve(host, port, service, auth_tokens, **kwargs):
    server = make_server(host, port, service, auth_tokens, **kwargs)
    try:
        server.serve_forever()
    finally:
        server.server_close()
