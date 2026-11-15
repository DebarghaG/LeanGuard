"""Native scenario comparison and artifact-bound local human review."""

import hashlib
import hmac
import os
import pwd
import secrets
import shutil
import tomllib
from datetime import UTC, datetime
from pathlib import Path

from .engine import Engine, canonical, digest
from .inspection import inspect_policy
from .policy_authoring import load_json, source_provenance
from .replay import audit


def run_scenarios(binary, domain, corpus):
    if not isinstance(corpus, dict) or set(corpus) != {"format", "version", "cases"}:
        raise ValueError("Expected a versioned scenario corpus")
    if (
        corpus["format"] != "leanguard.scenarios"
        or type(corpus["version"]) is not int
        or corpus["version"] != 1
    ):
        raise ValueError("Unsupported scenario format/version")
    if not isinstance(corpus["cases"], list) or not 0 < len(corpus["cases"]) <= 200:
        raise ValueError("Supply between 1 and 200 scenarios")
    ids, results = set(), []
    with Engine(domain, Path(binary)) as engine:
        for case in corpus["cases"]:
            if not isinstance(case, dict) or set(case) != {
                "id",
                "request",
                "history",
                "history_complete",
                "missing_evidence",
            }:
                raise ValueError(
                    "Scenario fields must be explicit: id, request, history, history_complete, missing_evidence"
                )
            if not isinstance(case["id"], str) or not case["id"] or case["id"] in ids:
                raise ValueError("Scenario IDs must be nonempty and unique")
            ids.add(case["id"])
            if type(case["history_complete"]) is not bool or not isinstance(case["history"], list):
                raise ValueError("Invalid scenario history")
            if not isinstance(case["missing_evidence"], list) or any(
                not isinstance(s, str) for s in case["missing_evidence"]
            ):
                raise ValueError("Missing-evidence labels must be strings")
            if not isinstance(case["request"], dict) or any(
                not isinstance(event, dict) for event in case["history"]
            ):
                raise ValueError("Scenario events must be objects")
            if any(
                any(event.get(key) for key in ["actor", "workflow", "delegation", "peer"])
                for event in [case["request"], *case["history"]]
            ):
                raise ValueError(
                    "Delegated scenario replay is not supported; use the multi-agent conformance tools"
                )
            result = audit(
                engine,
                case["request"],
                case["history"],
                history_complete=case["history_complete"],
                missing_evidence=case["missing_evidence"],
            )
            results.append({"id": case["id"], **result})
        return {
            "engine_sha256": engine.fingerprint,
            "domain": domain,
            "corpus_sha256": digest(corpus),
            "cases": results,
        }


def structural_changes(old, new, path=""):
    if isinstance(old, dict) and isinstance(new, dict):
        return [
            change
            for key in sorted(old.keys() | new.keys())
            for change in structural_changes(
                old.get(key), new.get(key), f"{path}/{key.replace('~', '~0').replace('/', '~1')}"
            )
        ]
    if old == new:
        return []
    return [{"path": path, "before": old, "after": new}]


def compare_policies(old_binary, old_domain, new_binary, new_domain, corpus):
    before = run_scenarios(old_binary, old_domain, corpus)
    after = run_scenarios(new_binary, new_domain, corpus)
    changes = []
    for old, new in zip(before["cases"], after["cases"], strict=True):
        if old["assessment"] != new["assessment"]:
            changes.append(
                {"id": old["id"], "before": old["assessment"], "after": new["assessment"]}
            )
    with (
        Engine(old_domain, Path(old_binary)) as old_engine,
        Engine(new_domain, Path(new_binary)) as new_engine,
    ):
        inspections = [inspect_policy(engine) for engine in [old_engine, new_engine]]
    structures = [
        {"rules": {r["id"]: r for r in tree["rules"]}, "schemas": tree["schemas"]}
        for tree in inspections
    ]
    return {
        "before": before,
        "after": after,
        "changes": changes,
        "structural_changes": structural_changes(*structures),
        "claim": "Sampled scenario results, not a proof of equivalence or of policy intent.",
    }


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def create_bundle(build_directory, output_directory, corpus, *, include_scenario_data=False):
    source, target = Path(build_directory).resolve(), Path(output_directory).resolve()
    build = load_json((source / "build.json").read_text())
    if build.get("format") != "leanguard.build" or build.get("version") != 1:
        raise ValueError("Unsupported build record")
    if target.exists():
        raise ValueError("Review bundle directory must not exist")
    for name, expected in build["files"].items():
        if (
            Path(name).name != name
            or (source / name).is_symlink()
            or _sha(source / name) != expected
        ):
            raise ValueError("Build inputs or audit output changed; rebuild before review")
    project = tomllib.loads((source / "lakefile.toml").read_text())["require"][0]["path"]
    if source_provenance(project) != build["provenance"]:
        raise ValueError("Dependency drift after compilation; rebuild before review")
    binary = source / ".lake/build/bin/policy-engine"
    if _sha(binary) != build["engine_sha256"]:
        raise ValueError("Compiled artifact changed")
    document = load_json((source / "policy.json").read_text())
    results = run_scenarios(binary, document["name"], corpus)
    target.mkdir(parents=True)
    for name in build["files"]:
        shutil.copyfile(source / name, target / name)
        if _sha(target / name) != build["files"][name]:
            raise ValueError("Build changed while creating the bundle")
    (target / "build.json").write_text(canonical(build) + "\n")
    shutil.copyfile(binary, target / "policy-engine")
    (target / "policy-engine").chmod(0o700)
    if include_scenario_data:
        (target / "scenarios.json").write_text(canonical(corpus) + "\n")
        (target / "results.json").write_text(canonical(results) + "\n")
    else:
        summary = {
            "corpus_sha256": results["corpus_sha256"],
            "cases": [{"id": c["id"], "assessment": c["assessment"]} for c in results["cases"]],
            "note": "Scenario inputs, facts and diagnostics omitted; full replay needs the private corpus.",
        }
        (target / "results.json").write_text(canonical(summary) + "\n")
    manifest = {
        "format": "leanguard.review-bundle",
        "version": 1,
        "domain": document["name"],
        "engine_sha256": build["engine_sha256"],
        "scenario_data_included": include_scenario_data,
        "files": {p.name: _sha(p) for p in sorted(target.iterdir())},
    }
    (target / "bundle.json").write_text(canonical(manifest) + "\n")
    verify_bundle(target)
    return {"directory": str(target), "bundle_sha256": digest(manifest), "manifest": manifest}


def verify_bundle(directory):
    directory = Path(directory).resolve()
    if (directory / "bundle.json").is_symlink():
        raise ValueError("Bundle manifest must be a regular file")
    manifest = load_json((directory / "bundle.json").read_text())
    if (
        manifest.get("format") != "leanguard.review-bundle"
        or type(manifest.get("version")) is not int
        or manifest["version"] != 1
    ):
        raise ValueError("Unsupported review bundle")
    files = manifest["files"]
    required = {
        "policy-engine",
        "policy.json",
        "Policy.lean",
        "Main.lean",
        "Audit.lean",
        "build.json",
        "inspection.json",
        "lakefile.toml",
        "lean-toolchain",
        "build.log",
        "lake-manifest.json",
        "results.json",
    }
    if (
        not isinstance(files, dict)
        or not required <= files.keys()
        or {p.name for p in directory.iterdir()} != set(files) | {"bundle.json"}
    ):
        raise ValueError("Bundle contains missing or unreviewed files")
    for name, expected in files.items():
        path = directory / name
        if (
            Path(name).name != name
            or not path.is_file()
            or path.is_symlink()
            or _sha(path) != expected
        ):
            raise ValueError("Bundle contents changed")
    if files.get("policy-engine") != manifest["engine_sha256"]:
        raise ValueError("Bundle executable identity mismatch")
    return {"bundle_sha256": digest(manifest), "manifest": manifest}


def create_review_key(path):
    """Create a local operator capability; never expose it to model tools."""
    path = Path(path)
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as stream:
        stream.write(secrets.token_bytes(32))


def _key(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_mode & 0o077:
        raise ValueError("Review key must be a private regular file")
    value = path.read_bytes()
    if len(value) != 32:
        raise ValueError("Invalid review key")
    return value


def record_review(directory, decision, key_path):
    if decision not in {"accept", "reject"}:
        raise ValueError("Review decision must be accept or reject")
    verified = verify_bundle(directory)
    record = {
        "format": "leanguard.local-review",
        "version": 1,
        "bundle_sha256": verified["bundle_sha256"],
        "decision": decision,
        "reviewer": {"uid": os.getuid(), "name": pwd.getpwuid(os.getuid()).pw_name},
        "time": datetime.now(UTC).isoformat(),
    }
    return {
        **record,
        "mac": hmac.new(_key(key_path), canonical(record).encode(), hashlib.sha256).hexdigest(),
    }


def verify_for_activation(directory, review, key_path):
    verified = verify_bundle(directory)
    payload = {key: value for key, value in review.items() if key != "mac"}
    expected = hmac.new(_key(key_path), canonical(payload).encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, str(review.get("mac", ""))):
        raise ValueError("Unauthenticated local review")
    if payload.get("format") != "leanguard.local-review" or payload.get("version") != 1:
        raise ValueError("Unsupported local review")
    if (
        payload.get("decision") != "accept"
        or payload.get("bundle_sha256") != verified["bundle_sha256"]
    ):
        raise ValueError("Review does not accept this exact bundle")
    # The application still supplies a journal to GuardHost; its fingerprint check remains intact.
    return {
        "binary": str(Path(directory).resolve() / "policy-engine"),
        "domain": verified["manifest"]["domain"],
        "engine_sha256": verified["manifest"]["engine_sha256"],
    }
