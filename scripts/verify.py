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
    dependencies = re.findall(r"depends on axioms: \[([^\]]*)\]", audit.stdout)
    if len(dependencies) < 17:
        raise RuntimeError("incomplete proof audit")
    standard = {"propext", "Classical.choice", "Quot.sound"}
    for group in dependencies:
        unexpected = {name.strip() for name in group.split(",") if name.strip()} - standard
        if unexpected:
            raise RuntimeError(f"nonstandard proof axioms: {unexpected}")
    run(sys.executable, "-m", "ruff", "check", "python", "tests", "scripts")
    run(sys.executable, "-m", "ruff", "format", "--check", "python", "tests", "scripts")
    run(sys.executable, "-m", "pytest", "-q")
    run(sys.executable, "-m", "leanguard.conformance")
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
