import pytest
from nexus import InvalidSpec, RetryPolicy, RunSpec, StepSpec
from nexus.models import canonical, digest, strict_loads
from .conftest import action, spec


@pytest.mark.parametrize("raw", [b'{"a":1,"a":2}', b'{"x":NaN}', b'{"x":Infinity}', b'\xff',
                                     b'{', b'0'*65537, b'['*34+b'0'+b']'*34])
def test_strict_json_rejects_bad_data(raw):
    with pytest.raises(InvalidSpec):
        strict_loads(raw)


@pytest.mark.parametrize("change", [dict(max_attempts=True), dict(max_attempts=21),
                                        dict(base_delay_ms=-1), dict(cap_delay_ms=1)])
def test_retry_bounds(change):
    with pytest.raises(InvalidSpec):
        RetryPolicy(**change)


def test_submission_is_deeply_immutable():
    data = {"a": [1]}
    s = StepSpec.action(id="a", action="echo", version="1", input=data)
    before = s.to_dict()
    data["a"].append(2)
    s.to_dict()["input"]["a"].append(3)
    assert s.to_dict() == before
    assert digest({"a":1,"b":2}) == digest({"b":2,"a":1})
    assert canonical({"b":2,"a":1}) == '{"a":1,"b":2}'


@pytest.mark.parametrize("obj", [{"steps":[]}, {"steps":[{"kind":"other"}]},
                                    {"steps":[{"kind":"wait_signal","id":"a","name":"x","input":{}}]},
                                    {"steps":[action().to_dict(), action().to_dict()]},
                                    {"steps":[{**action().to_dict(),"timeout_ms":True}]},
                                    {"steps":[{**action().to_dict(),"extra":True}]}])
def test_invalid_specs(obj):
    with pytest.raises(InvalidSpec):
        RunSpec.from_dict(obj)


def test_normalized_spec_round_trip():
    original = spec(action(), StepSpec.wait_signal(id="b", name="ready"))
    assert RunSpec.from_dict(strict_loads(canonical(original.to_dict()))) == original
