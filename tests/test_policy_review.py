from copy import deepcopy
from pathlib import Path

import pytest
from leanguard import GuardHost
from leanguard.demo import MemoryTools
from leanguard.engine import default_binary
from leanguard.policy_authoring import compile_document, example_document
from leanguard.policy_review import (
    compare_policies,
    create_bundle,
    create_review_key,
    record_review,
    run_scenarios,
    verify_bundle,
    verify_for_activation,
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
        "binding": "approval",
        "amount": 0,
        "input": {},
        "facts": {},
        **extra,
    }


@pytest.fixture
def corpus():
    history = [
        event("confirmed", "write", 600),
        event("dispatch", "read", 998, id="read", binding=""),
        event("success", "read", 999, id="read", binding=""),
    ]
    return {
        "format": "leanguard.scenarios",
        "version": 1,
        "cases": [
            {
                "id": "stale-approval",
                "request": event("request", "write", 1000, input={"value": "sensitive fixture"}),
                "history": history,
                "history_complete": True,
                "missing_evidence": [],
            }
        ],
    }


@pytest.fixture(scope="module")
def compiled(tmp_path_factory):
    return compile_document(
        example_document(),
        tmp_path_factory.mktemp("review-build"),
        Path(__file__).resolve().parents[1],
    )


def test_native_comparison_and_incomplete_evidence(compiled, corpus):
    compared = compare_policies(
        default_binary(), "example", compiled["binary"], "documents", corpus
    )
    assert compared["changes"] == [{"id": "stale-approval", "before": "allowed", "after": "denied"}]
    assert compared["structural_changes"]
    corpus["cases"][0]["history_complete"] = False
    result = run_scenarios(compiled["binary"], "documents", corpus)
    assert result["cases"][0]["assessment"] == "insufficient_evidence"
    corpus["cases"][0]["request"]["delegation"] = "unreplayed-grant"
    with pytest.raises(ValueError, match="Delegated"):
        run_scenarios(compiled["binary"], "documents", corpus)


def test_review_binds_artifact_and_local_authority(compiled, corpus, tmp_path):
    bundle = create_bundle(compiled["directory"], tmp_path / "bundle", corpus)
    directory = Path(bundle["directory"])
    assert "sensitive fixture" not in (directory / "results.json").read_text()
    assert not (directory / "scenarios.json").exists()
    key = tmp_path / "authority.key"
    create_review_key(key)
    review = record_review(directory, "accept", key)
    assert verify_bundle(directory)["bundle_sha256"] == review["bundle_sha256"]
    configured = verify_for_activation(directory, review, key)
    with GuardHost(
        configured["domain"],
        tmp_path / "fresh.sqlite",
        MemoryTools(),
        principal="p",
        session="s",
        binary=Path(configured["binary"]),
    ) as host:
        assert host.execute("read", {})["allow"]
    with pytest.raises(RuntimeError, match="compiled policy version mismatch"):
        GuardHost("example", tmp_path / "fresh.sqlite", MemoryTools(), principal="p", session="s")
    forged = deepcopy(review)
    forged["reviewer"]["name"] = "another person"
    with pytest.raises(ValueError, match="Unauthenticated"):
        verify_for_activation(directory, forged, key)
    rejected = record_review(directory, "reject", key)
    with pytest.raises(ValueError, match="does not accept"):
        verify_for_activation(directory, rejected, key)
    (directory / "Policy.lean").write_text("tampered")
    with pytest.raises(ValueError, match="changed"):
        verify_for_activation(directory, review, key)


def test_changed_corpus_invalidates_review_and_exports_are_explicit(compiled, corpus, tmp_path):
    key = tmp_path / "key"
    create_review_key(key)
    first = create_bundle(compiled["directory"], tmp_path / "one", corpus)
    review = record_review(first["directory"], "accept", key)
    corpus["cases"][0]["id"] = "changed-case"
    second = create_bundle(
        compiled["directory"], tmp_path / "two", corpus, include_scenario_data=True
    )
    assert "sensitive fixture" in (Path(second["directory"]) / "scenarios.json").read_text()
    with pytest.raises(ValueError, match="does not accept"):
        verify_for_activation(second["directory"], review, key)
    (Path(second["directory"]) / "unreviewed.txt").write_text("extra")
    with pytest.raises(ValueError, match="unreviewed"):
        verify_bundle(second["directory"])


def test_modified_build_cannot_be_bundled(compiled, corpus, tmp_path):
    path = Path(compiled["directory"]) / "Policy.lean"
    original = path.read_text()
    try:
        path.write_text(original + "\n-- changed after audit\n")
        with pytest.raises(ValueError, match="changed"):
            create_bundle(compiled["directory"], tmp_path / "bundle", corpus)
    finally:
        path.write_text(original)
