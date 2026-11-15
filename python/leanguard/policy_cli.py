"""Trusted, offline policy authoring commands. These are never agent tools."""

import argparse
import json
from pathlib import Path

from .engine import Engine
from .inspection import inspect_policy
from .policy_authoring import compile_document, example_document, generate_lean, load_json
from .policy_review import (
    compare_policies,
    create_bundle,
    create_review_key,
    record_review,
    run_scenarios,
    verify_for_activation,
)


def main():
    parser = argparse.ArgumentParser(description="Author and inspect LeanGuard policies")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("new", help="Print an editable example authoring document")
    generate = sub.add_parser("generate", help="Validate a document and print its Lean source")
    generate.add_argument("document", type=Path)
    compile_parser = sub.add_parser("compile", help="Build and axiom-audit a generated pack")
    compile_parser.add_argument("document", type=Path)
    compile_parser.add_argument("directory", type=Path)
    compile_parser.add_argument(
        "--project", type=Path, required=True, help="Pinned LeanGuard source checkout"
    )
    inspect = sub.add_parser("inspect", help="Print the exact compiled inspection document")
    inspect.add_argument("domain")
    inspect.add_argument("--binary", type=Path)
    scenarios = sub.add_parser(
        "scenarios", help="Evaluate fixture histories without dispatching tools"
    )
    scenarios.add_argument("domain")
    scenarios.add_argument("binary", type=Path)
    scenarios.add_argument("corpus", type=Path)
    compare = sub.add_parser("compare", help="Compare two compiled policies on the same scenarios")
    compare.add_argument("old_domain")
    compare.add_argument("old_binary", type=Path)
    compare.add_argument("new_domain")
    compare.add_argument("new_binary", type=Path)
    compare.add_argument("corpus", type=Path)
    bundle = sub.add_parser("bundle", help="Create an artifact-bound review bundle")
    bundle.add_argument("build_directory", type=Path)
    bundle.add_argument("output_directory", type=Path)
    bundle.add_argument("corpus", type=Path)
    bundle.add_argument("--include-scenario-data", action="store_true")
    key = sub.add_parser("review-key", help="Create a private local operator review key")
    key.add_argument("path", type=Path)
    review = sub.add_parser(
        "review", help="Record a trusted local human's decision on an exact bundle"
    )
    review.add_argument("directory", type=Path)
    review.add_argument("decision", choices=["accept", "reject"])
    review.add_argument("--key", type=Path, required=True)
    verify = sub.add_parser("verify-review", help="Verify bundle identity before activation")
    verify.add_argument("directory", type=Path)
    verify.add_argument("review", type=Path)
    verify.add_argument("--key", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "new":
        print(json.dumps(example_document(), indent=2))
    elif args.command == "generate":
        print(generate_lean(load_json(args.document.read_text())), end="")
    elif args.command == "compile":
        print(
            json.dumps(
                compile_document(
                    load_json(args.document.read_text()), args.directory, args.project
                ),
                indent=2,
            )
        )
    elif args.command == "scenarios":
        print(
            json.dumps(
                run_scenarios(args.binary, args.domain, load_json(args.corpus.read_text())),
                indent=2,
            )
        )
    elif args.command == "compare":
        print(
            json.dumps(
                compare_policies(
                    args.old_binary,
                    args.old_domain,
                    args.new_binary,
                    args.new_domain,
                    load_json(args.corpus.read_text()),
                ),
                indent=2,
            )
        )
    elif args.command == "bundle":
        print(
            json.dumps(
                create_bundle(
                    args.build_directory,
                    args.output_directory,
                    load_json(args.corpus.read_text()),
                    include_scenario_data=args.include_scenario_data,
                ),
                indent=2,
            )
        )
    elif args.command == "review-key":
        create_review_key(args.path)
    elif args.command == "review":
        print(json.dumps(record_review(args.directory, args.decision, args.key), indent=2))
    elif args.command == "verify-review":
        print(
            json.dumps(
                verify_for_activation(args.directory, load_json(args.review.read_text()), args.key),
                indent=2,
            )
        )
    else:
        with Engine(args.domain, args.binary) as engine:
            print(json.dumps(inspect_policy(engine), indent=2))


if __name__ == "__main__":
    main()
