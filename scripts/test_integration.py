"""Install one optional SDK environment and run its mandatory native conformance test."""

import argparse
import json
import os
import subprocess
import sys
import tomllib
from pathlib import Path


def main():
    root = Path(__file__).resolve().parents[1]
    with (root / "pyproject.toml").open("rb") as source:
        extras = tomllib.load(source)["project"]["optional-dependencies"]
    integrations = {
        key.removeprefix("agent-"): value
        for key, value in extras.items()
        if key.startswith("agent-")
    }
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("framework", nargs="?", choices=sorted(integrations))
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--install", action="store_true")
    args = parser.parse_args()
    if args.list:
        print(json.dumps(sorted(integrations)))
        return
    if not args.framework:
        parser.error("framework is required without --list")
    if args.install:
        subprocess.run(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                *extras["test"],
                *integrations[args.framework],
            ],
            check=True,
        )
    env = {
        **os.environ,
        "PYTHONPATH": str(root / "python"),
        "LEANGUARD_REQUIRE_SDK": args.framework,
        "HAYSTACK_TELEMETRY_ENABLED": "false",
        "CREWAI_TELEMETRY_ENABLED": "false",
    }
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "tests/integrations/test_python_sdks.py",
            "-k",
            f"{args.framework}-",
        ],
        cwd=root,
        env=env,
        check=True,
    )


if __name__ == "__main__":
    main()
