"""Operational CLI for initializing, inspecting, and running Nexus workflows."""
from __future__ import annotations

import argparse
from importlib.metadata import version
import json
import sys
from pathlib import Path

from .actions import echo
from .engine import Engine
from .models import NexusError, RunSpec
from .preflight import run as preflight_run
from .registry import Registry
from .service import Nexus
from .store import Store
from .worker import Worker


def _json_input(value):
    if value == "-":
        return json.load(sys.stdin)
    with Path(value).open(encoding="utf-8") as handle:
        return json.load(handle)


def _registry():
    return Registry().register("echo", "1", echo)


def _service(database):
    return Store(database)


def build_parser():
    parser = argparse.ArgumentParser(prog="nexus")
    parser.add_argument("--version", action="version", version=version("nexus-agent-runtime"))
    commands = parser.add_subparsers(dest="command", required=True)

    init = commands.add_parser("init", help="Initialize or validate a workflow database")
    init.add_argument("--database", required=True)
    init.add_argument("--journal", choices=("auto", "wal", "delete"), default="auto")

    submit = commands.add_parser("submit", help="Submit a JSON workflow specification")
    submit.add_argument("--database", required=True)
    submit.add_argument("--spec", required=True, help="JSON file, or - for stdin")
    submit.add_argument("--request-key", required=True)

    inspect = commands.add_parser("inspect", help="Inspect a durable run")
    inspect.add_argument("--database", required=True)
    inspect.add_argument("run_id")

    events = commands.add_parser("events", help="Read durable run events")
    events.add_argument("--database", required=True)
    events.add_argument("run_id")
    events.add_argument("--after", type=int, default=0)
    events.add_argument("--limit", type=int, default=100)

    cancel = commands.add_parser("cancel", help="Cancel a run")
    cancel.add_argument("--database", required=True)
    cancel.add_argument("run_id")
    cancel.add_argument("--principal", default="cli")

    approve = commands.add_parser("approve", help="Approve or deny a pending approval")
    approve.add_argument("--database", required=True)
    approve.add_argument("approval_id")
    approve.add_argument("decision", choices=("approved", "denied"))
    approve.add_argument("--principal", default="cli")

    signal = commands.add_parser("signal", help="Deliver a durable workflow signal")
    signal.add_argument("--database", required=True)
    signal.add_argument("run_id")
    signal.add_argument("name")
    signal.add_argument("message_id")
    signal.add_argument("--payload", default="-", help="JSON file, or - for stdin")

    worker = commands.add_parser("worker", help="Run the local durable worker")
    worker.add_argument("--database", required=True)
    worker.add_argument("--once", action="store_true")
    worker.add_argument("--poll-interval", type=float, default=0.1)
    worker.add_argument("--profile", choices=("trusted", "restricted"), default="trusted")

    serve = commands.add_parser("serve", help="Serve authenticated localhost HTTP controls")
    serve.add_argument("--database", required=True)
    serve.add_argument("--host", default="127.0.0.1", choices=("127.0.0.1", "::1", "localhost"))
    serve.add_argument("--port", type=int, default=8080)
    serve.add_argument("--operator-token", required=True)
    serve.add_argument("--admin-token")
    serve.add_argument("--reader-token")

    preflight = commands.add_parser("preflight", help="Validate the local deployment")
    preflight.add_argument("--database", required=True)
    preflight.add_argument("--isolated-root")

    demo = commands.add_parser("demo", help="Run an offline echo workflow end-to-end")
    demo.add_argument("--database", required=True)
    demo.add_argument("--text", default="hello from nexus")

    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        if args.command == "init":
            with Store(args.database, journal=args.journal) as store:
                result = {"ok": True, "settings": store.settings()}
        elif args.command == "preflight":
            result = preflight_run(args.database, isolated_root=args.isolated_root)
        elif args.command == "submit":
            with _service(args.database) as store:
                result = dict(zip(("run_id", "created"), Nexus(store).submit_result(
                    RunSpec.from_dict(_json_input(args.spec)), args.request_key)))
        elif args.command == "inspect":
            with _service(args.database) as store:
                result = Nexus(store).get_run(args.run_id)
        elif args.command == "events":
            with _service(args.database) as store:
                result = {"events": Nexus(store).events(args.run_id, args.after, args.limit)}
        elif args.command == "cancel":
            with _service(args.database) as store:
                result = Nexus(store).cancel(args.run_id, args.principal)
        elif args.command == "approve":
            with _service(args.database) as store:
                result = Nexus(store).decide(args.approval_id, args.decision, args.principal)
        elif args.command == "signal":
            with _service(args.database) as store:
                result = Nexus(store).signal(args.run_id, args.name, args.message_id,
                                             _json_input(args.payload))
        elif args.command == "worker":
            with _service(args.database) as store:
                worker = Worker(store, _registry(), poll_interval=args.poll_interval,
                                execution_profile=args.profile)
                result = {"worked": worker.run_once()} if args.once else _run_worker(worker)
        elif args.command == "serve":
            from .api import serve
            tokens = {"operator": args.operator_token}
            if args.reader_token:
                tokens["reader"] = args.reader_token
            if args.admin_token:
                tokens["admin"] = args.admin_token
            with _service(args.database) as store:
                serve(args.host, args.port, Nexus(store), tokens)
            return 0
        elif args.command == "demo":
            with _service(args.database) as store:
                api = Nexus(store)
                spec = RunSpec.from_dict({"steps": [{"id": "echo", "kind": "action",
                    "action": "echo", "version": "1", "input": {"text": args.text}}]})
                run_id, created = api.submit_result(spec, "cli-demo")
                worked = Worker(store, _registry()).run_once()
                result = {"run_id": run_id, "created": created, "worked": worked,
                          "run": api.get_run(run_id)}
        print(json.dumps(result, sort_keys=True, default=str))
        return 0 if result.get("ok", True) is not False else 1
    except (NexusError, OSError, ValueError, KeyError) as exc:
        print(json.dumps({"error": {"code": getattr(exc, "code", "CONFIGURATION_ERROR"),
                                     "message": str(exc)}}, sort_keys=True))
        return 2


def _run_worker(worker):
    worker.run_forever()
    return {"stopped": True}


if __name__ == "__main__":
    raise SystemExit(main())
