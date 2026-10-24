import json
import threading
import urllib.error
import urllib.request

import pytest

from nexus import Nexus, Registry, RunSpec, StepSpec, Store, make_server


def request(server, method, path, body=None, token="secret"):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(f"http://127.0.0.1:{server.server_port}{path}", data=data, method=method)
    if token is not None:
        req.add_header("Authorization", f"Bearer {token}")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=2) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def test_authenticated_http_control_and_structured_errors(tmp_path):
    with Store(tmp_path / "api.sqlite") as store:
        api = Nexus(store)
        server = make_server("127.0.0.1", 0, api, "secret")
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
            assert request(server, "POST", "/v1/runs",
                           {"request_key": "http-1", "spec": spec})[0] == 200
            assert request(server, "GET", f"/v1/runs/{run_id}")[0] == 200
            status, signal = request(server, "POST", f"/v1/runs/{run_id}/signals",
                                     {"name": "review", "message_id": "m-1", "payload": {"ok": True}})
            assert status == 201
            assert signal["message_id"] == "m-1"
            assert request(server, "GET", f"/v1/runs/{run_id}/events")[0] == 200
            status, error = request(server, "POST", "/v1/runs",
                                    {"request_key": "http-2", "spec": {"bad": True}})
            assert status == 400
            assert error["error"]["code"] == "INVALID_SPEC"
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


def test_http_refuses_non_localhost_binding(tmp_path):
    with Store(tmp_path / "api.sqlite") as store:
        with pytest.raises(ValueError):
            make_server("0.0.0.0", 0, Nexus(store), "secret")
