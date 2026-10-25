from importlib import metadata, resources
import json
import subprocess
import sys
from nexus import Conflict, Runtime, Store
import pytest


def test_packaged_schema_and_metadata():
    assert resources.files("nexus").joinpath("schema.sql").is_file()
    assert metadata.version("nexus-agent-runtime") == "1.0.0a1"


def test_cli_init_and_version(tmp_path):
    result = subprocess.run([sys.executable, "-m", "nexus", "init", "--database", str(tmp_path/"x.db")],
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["settings"]["user_version"] == 2
    result = subprocess.run([sys.executable, "-m", "nexus", "--version"],
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0
    assert result.stdout.strip() == metadata.version("nexus-agent-runtime")


def test_cli_unknown_schema_has_structured_error(tmp_path):
    path = tmp_path/"legacy.db"
    with Runtime(path):
        pass
    before = path.read_bytes()
    result = subprocess.run([sys.executable,"-m","nexus","init","--database",str(path)],
                            capture_output=True,text=True,timeout=10)
    assert result.returncode == 2
    assert json.loads(result.stdout)["error"]["code"] == "CONFLICT"
    assert "Traceback" not in result.stderr
    assert path.read_bytes() == before


def test_legacy_runtime_cannot_modify_a_workflow_database(tmp_path):
    path = tmp_path/"workflow.db"
    with Store(path):
        pass
    before = path.read_bytes()
    with pytest.raises(ValueError, match="legacy"):
        Runtime(path)
    assert path.read_bytes() == before
