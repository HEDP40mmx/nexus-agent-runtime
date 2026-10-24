"""Small authenticated HTTP control adapter for the fresh-v1 service."""
from __future__ import annotations

import hmac
import json
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from .models import Conflict, InvalidSpec, NexusError, NotFound, canonical
from .service import Nexus
from .store import Store

MAX_BODY = 65536


def _status(exc):
    if isinstance(exc, NotFound):
        return 404
    if isinstance(exc, Conflict):
        return 409
    if isinstance(exc, InvalidSpec):
        return 400
    return 500


def make_server(host, port, service, bearer_token):
    if host not in ("127.0.0.1", "::1", "localhost"):
        raise ValueError("HTTP control must bind to localhost")
    if not isinstance(bearer_token, str) or not bearer_token:
        raise ValueError("bearer token is required")

    class Handler(BaseHTTPRequestHandler):
        server_version = "NexusHTTP/1"

        def _send(self, status, body):
            raw = canonical(body).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def _error(self, status, code, message):
            self._send(status, {"error": {"code": code, "message": str(message)[:4096]}})

        def _auth(self):
            value = self.headers.get("Authorization", "")
            supplied = value[7:] if value.startswith("Bearer ") else ""
            return bool(supplied) and hmac.compare_digest(supplied, bearer_token)

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

        def _principal(self):
            return self.headers.get("X-Principal", "http-bearer")

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
            if not self._auth():
                self._error(401, "UNAUTHORIZED", "valid bearer token required")
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
            if not self._auth():
                self._error(401, "UNAUTHORIZED", "valid bearer token required")
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
                        self._send(200, current.cancel(parts[2], self._principal()))
                    elif len(parts) == 4 and parts[:2] == ["v1", "approvals"] and parts[3] == "decision":
                        self._send(200, current.decide(parts[2], body["decision"], self._principal()))
                    else:
                        self._error(404, "NOT_FOUND", "endpoint not found")
            except KeyError as exc:
                self._error(400, "INVALID_SPEC", f"missing field: {exc.args[0]}")
            except BaseException as exc:
                self._error(_status(exc), getattr(exc, "code", "NEXUS_ERROR"), exc)

        def log_message(self, *_args):
            return

    return ThreadingHTTPServer((host, port), Handler)


def serve(host, port, service, bearer_token):
    server = make_server(host, port, service, bearer_token)
    try:
        server.serve_forever()
    finally:
        server.server_close()
