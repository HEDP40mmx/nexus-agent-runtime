import json

from nexus.cli import main


def test_cli_init_demo_inspect_and_events(tmp_path, capsys):
    database = tmp_path / "cli.sqlite"
    assert main(["init", "--database", str(database)]) == 0
    capsys.readouterr()
    assert main(["demo", "--database", str(database), "--text", "cli-test"]) == 0
    demo = json.loads(capsys.readouterr().out)
    assert demo["run"]["status"] == "succeeded"
    run_id = demo["run_id"]
    assert main(["inspect", "--database", str(database), run_id]) == 0
    inspected = json.loads(capsys.readouterr().out)
    assert inspected["run_id"] == run_id
    assert main(["events", "--database", str(database), run_id]) == 0
    events = json.loads(capsys.readouterr().out)
    assert any(event["kind"] == "run_succeeded" for event in events["events"])


def test_cli_preflight_reports_isolation_as_unavailable_without_root(tmp_path, capsys):
    database = tmp_path / "preflight.sqlite"
    assert main(["preflight", "--database", str(database)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["ok"] is True
    isolated = next(item for item in result["checks"] if item["name"] == "isolated_profile")
    assert isolated["ok"] is True
    assert isolated["detail"]["available"] is False
