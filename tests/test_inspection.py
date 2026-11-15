from copy import deepcopy

import pytest
from leanguard.engine import Engine
from leanguard.inspection import inspect_policy


def atoms(tree):
    if tree["op"] == "atom":
        yield tree
    for key in ("child", "left", "right"):
        if key in tree:
            yield from atoms(tree[key])


def test_inspection_preserves_manifest_and_parameters():
    with Engine("example") as engine:
        before = deepcopy(engine.manifest)
        tree = inspect_policy(engine)
        assert tree["engine_sha256"] == engine.fingerprint
        assert tree["schemas"] == engine.manifest["schemas"]
        rules = tree["rules"]
        assert [rule["id"] for rule in rules] == [r["id"] for r in before["rules"]]
        descriptions = [
            node["description"]
            for r in rules
            for node in atoms(r["condition"])
            if not node["opaque"]
        ]
        quota = next(item for item in descriptions if item["kind"] == "dispatch_quota")
        assert quota == {
            "kind": "dispatch_quota",
            "calls": 10,
            "amount": 10000,
            "window_seconds": 3600,
            "scope": "principal",
        }
        for rule in rules:
            for node in atoms(rule["condition"]):
                if not node["opaque"] and node["description"]["kind"] == "argument_schema":
                    assert node["description"]["schema"] == tree["schemas"][rule["actions"][0]]
                    assert node["description"]["max_depth"] == before["schema_max_depth"]
        tree["rules"].clear()
        assert engine.manifest == before


def test_old_or_future_inspection_is_explicitly_unsupported():
    with Engine("example") as engine:
        engine.manifest["inspection"]["version"] = 99
        with pytest.raises(ValueError, match="Unsupported"):
            inspect_policy(engine)
        engine.manifest.pop("inspection")
        with pytest.raises(ValueError, match="does not expose"):
            inspect_policy(engine)
