"""Recheck every saved native audit and account for every normalized assistant call."""

import argparse
import gzip
import hashlib
import json
from collections import Counter
from contextlib import ExitStack
from pathlib import Path

from .engine import Engine, canonical
from .trajectory_replay import classify


def verify(root, output):
    report = json.loads((output / "report.json").read_text())
    normalized = root / "normalized.jsonl"
    if hashlib.sha256(normalized.read_bytes()).hexdigest() != report["normalized_sha256"]:
        raise ValueError("normalized input fingerprint mismatch")
    expected = {}
    with normalized.open() as stream:
        for index, line in enumerate(stream):
            if report["limit"] is not None and index >= report["limit"]:
                break
            record = json.loads(line)
            if record["id"] in expected:
                raise ValueError("duplicate trajectory ID")
            expected[record["id"]] = (
                record["domain"],
                sum(len(m["calls"]) for m in record["messages"] if m["role"] == "assistant"),
            )
    observed = Counter()
    rules = {}
    total = 0
    with ExitStack() as stack:
        engines = {
            d: stack.enter_context(Engine(d, timeout=60)) for d in ("retail", "airline", "telecom")
        }
        if {d: e.fingerprint for d, e in engines.items()} != report["policy_binary_sha256"]:
            raise ValueError("native binary fingerprint mismatch")
        journal = stack.enter_context(gzip.open(output / "native-audits.jsonl.gz", "rt"))
        calls = stack.enter_context((output / "calls.jsonl").open())
        for line in journal:
            saved = json.loads(line)
            call = json.loads(next(calls))
            trajectory = saved["trajectory"]
            if trajectory not in expected or saved["call"] != observed[trajectory]:
                raise ValueError("unexpected or nonconsecutive native audit")
            if (call["trajectory"], call["call"]) != (trajectory, saved["call"]):
                raise ValueError("call/audit identity mismatch")
            actual = engines[expected[trajectory][0]].request(saved["command"])
            if actual != saved["response"]:
                raise ValueError(f"native response mismatch: {trajectory}/{saved['call']}")
            if call["native_decision"] != actual["decision"] or call["rules"] != actual["rules"]:
                raise ValueError("exported decision differs from native audit")
            classification = classify(
                actual,
                saved["command"]["facts"],
                call["supported"],
                call["schema_errors"],
                call["action"],
                call["prior_unsupported_dispatch"],
            )
            if any(call[k] != v for k, v in classification.items()):
                raise ValueError("exported classification differs from native audit")
            for rule, value in actual["rules"].items():
                key = expected[trajectory][0] + "/" + rule
                counts = rules.setdefault(key, Counter())
                counts["evaluated"] += 1
                counts["true" if value else "false"] += 1
                counts["unavailable"] += rule in call["unavailable_rules"]
                counts["recorded_failure"] += rule in call["recorded_policy_failures"]
            observed[trajectory] += 1
            total += 1
        if next(calls, None) is not None:
            raise ValueError("exported call without native audit")
    if any(observed[id] != count for id, (_, count) in expected.items()):
        raise ValueError("incomplete assistant-call coverage")
    summaries = [json.loads(s) for s in (output / "trajectories.jsonl").open()]
    if len(summaries) != len(expected) or {s["id"] for s in summaries} != set(expected):
        raise ValueError("incomplete trajectory coverage")
    if any(s["assistant_calls"] != observed[s["id"]] for s in summaries):
        raise ValueError("trajectory call count mismatch")
    result = {
        "status": "every_native_response_matches",
        "trajectories": len(expected),
        "assistant_calls": total,
        "rules": rules,
        "rule_evaluations": sum(c["evaluated"] for c in rules.values()),
        "policy_binary_sha256": report["policy_binary_sha256"],
        "artifacts_sha256": {},
    }
    for name in ("native-audits.jsonl.gz", "calls.jsonl", "trajectories.jsonl", "report.json"):
        with (output / name).open("rb") as stream:
            result["artifacts_sha256"][name] = hashlib.file_digest(stream, "sha256").hexdigest()
    (output / "verification.json").write_text(json.dumps(result, indent=2) + "\n")
    return {k: v for k, v in result.items() if k != "rules"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    print(canonical(verify(args.root.resolve(), args.output.resolve())))


if __name__ == "__main__":
    main()
