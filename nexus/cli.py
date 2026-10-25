"""Commands available in the atomic-state implementation milestone."""
import argparse
from importlib.metadata import version
import json
from .models import NexusError
from .store import Store


def main(argv=None):
    parser = argparse.ArgumentParser(prog="nexus")
    parser.add_argument("--version", action="version", version=version("nexus-agent-runtime"))
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init", help="Initialize or validate a v1 workflow database")
    init.add_argument("--database", required=True)
    init.add_argument("--journal", choices=("auto", "wal", "delete"), default="auto")
    args = parser.parse_args(argv)
    try:
        with Store(args.database, journal=args.journal) as store:
            print(json.dumps({"ok": True, "settings": store.settings()}, sort_keys=True))
        return 0
    except (NexusError, OSError) as exc:
        print(json.dumps({"error": {"code": getattr(exc, "code", "CONFIGURATION_ERROR"),
                                   "message": str(exc)}}))
        return 2
