import json
import threading
import urllib.error
import urllib.request

import pytest

from nexus import Nexus, RunSpec, StepSpec, Store, make_server


TOKENS = {"reader": "reader-secret", "operator": "operator-secret", "admin": "admin-secret"}


def request(server, method, path, body=None, token="operator-secret", principal=None):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(f"http://127.0.0.1:{server.server_port}{path}", data=data, method=method)
    if token is not None:
        req.add_header("Authorization", f"Bearer {token}")
    if principal is not None:
        req.add_header("X-Principal", principal)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=2) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def test_authenticated_http_roles_controls_and_structured_errors(tmp_path):
    with Store(tmp_path / "api.sqlite") as store:
        api = Nexus(store)
        server = make_server("127.0.0.1", 0, api, TOKENS)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            assert request(server, "GET", "/healthz", token=None) == (200, {"ok": True})
            assert request(server, "GET", "/v1/runs/missing", token=None)[0] == 401
            spec = RunSpec((StepSpec.wait_signal(id="wait", name="review"),)).to_dict()
            status, submitted = request(server, "POST", "/v1/runs",
                                         {"request_key": "http-1", "spec": spec})
            assert status == 201
            run_id = submitted["run_id"]
            assert request(server, "GET", f"/v1/runs/{run_id}", token=TOKENS["reader"])[0] == 200
            assert request(server, "POST", "/v1/runs", {
                "request_key": "reader-denied", "spec": spec}, token=TOKENS["reader"])[0] == 403
            assert request(server, "POST", "/v1/runs",
                           {"request_key": "http-1", "spec": spec})[0] == 200
            status, signal = request(server, "POST", f"/v1/runs/{run_id}/signals",
                                     {"name": "review", "message_id": "m-1", "payload": {"ok": True}},
                                     principal="admin")
            assert status == 201
            assert signal["message_id"] == "m-1"
            assert request(server, "GET", f"/v1/runs/{run_id}/events", token=TOKENS["reader"])[0] == 200
            assert request(server, "POST", f"/v1/runs/{run_id}/cancel",
                           {}, principal="admin")[0] == 200
            status, error = request(server, "POST", "/v1/runs",
                                    {"request_key": "http-2", "spec": {"bad": True}})
            assert status == 400
            assert error["error"]["code"] == "INVALID_SPEC"
            events = api.events(run_id)
            cancelled = [e for e in events if e["kind"] == "run_cancelled"]
            assert cancelled[0]["payload"]["principal"] == "operator"
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


def test_rate_limit_is_per_client_and_health_is_exempt(tmp_path):
    with Store(tmp_path / "api.sqlite") as store:
        server = make_server("127.0.0.1", 0, Nexus(store), TOKENS,
                             max_requests=2, window_seconds=60)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            assert request(server, "GET", "/healthz", token=None)[0] == 200
            assert request(server, "GET", "/v1/runs/missing")[0] == 404
            assert request(server, "GET", "/v1/runs/missing")[0] == 404
            status, error = request(server, "GET", "/v1/runs/missing")
            assert status == 429
            assert error["error"]["code"] == "RATE_LIMITED"
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


def test_auth_configuration_is_strict(tmp_path):
    with Store(tmp_path / "api.sqlite") as store:
        api = Nexus(store)
        with pytest.raises(ValueError):
            make_server("127.0.0.1", 0, api, {"reader": "same", "operator": "same"})
        with pytest.raises(ValueError):
            make_server("127.0.0.1", 0, api, {"unknown": "secret"})


def test_http_refuses_non_localhost_binding(tmp_path):
    with Store(tmp_path / "api.sqlite") as store:
        with pytest.raises(ValueError):
            make_server("0.0.0.0", 0, Nexus(store), TOKENS)
