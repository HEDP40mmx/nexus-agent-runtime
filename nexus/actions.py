"""Small importable action examples for clean-launch qualification."""
import os
import time


def echo(value, context):
    return {"value": value, "attempt_no": context.attempt_no}


def environment_probe(value, context):
    return {
        "has_openai_key": bool(os.environ.get("OPENAI_API_KEY")),
        "has_nexus_token": bool(os.environ.get("NEXUS_BEARER_TOKEN")),
    }


def sleep_action(value, context):
    time.sleep(float(value.get("seconds", 1)))
    return {"finished": True}


def marker_action(value, context):
    """Write a marker only if the supervised action actually starts."""
    path = value["path"]
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("started")
    return {"started": True}
