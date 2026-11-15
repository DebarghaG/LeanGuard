"""Trusted, offline policy authoring commands. These are never agent tools."""

import argparse
import json
from pathlib import Path

from .engine import Engine
from .inspection import inspect_policy
from .policy_authoring import compile_document, example_document, generate_lean, load_json


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
    else:
        with Engine(args.domain, args.binary) as engine:
            print(json.dumps(inspect_policy(engine), indent=2))


if __name__ == "__main__":
    main()
