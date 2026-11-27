"""Versioned, display-only inspection of a compiled policy executable."""

from copy import deepcopy

from .engine import Engine


def inspect_policy(engine: Engine) -> dict:
    tree = deepcopy(engine.manifest.get("inspection"))
    if not isinstance(tree, dict) or tree.get("format") != "leanguard.inspection":
        raise ValueError("This executable does not expose policy inspection")
    if type(tree.get("version")) is not int or tree["version"] != 1:
        raise ValueError("Unsupported policy inspection version")
    return {
        **tree,
        "engine_sha256": engine.fingerprint,
        "properties": {
            "pack": deepcopy(engine.manifest.get("properties", [])),
            "engine": ["decision_sound", "decision_no_errors"],
            "note": "Declaration names identify compiled claims; source prose is not a proved specification.",
        },
        "deployment_assumptions": [
            "All covered effects pass through the host-owned adapter.",
            "Snapshots, identity, units and approval come from trusted application code.",
            "The journal has one execution authority and matches the engine fingerprint.",
        ],
    }
