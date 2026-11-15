"""A restricted authoring format that emits existing Lean policy constructors."""

import hashlib
import json
import re
import subprocess
from copy import deepcopy
from pathlib import Path

from .engine import Engine, canonical, digest
from .inspection import inspect_policy

FORMAT = "leanguard.policy"
MAX_INTEGER = 2**53 - 1


def load_json(text):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"Duplicate JSON field: {key}")
            result[key] = value
        return result

    def invalid(value):
        raise ValueError(f"Invalid JSON number: {value}")

    return json.loads(text, object_pairs_hook=unique, parse_constant=invalid)


def example_document():
    return {
        "format": FORMAT,
        "version": 1,
        "name": "documents",
        "units": "Integer operation units supplied by the trusted adapter; no automatic conversion.",
        "tools": [
            {"name": "read", "schema": {"type": "object", "properties": {}, "required": []}},
            {
                "name": "write",
                "schema": {
                    "type": "object",
                    "properties": {"value": {"type": "string"}},
                    "required": ["value"],
                },
            },
        ],
        "rules": [
            {
                "id": "documents.tools",
                "effect": "permit",
                "actions": ["read", "write"],
                "condition": {"kind": "always"},
                "source": "Read and write are recognized tools.",
            },
            {
                "id": "documents.approval",
                "effect": "require",
                "actions": ["write"],
                "condition": {"kind": "approval", "seconds": 300},
                "source": "An exact, unrevoked, unused approval is required within five minutes.",
            },
            {
                "id": "documents.read",
                "effect": "require",
                "actions": ["write"],
                "condition": {"kind": "observation", "actions": ["read"]},
                "source": "A successful read of the same resource in this conversation and workflow is required.",
            },
            {
                "id": "documents.quota",
                "effect": "require",
                "actions": ["write"],
                "condition": {
                    "kind": "quota",
                    "calls": 10,
                    "amount": 10000,
                    "window_seconds": 3600,
                },
                "source": "Writes must fit the principal's hourly dispatch count and amount budget.",
            },
            {
                "id": "documents.single",
                "effect": "require",
                "actions": ["read", "write"],
                "condition": {"kind": "single_flight"},
                "source": "Wait until earlier dispatches in this conversation or resource are resolved.",
            },
        ],
    }


def _object(value, required, optional=()):
    if not isinstance(value, dict) or not set(required) <= value.keys():
        raise ValueError(f"Expected object with fields: {', '.join(required)}")
    if any(not isinstance(key, str) for key in value):
        raise ValueError("Object keys must be strings")
    unknown = value.keys() - set(required) - set(optional)
    if unknown:
        raise ValueError(f"Unknown fields: {', '.join(sorted(unknown))}")


def _text(value, label):
    if not isinstance(value, str) or not value or len(value) > 10000:
        raise ValueError(f"{label} must be nonempty text of at most 10000 characters")
    if any(ord(c) < 32 and c not in "\n\r\t" or 0xD800 <= ord(c) <= 0xDFFF for c in value):
        raise ValueError(f"{label} contains unsupported control characters")
    return value


def _identifier(value, label):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]{0,127}", value):
        raise ValueError(
            f"{label} must be a stable identifier (letters, digits, dot, dash, underscore)"
        )
    return value


def _natural(value):
    if type(value) is not int or not 0 <= value <= MAX_INTEGER:
        raise ValueError("Expected a nonnegative integer no larger than 2^53-1")
    return str(value)


def _strings(value):
    if (
        not isinstance(value, list)
        or not value
        or any(not isinstance(s, str) or not s for s in value)
    ):
        raise ValueError("Expected a nonempty list of names")
    if len(set(value)) != len(value):
        raise ValueError("Repeated names are not allowed")
    return "[" + ", ".join(_quote(_text(s, "Name")) for s in value) + "]"


def _quote(value):
    # Lean and JSON share these string escapes. Non-ASCII is emitted literally.
    return json.dumps(value, ensure_ascii=False)


def _schema(value, depth=0):
    if depth > 32:
        raise ValueError("Schema exceeds 32 levels")
    if not isinstance(value, dict):
        raise TypeError("Expected a schema object")
    kind = value.get("type")
    if kind is not None and not isinstance(kind, str):
        raise ValueError("Schema type must be a string")
    if kind in {"string", "integer", "number", "boolean", "null"}:
        _object(value, ["type"])
        return "." + kind
    if kind == "object":
        _object(value, ["type", "properties", "required"])
        properties, required = value["properties"], value["required"]
        if not isinstance(properties, dict) or not isinstance(required, list):
            raise ValueError("Object schemas need properties and an explicit required list")
        if any(not isinstance(key, str) or not key for key in required) or len(
            set(required)
        ) != len(required):
            raise ValueError("Invalid required property names")
        if not set(required) <= properties.keys():
            raise ValueError("Required properties must have schemas")
        fields = [
            f"({_quote(_text(key, 'Property'))}, {_schema(item, depth + 1)})"
            for key, item in sorted(properties.items())
        ]
        names = "[" + ", ".join(_quote(key) for key in sorted(required)) + "]"
        return f"(.object {names} [{', '.join(fields)}])"
    if kind == "array":
        _object(value, ["type", "items"])
        return f"(.array {_schema(value['items'], depth + 1)})"
    if "enum" in value:
        _object(value, ["enum"])
        values = value["enum"]
        _strings(values)
        return "(.enum [" + ", ".join("Lean.toJson " + _quote(item) for item in values) + "])"
    raise ValueError("Unsupported schema; use primitives, object, array, or a string enum")


def _condition(value, tools, depth=0):
    if depth > 32:
        raise ValueError("Condition exceeds 32 levels")
    if not isinstance(value, dict):
        raise TypeError("Expected a condition object")
    kind = value.get("kind")
    if not isinstance(kind, str):
        raise TypeError("Condition kind must be a string")
    if kind in {"always", "never", "single_flight"}:
        _object(value, ["kind"])
        return {"always": ".top", "never": ".bot", "single_flight": "singleFlight"}[kind]
    if kind == "approval":
        _object(value, ["kind", "seconds"])
        return (
            "confirmed"
            if value["seconds"] is None
            else f"(confirmedWithin {_natural(value['seconds'])})"
        )
    if kind in {"observation", "never_dispatched"}:
        _object(value, ["kind", "actions"])
        actions = _strings(value["actions"])
        if not set(value["actions"]) <= tools:
            raise ValueError("Condition actions must name declared tools")
        return f"({'observed' if kind == 'observation' else 'neverDispatched'} {actions})"
    if kind == "quota":
        _object(value, ["kind", "calls", "amount", "window_seconds"])
        return (
            "(quota "
            + " ".join(_natural(value[k]) for k in ["calls", "amount", "window_seconds"])
            + ")"
        )
    if kind in {"all", "any"}:
        _object(value, ["kind", "left", "right"])
        return f"(.{'conj' if kind == 'all' else 'disj'} {_condition(value['left'], tools, depth + 1)} {_condition(value['right'], tools, depth + 1)})"
    if kind == "not":
        _object(value, ["kind", "child"])
        return f"(.neg {_condition(value['child'], tools, depth + 1)})"
    # Arbitrary Lean and opaque inspection nodes are intentionally not editable input.
    raise ValueError(f"Unsupported condition kind: {kind}")


def generate_lean(document):
    _object(document, ["format", "version", "name", "units", "tools", "rules"])
    if (
        document["format"] != FORMAT
        or type(document["version"]) is not int
        or document["version"] != 1
    ):
        raise ValueError("Unsupported authoring format/version")
    _identifier(document["name"], "Pack name")
    _text(document["units"], "Adapter unit description")
    tools, rules = document["tools"], document["rules"]
    if not isinstance(tools, list) or not tools or len(tools) > 100:
        raise ValueError("Declare between 1 and 100 tools")
    schemas = []
    names = []
    for tool in tools:
        _object(tool, ["name", "schema"])
        names.append(_identifier(tool["name"], "Tool name"))
        if not isinstance(tool["schema"], dict) or tool["schema"].get("type") != "object":
            raise ValueError("Tool input schemas must be objects")
        schemas.append(f"({_quote(tool['name'])}, {_schema(tool['schema'])})")
    if len(set(names)) != len(names):
        raise ValueError("Duplicate tool name")
    if not isinstance(rules, list) or not rules or len(rules) > 500:
        raise ValueError("Declare between 1 and 500 rules")
    compiled, ids = [], set()
    for rule in rules:
        _object(rule, ["id", "effect", "actions", "condition", "source"])
        identifier = _identifier(rule["id"], "Rule ID")
        if identifier in ids or identifier.startswith("schema."):
            raise ValueError("Duplicate or reserved rule ID")
        ids.add(identifier)
        if not isinstance(rule["effect"], str) or rule["effect"] not in {
            "permit",
            "require",
            "forbid",
        }:
            raise ValueError("Unsupported rule effect")
        actions = _strings(rule["actions"])
        if not set(rule["actions"]) <= set(names):
            raise ValueError("Rule actions need declared tool schemas")
        source = _quote(_text(rule["source"], "Source clause"))
        condition = _condition(rule["condition"], set(names))
        compiled.append(f"    {rule['effect']} {_quote(identifier)} {actions} {condition} {source}")
    return "\n".join(
        [
            "import LeanGuard.Schema",
            "",
            "namespace WorkbenchPolicy",
            "open LeanGuard",
            "",
            "def pack : PolicyPack := withSchemas {",
            f"  name := {_quote(document['name'])}",
            "  rules := [",
            ",\n".join(compiled),
            "  ]",
            "} [" + ", ".join(schemas) + "]",
            "",
            "end WorkbenchPolicy",
            "",
        ]
    )


def validate_document(document):
    generate_lean(document)
    return deepcopy(document)


def source_provenance(project):
    project = Path(project).resolve()
    paths = [
        *project.glob("LeanGuard/**/*.lean"),
        *project.glob("*.lean"),
        project / "lakefile.toml",
        project / "lake-manifest.json",
        project / "lean-toolchain",
    ]
    files = {
        str(path.relative_to(project)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(set(paths))
        if path.is_file()
    }
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=project, check=True, capture_output=True, text=True
    ).stdout.strip()
    dependencies = {}
    for path in sorted((project / ".lake/packages").glob("*")):
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=path, capture_output=True, text=True, check=False
        )
        if result.returncode == 0:
            sources = [*path.rglob("*.lean"), *path.glob("lakefile.*"), path / "lean-toolchain"]
            hashes = {
                str(p.relative_to(path)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in sorted(set(sources))
                if p.is_file() and ".lake" not in p.relative_to(path).parts
            }
            dependencies[path.name] = {
                "revision": result.stdout.strip(),
                "source_tree_sha256": digest(hashes),
            }
    return {"revision": revision, "files": files, "dependencies": dependencies}


def compile_document(document, directory, project):
    document = validate_document(document)
    directory, project = Path(directory).resolve(), Path(project).resolve()
    if directory.exists() and any(directory.iterdir()):
        raise ValueError("Build directory must be new or empty")
    provenance = source_provenance(project)
    directory.mkdir(parents=True, exist_ok=True)
    sources = {
        "policy.json": canonical(document) + "\n",
        "Policy.lean": generate_lean(document),
        "Main.lean": "import Policy\nimport LeanGuard.Server\ndef main : IO Unit := LeanGuard.serve WorkbenchPolicy.pack\n",
        "Audit.lean": "import Main\nimport LeanGuard.Audit\nrun_cmd LeanGuard.Audit.check #[``WorkbenchPolicy.pack, ``main] #[`WorkbenchPolicy, `LeanGuard]\n",
        "lean-toolchain": (project / "lean-toolchain").read_text(),
        "lakefile.toml": "\n".join(
            [
                'name = "WorkbenchPolicy"',
                'defaultTargets = ["Policy", "Audit", "policy-engine"]',
                "[[require]]",
                'name = "LeanGuard"',
                "path = " + _quote(str(project)),
                "[[lean_lib]]",
                'name = "Policy"',
                'roots = ["Policy", "Main"]',
                "[[lean_lib]]",
                'name = "Audit"',
                "[[lean_exe]]",
                'name = "policy-engine"',
                'root = "Main"',
                "",
            ]
        ),
    }
    for name, contents in sources.items():
        (directory / name).write_text(contents)
    # Dependencies may share source caches, but generated build outputs stay isolated.
    (directory / ".lake").mkdir()
    (directory / ".lake/packages").symlink_to(project / ".lake/packages", target_is_directory=True)
    log = directory / "build.log"
    with log.open("w") as output:
        result = subprocess.run(
            ["lake", "build"],
            cwd=directory,
            stdout=output,
            stderr=subprocess.STDOUT,
            timeout=600,
            check=False,
        )
    if result.returncode:
        raise ValueError(f"Native build or axiom audit failed; inspect {log}")
    if provenance != source_provenance(project):
        raise ValueError("Dependency sources changed during build; rebuild in a new directory")
    binary = directory / ".lake/build/bin/policy-engine"
    with Engine(document["name"], binary) as engine:
        inspection = inspect_policy(engine)
    (directory / "inspection.json").write_text(canonical(inspection) + "\n")
    recorded_files = [*sources, "inspection.json", "lake-manifest.json", "build.log"]
    build = {
        "format": "leanguard.build",
        "version": 1,
        "document_sha256": digest(document),
        "engine_sha256": inspection["engine_sha256"],
        "provenance": provenance,
        "files": {
            name: hashlib.sha256((directory / name).read_bytes()).hexdigest()
            for name in recorded_files
        },
    }
    (directory / "build.json").write_text(canonical(build) + "\n")
    return {
        "directory": str(directory),
        "binary": str(binary),
        "inspection": inspection,
        "build": build,
    }
