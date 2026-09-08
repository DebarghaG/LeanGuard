"""Compare native LeanGuard encodings with the pinned Dogwood guide corpus.

Run from any directory. Upstream files remain in their Apache-2.0 checkout;
this example does not vendor or relicense them. No model or backend calls.
"""

import argparse
import hashlib
import json
import re
import subprocess
import tempfile
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from leanguard import Engine, replay

REVISION = "c6237c88099b3f492ecc5fcee42df06a19224b97"
HERE = Path(__file__).resolve().parent
ENTITY = re.compile(r'(?P<type>[A-Za-z_]\w*(?:::[A-Za-z_]\w*)*)::(?P<id>"(?:[^"\\]|\\.)*")\Z')
CLOCK_EXAMPLES = {"sell_after_2024_datetime", "sell_datetime_window"}
PROVIDERS = {
    "provider_allowed_or_short",
    "provider_digitcount_forbid",
    "provider_digitcount_operator_ge",
    "provider_filter_set_index_decimal",
    "provider_int_arithmetic_trusted",
    "provider_matches_and_not_blocked",
    "provider_principal_id_allowlist",
    "provider_regex_analyze_fields",
    "provider_regex_matches_uppercase",
    "provider_risk_decimal_method",
    "sell_after_approval_valid_ticker",
}
ADAPTERS = {
    "approve_has_output_guard",
    "cond_is_oauth_in_team",
    "login_attempt_custom_kind",
    "principal_is_oauth",
    "sell_after_2024_datetime",
    "sell_datetime_window",
    "sell_nonzero_proceeds_decimal",
    "sell_small_proceeds_decimal_method",
    "sell_zero_proceeds_if_has",
    "traders_is_in_group_scope",
}
ALWAYS_DENY = {
    "alert_heartbeat_and_login_rate": "Current-only Login count cannot exceed two.",
    "alert_login_current_tp": "Current Alert timepoint cannot also be a Login.",
    "alert_total_transfer_over_200": "Current-only sum sees no Transfer at an Alert.",
    "read_heartbeat_since_login_30s": "Current Read does not satisfy the left Heartbeat operand.",
    "read_since_login": "Current Read does not satisfy the left Login operand.",
    "forbid_large_except_amzn": "Forbid-only policy has no permit; default denial always wins.",
    "forbid_read_transfers_over_1000": "Forbid-only policy has no permit; default denial always wins.",
}


def split_top(source, delimiter=","):
    """Split outside strings/records; reject unsupported or unbalanced input."""
    pieces, stack, start, quoted, escaped = [], [], 0, False, False
    pairs = {")": "(", "}": "{", "]": "["}
    for i, char in enumerate(source):
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
        elif char in "({[":
            stack.append(char)
        elif char in ")}]":
            if not stack or stack.pop() != pairs[char]:
                raise ValueError("unbalanced source record")
        elif char == delimiter and not stack:
            pieces.append(source[start:i].strip())
            start = i + 1
    if quoted or stack:
        raise ValueError("unterminated source record")
    pieces.append(source[start:].strip())
    return [p for p in pieces if p]


def parse_value(source):
    source = source.strip()
    if source.startswith("{") and source.endswith("}"):
        return parse_fields(source[1:-1])
    if source.startswith("[") and source.endswith("]"):
        return [parse_value(p) for p in split_top(source[1:-1])]
    if ENTITY.fullmatch(source):
        return {"entity": source}
    if re.fullmatch(r"-?\d+\.\d+", source):
        scaled = Decimal(source) * 10000
        if scaled != int(scaled) or not -(2**63) <= scaled < 2**63:
            raise ValueError("decimal outside Cedar's four-place signed range")
        return {"decimal4": int(scaled)}
    if source.startswith('"') or source in ("true", "false") or re.fullmatch(r"-?\d+", source):
        return json.loads(source)
    raise ValueError(f"unsupported guide value: {source!r}")


def parse_fields(source):
    result = {}
    for item in split_top(source):
        key, value = item.split(":", 1)
        key = key.strip().strip('"')
        if key in result:
            raise ValueError(f"duplicate field: {key}")
        result[key] = parse_value(value)
    return result


def envelope(source, name):
    prefix = name + "("
    if not source.startswith(prefix):
        return None, source
    # A top-level comma immediately after the envelope lets the shared scanner
    # find its end, including quoted parentheses and nested request records.
    quoted = escaped = False
    depth = 0
    for i, char in enumerate(source):
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return source[len(prefix) : i], source[i + 1 :].strip()
    raise ValueError(f"unclosed {name} envelope")


@dataclass
class SourceEvent:
    time: int
    action: str
    kind: str
    principal: str
    resource: str
    context: dict
    logged: dict
    entities: dict = field(default_factory=dict)


def parse_trace(source):
    result = []
    for line in source.splitlines():
        if not line.strip():
            continue
        timestamp, rest = line.strip().split(maxsplit=1)
        if not re.fullmatch(r"@\d+", timestamp):
            raise ValueError("guide replay requires nonnegative integer seconds")
        scope, rest = envelope(rest, "scope")
        if scope is None:
            raise ValueError("guide replay requires explicit scope")
        scope = parse_fields(scope)
        entities, rest = envelope(rest, "entities")
        if entities is not None:
            raise ValueError("source entities envelopes require an explicit adapter")
        context, rest = envelope(rest, "request_context")
        match = re.fullmatch(r'Drupe::Action::"(\w+)"::(\w+)\((.*)\)', rest)
        if not match:
            raise ValueError(f"unsupported event: {rest}")
        action, kind, fields = match.groups()
        result.append(
            SourceEvent(
                int(timestamp[1:]),
                action,
                kind,
                scope["principal"]["entity"],
                scope["resource"]["entity"],
                {} if context is None else parse_fields(context),
                parse_fields(fields),
            )
        )
    return result


def render_value(value):
    if isinstance(value, dict):
        if set(value) == {"entity"}:
            return value["entity"]
        if set(value) == {"decimal4"}:
            return f"{Decimal(value['decimal4']) / 10000:.4f}"
        return "{ " + render_fields(value) + " }"
    if isinstance(value, list):
        return "[" + ", ".join(map(render_value, value)) + "]"
    return json.dumps(value, ensure_ascii=False)


def render_fields(fields):
    return ", ".join(f"{k}: {render_value(v)}" for k, v in fields.items())


def render_trace(events):
    lines = []
    for e in events:
        entities = ""
        if e.entities:
            records = []
            for uid, parents in e.entities.items():
                match = ENTITY.fullmatch(uid)
                attrs = (
                    {"id": json.loads(match["id"])} if match["type"] == "Drupe::OAuthUser" else {}
                )
                records.append(f"{uid}: {render_value(attrs)} in [{', '.join(parents)}]")
            entities = " entities(" + ", ".join(records) + ")"
        lines.append(
            f"@{e.time} scope(principal: {e.principal}, resource: {e.resource})"
            f'{entities} request_context({render_fields(e.context)}) Drupe::Action::"{e.action}"'
            f"::{e.kind}({render_fields(e.logged)})"
        )
    return "\n".join(lines) + "\n"


def provider_values(name, event):
    """Fixture adapters for the declared providers, NOT verified Rhai execution.

    Pass typed provider RESULTS across the boundary, never a final verdict.
    The upstream run evaluates the original Rhai implementation independently.
    """
    if name not in PROVIDERS:
        return {}
    inputs = event.context.get("input", {})
    text = inputs.get("stock" if name == "sell_after_approval_valid_ticker" else "document")
    principal_id = json.loads(ENTITY.fullmatch(event.principal)["id"])
    if text is not None and not isinstance(text, str):
        raise ValueError("provider argument must be a string")
    pattern = "[a-z]+" if name == "provider_matches_and_not_blocked" else "[A-Z]+"
    first = re.search("[0-9]+", text or "")
    return {
        "allowed": text in ("readme", "manifest"),
        "length": -1 if text is None else len(text),
        "digits": -1 if text is None else len(re.findall("[0-9]", text)),
        # Rust regex `$` requires the actual end; Python `$` also accepts the
        # position before a final newline. fullmatch preserves the source rule.
        "matched": text is not None and re.fullmatch(pattern, text) is not None,
        "blocked": text in ("evil", "badword"),
        "principal_allowed": principal_id == "alice",
        "starts_upper": re.search("^[A-Z]", text or "") is not None,
        "first_digits": first[0] if first else "",
        "violence_decimal4": -10000 if text is None else 9000 if text == "violent" else 1000,
        "risk_decimal4": -10000 if text is None else {"safe": 1000, "spam": 8000}.get(text, 5000),
    }


def normalize(name, events):
    for i, e in enumerate(events):
        # Custom schema explicitly declares attempt as decision; this is not
        # permission to map arbitrary observations to attempts or confirmations.
        kinds = {"request": "request", "response": "success"}
        if name == "login_attempt_custom_kind":
            kinds = {"attempt": "request", "outcome": "success"}
        if e.kind not in kinds:
            raise ValueError(f"unsupported source kind {e.kind}")
        principal = ENTITY.fullmatch(e.principal)
        if principal is None or ENTITY.fullmatch(e.resource) is None:
            raise ValueError("scope must contain typed entities")
        actor = "actor" if name == "login_attempt_custom_kind" else "callerPrincipal"
        if e.logged.get(actor) != {"entity": e.principal}:
            raise ValueError("logged principal must agree with authoritative scope")
        if actor != "actor" and e.logged.get("callerResource") != {"entity": e.resource}:
            raise ValueError("logged resource must agree with authoritative scope")
        ancestors, todo = set(), list(e.entities.get(e.principal, []))
        while todo:
            parent = todo.pop()
            if parent not in ancestors:
                ancestors.add(parent)
                todo.extend(e.entities.get(parent, []))
        context = json.loads(json.dumps(e.context))
        now = context.get("system", {}).get("now")
        if now is not None:
            instant = datetime.fromisoformat(now)
            if instant.tzinfo is None:
                raise ValueError("clock must specify a timezone")
            epoch = datetime.fromisoformat("1970-01-01T00:00:00+00:00")
            delta = instant - epoch
            context["system"]["now"] = {
                "datetime_ms": delta.days * 86400000
                + delta.seconds * 1000
                + delta.microseconds // 1000
            }
        yield {
            "id": f"guide-{i}",
            "time": e.time,
            "kind": kinds[e.kind],
            "principal": e.principal,
            "session": "guide",
            "action": e.action,
            "resource": e.resource,
            "binding": "",
            "amount": 0,
            "input": e.context.get("input", {})
            if kinds[e.kind] == "request"
            else e.logged.get("input", {}),
            "output": e.logged.get("output"),
            "facts": {
                "logged": e.logged,
                "context": context,
                "principal_type": principal["type"],
                "principal_ancestors": sorted(ancestors),
                "providers": provider_values(name, e),
            },
        }


def source_command(binary, bundle, operation, trace=None):
    command = [
        str(binary),
        operation,
        str(bundle / "policy.dw"),
        "--policy-schema",
        str(bundle / "schema.cedarschema"),
        "--format",
        "json",
    ]
    for flag, filenames in {
        "--event-schema": ("events.dwschema", "event.dwschema"),
        "--providers": ("providers.json",),
        "--macros": ("macros.dw",),
    }.items():
        for filename in filenames:
            if (bundle / filename).exists():
                command.extend([flag, str(bundle / filename)])
                break
    if trace is not None:
        command.extend(["--trace", str(trace)])
    result = subprocess.run(command, text=True, capture_output=True, timeout=120, check=False)
    if result.returncode:
        raise RuntimeError(f"{bundle.name}: {operation}: {result.stdout}\n{result.stderr}")
    return json.loads(result.stdout)


def compare(binary, bundle, trace, events, labels, engine):
    reference = source_command(binary, bundle, "replay", trace)["verdicts"]
    native = list(replay(engine, normalize(bundle.name, events)))
    decisions = [e for e in events if e.kind in ("request", "attempt")]
    if not len(reference) == len(native) == len(decisions) == len(labels):
        raise AssertionError(f"{bundle.name}: decision count mismatch")
    failures = []
    for index, (ref, actual, event, label) in enumerate(zip(reference, native, decisions, labels)):
        # Forbid-only examples always deny. Check whether the forbid actually
        # fires too, so default denial cannot mask a broken sum or threshold.
        wrong_forbid = bundle.name in {
            "forbid_large_except_amzn",
            "forbid_read_transfers_over_1000",
        } and bool(ref["determining_rules"]) != actual["rules"].get(bundle.name, False)
        if (
            (ref["verdict"] == "allow") != actual["decision"]["allow"]
            or ref["errors"]
            or actual["decision"]["errors"]
            or wrong_forbid
        ):
            failures.append(
                {
                    "index": index,
                    "label": label,
                    "time": event.time,
                    "action": event.action,
                    "input": event.context.get("input"),
                    "dogwood": ref,
                    "leanguard": actual,
                }
            )
    return (
        {
            "decisions": len(native),
            "allowed": sum(r["decision"]["allow"] for r in native),
            "mismatches_or_errors": failures,
        },
        reference,
        native,
    )


def clock_oracle(name, events, reference, native):
    """Record the upstream limitation; check the intended clock predicate separately."""
    failures = []
    for index, (e, actual, ref) in enumerate(zip(events, native, reference)):
        if ref["verdict"] != "deny" or not any(
            "expected datetime, got string" in error for error in ref["errors"]
        ):
            raise AssertionError("upstream datetime behavior changed; revisit this limitation")
        now = datetime.fromisoformat(e.context["system"]["now"])
        expected = (
            now > datetime.fromisoformat("2024-01-01T00:00:00Z")
            if name == "sell_after_2024_datetime"
            else datetime.fromisoformat("2025-01-01T00:00:00Z")
            <= now
            < datetime.fromisoformat("2026-01-01T00:00:00Z")
        )
        if actual["decision"]["allow"] != expected or actual["decision"]["errors"]:
            failures.append({"index": index, "expected": expected, "leanguard": actual})
    return {
        "oracle": "independent UTC datetime comparison; NOT Dogwood replay agreement",
        "decisions": len(native),
        "allowed": sum(r["decision"]["allow"] for r in native),
        "mismatches_or_errors": failures,
    }


def main():
    from cases import generated

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True, help="pinned Dogwood git checkout")
    parser.add_argument("--dogwood", type=Path, required=True, help="upstream dogwood CLI")
    parser.add_argument("--binary", type=Path, default=HERE / ".lake/build/bin/dogwood-guide")
    parser.add_argument("--output", type=Path, default=HERE / "results.json")
    args = parser.parse_args()
    source = args.source.resolve()
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=source, text=True).strip()
    if revision != REVISION or subprocess.check_output(
        ["git", "status", "--porcelain", "--", ".", ":(exclude)Cargo.lock", ":(exclude)target"],
        cwd=source,
    ):
        raise RuntimeError(f"expected clean upstream revision {REVISION}")
    bundles = sorted((source / "dogwood-docs/examples").glob("*/policy.dw"))
    if len(bundles) != 86:
        raise RuntimeError("guide inventory changed")
    report = {
        "source_revision": revision,
        "engine_sha256": hashlib.sha256(args.binary.read_bytes()).hexdigest(),
        "dogwood_sha256": hashlib.sha256(args.dogwood.read_bytes()).hexdigest(),
        "examples": [],
    }
    with tempfile.TemporaryDirectory(prefix="leanguard-dogwood-") as temp:
        for policy in bundles:
            bundle = policy.parent
            source_command(args.dogwood, bundle, "validate")
            item = {
                "name": bundle.name,
                "category": "provider_adapter"
                if bundle.name in PROVIDERS
                else "data_adapter"
                if bundle.name in ADAPTERS
                else "native",
                "source_sha256": {
                    p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                    for p in sorted(bundle.iterdir())
                    if p.is_file()
                },
            }
            if bundle.name in ALWAYS_DENY:
                item["always_denies"] = ALWAYS_DENY[bundle.name]
            with Engine(bundle.name, binary=args.binary) as engine:
                if (bundle / "trace.log").exists():
                    events = parse_trace((bundle / "trace.log").read_text())
                    labels = ["published"] * sum(e.kind in ("request", "attempt") for e in events)
                    item["published"], reference, _ = compare(
                        args.dogwood, bundle, bundle / "trace.log", events, labels, engine
                    )
                    expected = re.findall(r": (ALLOW|DENY)", (bundle / "expected.out").read_text())
                    if [r["verdict"].upper() for r in reference] != expected:
                        raise AssertionError(f"upstream expected.out disagrees: {bundle.name}")
                events, labels = generated(bundle)
                trace = Path(temp) / "generated.log"
                trace.write_text(render_trace(events))
                item["generated"], reference, native = compare(
                    args.dogwood, bundle, trace, events, labels, engine
                )
                item["generated_sha256"] = hashlib.sha256(trace.read_bytes()).hexdigest()
                if bundle.name in CLOCK_EXAMPLES:
                    item["reference_limitation"] = {
                        "reason": "Dogwood Value/log parser has no datetime value variant",
                        "replay_errors": [r["errors"] for r in reference],
                    }
                    item["generated"] = clock_oracle(bundle.name, events, reference, native)
            report["examples"].append(item)
            args.output.write_text(json.dumps(report, indent=2) + "\n")
            print(
                bundle.name,
                sum(item[k]["decisions"] for k in ("published", "generated") if k in item),
                "FAIL"
                if any(
                    item[k]["mismatches_or_errors"] for k in ("published", "generated") if k in item
                )
                else "PASS",
                flush=True,
            )
    report["summary"] = {
        "examples": len(report["examples"]),
        "categories": dict(Counter(e["category"] for e in report["examples"])),
        "differential_examples": len(report["examples"]) - len(CLOCK_EXAMPLES),
        "clock_oracle_only_examples": len(CLOCK_EXAMPLES),
    }
    for kind in ("published", "generated"):
        rows = [e[kind] for e in report["examples"] if kind in e]
        report["summary"][kind] = {
            "examples": len(rows),
            "decisions": sum(r["decisions"] for r in rows),
            "allowed": sum(r["allowed"] for r in rows),
            "mismatches_or_errors": sum(len(r["mismatches_or_errors"]) for r in rows),
        }
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report["summary"], indent=2))
    if any(report["summary"][k]["mismatches_or_errors"] for k in ("published", "generated")):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
