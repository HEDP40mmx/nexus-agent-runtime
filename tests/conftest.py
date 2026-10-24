import sys
import pytest
from nexus import Store, Nexus, StepSpec, RunSpec


def pytest_sessionstart(session):
    if sys.version_info[:2] != (3, 12):
        raise pytest.UsageError("The Nexus v1 acceptance suite requires Python 3.12")


class Clock:
    def __init__(self, value=100000):
        self.value = value

    def now_ms(self):
        return self.value


@pytest.fixture
def env(tmp_path):
    clock = Clock()
    with Store(tmp_path / "nexus.sqlite", clock=clock) as store:
        yield store, Nexus(store), clock


def action(id="a", **kwargs):
    return StepSpec.action(id=id, action="echo", version="1", input={"text": id}, **kwargs)


def spec(*steps):
    return RunSpec(steps or (action(),))
