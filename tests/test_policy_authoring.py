from copy import deepcopy
from pathlib import Path

import pytest
from leanguard.engine import Engine
from leanguard.policy_authoring import compile_document, example_document, generate_lean, load_json
from leanguard.replay import audit


def test_deterministic_generation_and_escaped_source():
    document = example_document()
    document["rules"][0]["source"] = 'A quote " and a newline\n#eval IO.println "not code"'
    generated = generate_lean(document)
    assert generated == generate_lean(deepcopy(document))
    assert "\\n#eval" in generated and '\\"not code\\"' in generated
    assert "confirmedWithin 300" in generated and "quota 10 10000 3600" in generated
    assert '(.object ["value"] [("value", .string)])' in generated


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d.update(version=2),
        lambda d: d.update(version=True),
        lambda d: d["rules"].append(deepcopy(d["rules"][0])),
        lambda d: d["rules"][0].update(actions=["missing"]),
        lambda d: d["rules"][0].update(condition={"kind": "opaque", "code": "anything"}),
        lambda d: d["rules"][3]["condition"].update(amount=True),
        lambda d: d["rules"][3]["condition"].update(amount=2**53),
        lambda d: d["rules"][3]["condition"].update(window_seconds=-1),
        lambda d: d["tools"][0]["schema"].update(additionalProperties=False),
        lambda d: d["tools"][0]["schema"].update(required=["missing"]),
    ],
)
def test_invalid_or_unsupported_documents_fail_closed(mutate):
    document = example_document()
    mutate(document)
    with pytest.raises(ValueError):
        generate_lean(document)


def test_duplicate_json_and_nan_rejected():
    for text in ['{"version":1,"version":2}', '{"amount":NaN}']:
        with pytest.raises(ValueError):
            load_json(text)


@pytest.fixture(scope="module")
def compiled(tmp_path_factory):
    return compile_document(
        example_document(), tmp_path_factory.mktemp("authored"), Path(__file__).resolve().parents[1]
    )


def event(kind, action, time, **extra):
    return {
        "id": f"{kind}-{time}",
        "time": time,
        "kind": kind,
        "principal": "p",
        "session": "s",
        "action": action,
        "resource": "document",
        "binding": "binding",
        "amount": 0,
        "input": {},
        "facts": {},
        **extra,
    }


def test_compiled_pack_native_boundaries(compiled):
    history = [
        event("confirmed", "write", 700),
        event("dispatch", "read", 998, id="read", binding=""),
        event("success", "read", 999, id="read", binding=""),
    ]
    request = event("request", "write", 1000, input={"value": "new"})
    with Engine("documents", Path(compiled["binary"])) as engine:
        assert audit(engine, request, history)["assessment"] == "allowed"
        assert engine.manifest["properties"] == []  # No invented pack-intent proof.
        expired = deepcopy(history)
        expired[0]["time"] = 699
        assert audit(engine, request, expired)["assessment"] == "denied"
        wrong_resource = deepcopy(history)
        wrong_resource[-1]["resource"] = "another"
        assert audit(engine, request, wrong_resource)["assessment"] == "denied"
        too_large = {**request, "amount": 10001}
        assert audit(engine, too_large, history)["assessment"] == "denied"
        malformed = {**request, "input": {"value": False}}
        assert audit(engine, malformed, history)["assessment"] == "insufficient_evidence"
        unknown = deepcopy(history)
        unknown[-1]["kind"] = "unknown"
        assert audit(engine, request, unknown)["assessment"] == "denied"
        assert engine.request({"op": "status", "version": engine.version})["events"] == 0


def test_build_wont_overwrite_existing_work(compiled):
    with pytest.raises(ValueError, match="new or empty"):
        compile_document(
            example_document(), compiled["directory"], Path(__file__).resolve().parents[1]
        )
