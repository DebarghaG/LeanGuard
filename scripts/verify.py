"""Run the local verification gate without model calls or external writes."""

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(*command, capture=False):
    result = subprocess.run(
        command, cwd=ROOT, check=False, text=True, stdout=subprocess.PIPE if capture else None
    )
    if result.returncode and capture:
        print(result.stdout, end="")
    result.check_returncode()
    return result


def main():
    run("lake", "build")
    audit = run("lake", "env", "lean", "Audit.lean", capture=True)
    print(audit.stdout, end="")
    expected = re.findall(r"^#print axioms (\S+)$", (ROOT / "Audit.lean").read_text(), re.MULTILINE)
    reports = re.findall(
        r"'([^']+)' (?:depends on axioms: \[([^\]]*)\]|does not depend on any axioms)",
        audit.stdout,
    )
    if len(reports) != len(expected) or {name for name, _ in reports} != set(expected):
        raise RuntimeError("incomplete proof audit")
    standard = {"propext", "Classical.choice", "Quot.sound"}
    for _, group in reports:
        unexpected = {name.strip() for name in group.split(",") if name.strip()} - standard
        if unexpected:
            raise RuntimeError(f"nonstandard proof axioms: {unexpected}")
    sources = ("python", "tests", "scripts", "setup.py", "examples/custom_policy/run.py")
    run(sys.executable, "-m", "ruff", "check", *sources)
    run(sys.executable, "-m", "ruff", "format", "--check", *sources)
    run(sys.executable, "-m", "pytest", "-q", "-m", "not live")
    run(sys.executable, "-m", "scripts.conformance")
    from leanguard import Engine

    coverage = {}
    for domain in ("retail", "airline", "telecom"):
        with Engine(domain) as engine:
            rules = engine.manifest["rules"]
            coverage[domain] = {
                "rules": len(rules),
                "actions": len({action for rule in rules for action in rule["actions"]}),
            }
    print(json.dumps({"verification": "passed", "policy_registry": coverage}, indent=2))


if __name__ == "__main__":
    main()
