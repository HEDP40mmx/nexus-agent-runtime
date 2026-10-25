import pytest

from nexus import Engine, Nexus, Registry, ResourceLimits, RunSpec, StepSpec, Store
from nexus.actions import echo


def test_isolated_limits_require_positive_values_and_absolute_root(tmp_path):
    limits = ResourceLimits(cpu_seconds=1, memory_bytes=64 * 1024 * 1024,
                            file_bytes=1024, max_processes=4,
                            filesystem_root=str(tmp_path), network_mode="none")
    limits.validate("isolated")
    with pytest.raises(ValueError):
        ResourceLimits(cpu_seconds=0, filesystem_root=str(tmp_path)).validate("isolated")
    with pytest.raises(ValueError):
        ResourceLimits(filesystem_root="relative-root").validate("isolated")
    with pytest.raises(ValueError):
        ResourceLimits(max_processes=0, filesystem_root=str(tmp_path)).validate("isolated")
    with pytest.raises(ValueError):
        ResourceLimits(network_mode="host", filesystem_root=str(tmp_path)).validate("isolated")


def test_isolated_profile_fails_closed_for_missing_filesystem_root(tmp_path):
    with Store(tmp_path / "isolated.sqlite") as store:
        api = Nexus(store)
        registry = Registry().register("echo", "1", echo)
        run_id = api.submit(RunSpec((StepSpec.action(id="a", action="echo", version="1", input={}),)),
                            "isolated-missing-root")
        engine = Engine(
            store, registry, execution_profile="isolated",
            resource_limits=ResourceLimits(filesystem_root=str(tmp_path / "does-not-exist")),
        )
        assert engine.execute_once() is True
        run = api.get_run(run_id)
        assert run["status"] == "failed"
        assert run["error_code"] == "ISOLATION_UNAVAILABLE"
