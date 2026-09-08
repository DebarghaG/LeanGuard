"""Offline native-policy injection into published, fixed tool trajectories.

No environment tool, embedded expression, reward verifier, or model is executed.
Only earlier recorded observations become facts. A blocked call's recorded outcome
still advances the shadow history: later verdicts are conditional on the original
trajectory, not a counterfactual continuation after enforcement.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
import time
from collections import Counter
from contextlib import ExitStack
from copy import deepcopy
from pathlib import Path

from jsonschema import Draft202012Validator
from leanguard.engine import Engine, canonical, digest
from leanguard.tau import TauAdapter, epoch, normalize

from .trajectory_data import download_datasets, normalize_datasets

CONFIRMATION = {"retail.confirmation", "airline.confirmation", "telecom.refuel_confirm"}
LOOKUPS = {
    "find_user_id_by_email",
    "find_user_id_by_name_zip",
    "get_customer_by_id",
    "get_customer_by_phone",
    "get_customer_by_name",
}


def translated(domain, name, arguments, dataset):
    """Narrow, explicit aliases for fuvty's documented unified commerce interface."""
    args = deepcopy(arguments)
    if dataset != "fuvty--tau-bench-synthetic" or not isinstance(args, dict):
        return name, args
    if domain == "retail":
        if name == "find_user_by_contact" and set(args) == {"email"}:
            name = "find_user_id_by_email"
        elif name == "find_user_by_name" and set(args) == {"first_name", "last_name", "zip"}:
            name = "find_user_id_by_name_zip"
        elif name == "cancel_order" and set(args) <= {"order_id", "reason"}:
            name = "cancel_pending_order"
    elif domain == "airline" and name in {"get_order_details", "cancel_order"}:
        permitted = {"order_id"} | ({"reason"} if name == "cancel_order" else set())
        if "order_id" in args and set(args) <= permitted:
            name = (
                "get_reservation_details" if name == "get_order_details" else "cancel_reservation"
            )
            args = {"reservation_id": args["order_id"]}
    return name, args


def payload(message):
    value = message["content"]
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            return value
    return value


def failed(message, value):
    return (
        bool(message.get("error"))
        or (isinstance(value, dict) and bool(value.get("error")))
        or (
            isinstance(value, str)
            and bool(
                re.match(
                    r"\s*(?:error\b|\w*(?:Error|Exception):|traceback\b)", value, re.IGNORECASE
                )
            )
        )
    )


def paired_responses(calls, responses):
    """Match IDs first; absent IDs use τ²'s serial, same-batch output ordering.

    Only a complete batch permits positional matching. A conflicting ID never
    falls back to position. Missing/ambiguous results remain unresolved.
    """
    result = [(None, "missing_or_ambiguous")] * len(calls)
    used = set()
    for index, call in enumerate(calls):
        matches = [
            j
            for j, r in enumerate(responses)
            if j not in used and call.get("id") and r.get("response_id") == call["id"]
        ]
        if len(matches) == 1:
            j = matches[0]
            result[index] = (responses[j], "call_id")
            used.add(j)
    if len(calls) == len(responses):
        for index, call in enumerate(calls):
            if result[index][0] is None and index not in used:
                response = responses[index]
                if not response.get("response_id") and (
                    not response.get("name") or response["name"] == call["name"]
                ):
                    result[index] = (response, "position_same_batch")
                    used.add(index)
    return result, len(responses) - len(used)


class Observations:
    """Partial state from tool outputs; absent facts stay absent (including collections)."""

    def __init__(self, domain):
        self.domain = domain
        self.objects = {
            k: {}
            for k in (
                "users",
                "orders",
                "products",
                "reservations",
                "flights",
                "lines",
                "bills",
                "plans",
                "devices",
            )
        }
        self.customer = ""
        self.user_text = []
        self.reason = ""
        self.lookup_results = {}
        self.clock = epoch("2025-02-25T12:08:00" if domain == "telecom" else "2024-05-15T15:00:00")

    def user_message(self, content):
        if isinstance(content, str) and content:
            # Reuse the exact live runner's evidence extraction, including its limits.
            from .rollout import customer_reason

            self.reason = customer_reason(content, self.reason)
            self.user_text.append(content)
            if self.domain == "airline" and not self.customer:
                candidates = set(
                    re.findall(
                        r"\b[A-Za-z]+(?:_[A-Za-z]+)+_(?=[A-Za-z0-9]*\d)[A-Za-z0-9]+\b", content
                    )
                )
                candidates = {
                    c for c in candidates if not c.startswith(("credit_card_", "gift_card_"))
                }
                if len(candidates) == 1:
                    self.customer = candidates.pop()

    def supplied(self, customer):
        return (
            isinstance(customer, str)
            and bool(customer)
            and not customer.startswith(("credit_card_", "gift_card_"))
            and any(
                re.search(r"(?<![\w])" + re.escape(customer) + r"(?![\w])", s)
                for s in self.user_text
            )
        )

    def facts(self, action, args):
        if not isinstance(args, dict):
            return {}, "public", False
        identity = self.domain == "airline" and self.supplied(self.customer)
        if self.domain == "airline" and self.supplied(args.get("user_id")):
            if not self.customer:
                self.customer = args["user_id"]
            identity = self.customer == args["user_id"]
        o = self.objects
        # A reservation can name the candidate, but only literal user text proves supply.
        reservation = o["reservations"].get(args.get("reservation_id"), {})
        candidate = reservation.get("user_id")
        if self.domain == "airline" and not self.customer and self.supplied(candidate):
            self.customer, identity = candidate, True
        facts = {"customer_id": self.customer, "user": deepcopy(o["users"].get(self.customer, {}))}
        resource = (
            args.get("order_id")
            or args.get("reservation_id")
            or args.get("line_id")
            or args.get("bill_id")
            or args.get("id")
            or args.get("user_id")
            or args.get("customer_id")
            or self.customer
            or "public"
        )
        if action in LOOKUPS:
            candidate = self.lookup_results.get(digest([action, args]))
            if candidate is not None:
                facts["lookup_customer_id"] = candidate
                resource = candidate or resource
            elif not self.customer:
                # Stable-identity check is vacuous before the first lookup.
                facts["lookup_customer_id"] = ""
        if self.domain == "retail" and "order_id" in args:
            if resource in o["orders"]:
                facts["order"] = deepcopy(o["orders"][resource])
            facts["products"] = deepcopy(o["products"])
        if self.domain == "airline":
            if reservation:
                facts["reservation"] = deepcopy(reservation)
            facts["flights"] = deepcopy(o["flights"])
            facts["cancellation_reason"] = self.reason
        if self.domain == "telecom":
            user = facts["user"]
            for collection, ids, output in [
                ("bills", "bill_ids", "bills"),
                ("lines", "line_ids", "customer_lines"),
            ]:
                if ids in user and all(i in o[collection] for i in user[ids]):
                    facts[output] = [deepcopy(o[collection][i]) for i in user[ids]]
            for collection, kind in [
                ("users", "customer"),
                ("lines", "line"),
                ("bills", "bill"),
                ("plans", "plan"),
                ("devices", "device"),
            ]:
                if resource in o[collection]:
                    facts["detail_type"] = kind
            # Typed references in an observed customer/line also identify detail types.
            if resource in user.get("line_ids", []):
                facts["detail_type"] = "line"
            if resource in user.get("bill_ids", []):
                facts["detail_type"] = "bill"
            if any(line.get("plan_id") == resource for line in o["lines"].values()):
                facts["detail_type"] = "plan"
            for kind in ["line", "bill"]:
                if resource in o[kind + "s"]:
                    facts[kind] = deepcopy(o[kind + "s"][resource])
            plan_id = facts.get("line", {}).get("plan_id")
            if plan_id in o["plans"]:
                facts["plan"] = deepcopy(o["plans"][plan_id])
        return facts, resource, identity

    def invalidate(self, action, args, mutating, supported):
        o = self.objects
        if not supported:
            # Arbitrary code/unknown tools may mutate any object. Do not trust stale state.
            for collection in o.values():
                collection.clear()
            self.lookup_results.clear()
        elif mutating:
            for collection, key in [
                ("orders", "order_id"),
                ("reservations", "reservation_id"),
                ("lines", "line_id"),
                ("bills", "bill_id"),
            ]:
                o[collection].pop(args.get(key), None)
            for user in o["users"].values():
                user.pop("payment_methods", None)
                if self.domain == "telecom":
                    user.pop("bill_ids", None)
            for flight in o["flights"].values():
                for instance in flight.get("dates", {}).values():
                    instance.pop("available_seats", None)
                    instance.pop("prices", None)

    def ingest(self, action, args, value):
        """Only typed outputs of recognized tools enter the cache; code stdout never does."""
        o = self.objects
        if action in LOOKUPS:
            customer = value.get("customer_id") if isinstance(value, dict) else value
            if isinstance(customer, str) and re.fullmatch(r"[\w-]+", customer):
                self.lookup_results[digest([action, args])] = customer
                if not self.customer:
                    self.customer = customer
        if action == "get_flight_status" and isinstance(value, str):
            if value in {"available", "cancelled", "delayed", "flying", "landed"}:
                flight = o["flights"].setdefault(args["flight_number"], {"dates": {}})
                flight["dates"].setdefault(args["date"], {})["status"] = value
            return
        if action in {"search_direct_flight", "search_onestop_flight"}:

            def flights(v):
                if isinstance(v, list):
                    for item in v:
                        flights(item)
                elif isinstance(v, dict) and "flight_number" in v:
                    flight = o["flights"].setdefault(v["flight_number"], {"dates": {}})
                    flight.update({k: v[k] for k in ("origin", "destination") if k in v})
                    date = v.get("date") or args.get("date")
                    if date:
                        flight["dates"][date] = deepcopy(v)

            flights(value)
            return
        if action == "get_bills_for_customer" and isinstance(value, list):
            for bill in value:
                if isinstance(bill, dict) and "bill_id" in bill:
                    o["bills"][bill["bill_id"]] = deepcopy(bill)
            return
        if not isinstance(value, dict):
            return
        if action == "get_data_usage" and "line_id" in value:
            line = o["lines"].get(value["line_id"])
            if line is not None:
                line.update(
                    {
                        k: deepcopy(v)
                        for k, v in value.items()
                        if k in {"data_used_gb", "data_refueling_gb"}
                    }
                )
                if line.get("plan_id") and "data_limit_gb" in value:
                    o["plans"].setdefault(line["plan_id"], {})["data_limit_gb"] = value[
                        "data_limit_gb"
                    ]
            return
        expected = {
            "get_user_details": {"users"},
            "modify_user_address": {"users"},
            "get_order_details": {"orders"},
            "get_reservation_details": {"reservations"},
            "get_product_details": {"products"},
            "get_details_by_id": {"users", "lines", "bills", "plans", "devices"},
            "get_customer_by_id": {"users"},
            "get_customer_by_phone": {"users"},
            "get_customer_by_name": {"users"},
            "book_reservation": {"reservations"},
            "cancel_pending_order": {"orders"},
            "return_delivered_order_items": {"orders"},
            "exchange_delivered_order_items": {"orders"},
            "send_payment_request": {"bills"},
            "suspend_line": {"lines"},
            "resume_line": {"lines"},
            "enable_roaming": {"lines"},
            "disable_roaming": {"lines"},
            "refuel_data": {"lines"},
        }.get(action, set())
        if action.startswith("modify_pending_order_"):
            expected = {"orders"}
        if action.startswith("update_reservation_") or action == "cancel_reservation":
            expected = {"reservations"}
        # Prefer the specific object ID over embedded foreign keys such as user_id.
        for collection, key, discriminator in [
            ("orders", "order_id", "items"),
            ("reservations", "reservation_id", "flights"),
            ("products", "product_id", "variants"),
            ("lines", "line_id", "plan_id"),
            ("bills", "bill_id", "status"),
            ("plans", "plan_id", "data_limit_gb"),
            ("devices", "device_id", "device_type"),
            ("users", "customer_id", "line_ids"),
            ("users", "user_id", "payment_methods"),
        ]:
            if collection in expected and key in value and discriminator in value:
                o[collection][value[key]] = deepcopy(value)
                return


def event(record, number, clock, action, resource, kind="request", **extra):
    return {
        "id": f"{record['id']}:{number}",
        "time": clock,
        "kind": kind,
        "principal": "recorded_agent",
        "session": record["id"],
        "action": action,
        "resource": resource,
        "binding": "",
        "amount": 0,
        **extra,
    }


def classify(response, facts, supported, schema_errors, action="", unsupported_history=False):
    decision = response["decision"]
    reasons = set(decision["reasons"])
    errors = decision["errors"]
    domain_errors = {"flight unavailable", "insufficient seats", "item not in order"}
    unavailable = {
        error.split("/", 1)[0]: "missing_or_invalid_recorded_fact"
        for error in errors
        if error.rsplit(": ", 1)[-1] not in domain_errors
    }
    for rule in reasons & CONFIRMATION:
        unavailable[rule] = "no_trusted_bound_approval_in_dataset"
    if "telecom.roaming" in reasons:
        unavailable["telecom.roaming"] = "no_trusted_travel_sensor_in_dataset"
    if "airline.compensation" in reasons:
        unavailable["airline.compensation"] = "no_trusted_compensation_request_binding_in_dataset"
    if "airline.cancel" in reasons and not facts.get("cancellation_reason"):
        unavailable["airline.cancel"] = "literal_customer_reason_not_extracted"
    if "host.no_overlap" in reasons:
        unavailable["host.no_overlap"] = "prior_recorded_outcome_missing"
    if action == "send_certificate":
        for rule in reasons & {"airline.observed", "airline.reservation_owner"}:
            unavailable[rule] = "no_recorded_compensation_reservation_binding"
    if not facts.get("customer_id"):
        for rule in reasons & {
            "airline.user_owner",
            "airline.reservation_owner",
            "retail.profile_owner",
            "retail.order_owner",
        }:
            unavailable[rule] = "customer_not_established"
    if unsupported_history:
        for rule in reasons & {
            "airline.observed",
            "retail.status_observed",
            "retail.identity",
            "telecom.identity",
            "telecom.bill_observed",
        }:
            unavailable[rule] = "prior_unsupported_tool_cannot_supply_native_evidence"
    violations = sorted(reasons - set(unavailable) - {"default_deny"})
    if not supported:
        category = "unsupported_tool"
    elif schema_errors:
        category = "invalid_arguments"
    elif violations:
        category = "recorded_policy_failure"
    elif not decision["allow"]:
        category = "insufficient_evidence"
    else:
        category = "allow"
    return {
        "category": category,
        "allow": category == "allow",
        "native_allow": decision["allow"],
        "recorded_policy_failures": violations,
        "unavailable_rules": unavailable,
        "schema_errors": schema_errors,
    }


def replay(record, engine, schemas, mutating, journal):
    state = Observations(record["domain"])
    history = []
    calls_out = []
    diagnostics = Counter()
    unsupported_history = False
    messages = record["messages"]
    i = 0
    while i < len(messages):
        message = messages[i]
        if message["role"] == "user" and not message["calls"]:
            state.user_message(message["content"])
        calls = message["calls"]
        if not calls:
            if message["role"] == "tool":
                diagnostics["orphan_tool_responses"] += 1
            i += 1
            continue
        end = i + 1
        while end < len(messages) and messages[end]["role"] == "tool":
            end += 1
        pairs, orphaned = paired_responses(calls, messages[i + 1 : end])
        diagnostics["orphan_tool_responses"] += orphaned
        for call, (outcome, matching) in zip(calls, pairs, strict=True):
            diagnostics[f"response_matching/{matching}"] += 1
            value = payload(outcome) if outcome else None
            is_failure = failed(outcome, value) if outcome else None
            # Envelope role controls authority. A nested requestor cannot promote a user tool.
            assistant = message["role"] == "assistant"
            if call.get("requestor") != message["role"]:
                diagnostics["requestor_role_conflict"] += 1
            action, args = translated(
                record["domain"], call["name"], call["arguments"], record["dataset"]
            )
            if not assistant:
                diagnostics["user_tool_calls"] += 1
                # Device actions can alter telecom usage; discard that volatile observation.
                for line in state.objects["lines"].values():
                    line.pop("data_used_gb", None)
                if action == "make_payment":
                    state.objects["bills"].clear()
                i_event = event(
                    record,
                    f"user-{i}-{len(history)}",
                    state.clock,
                    action,
                    state.customer or "public",
                    kind="user_action",
                )
                history.insert(0, i_event)
                continue
            number = len(calls_out)
            facts, resource, identity = state.facts(action, args)
            if identity and not any(
                e["kind"] == "identity" and e["resource"] == state.customer for e in history
            ):
                history.insert(
                    0,
                    event(
                        record,
                        f"identity-{number}",
                        state.clock,
                        "user",
                        state.customer,
                        kind="identity",
                    ),
                )
            supported = action in schemas
            schema_errors = []
            if supported:
                schema_errors = [
                    f"{'.'.join(map(str, e.absolute_path))}: {e.message}"
                    for e in schemas[action].iter_errors(args)
                ]
            try:
                native_args, native_facts = normalize(args), normalize(facts)
            except (TypeError, ValueError, ArithmeticError) as exc:
                schema_errors.append(f"unit_normalization: {exc}")
                # Still ask the native engine: raw values expose type errors, never invent units.
                native_args, native_facts = args, facts
            request = event(record, number, state.clock, action, str(resource))
            amount = native_args.get("amount", 0) if isinstance(native_args, dict) else 0
            request["amount"] = max(0, amount) if type(amount) is int else 0
            command = {
                "op": "audit",
                "version": engine.version,
                "event": request,
                "arguments": native_args,
                "facts": native_facts,
                "history": history,
            }
            response = engine.request(command)
            journal.write(
                canonical(
                    {
                        "trajectory": record["id"],
                        "call": number,
                        "command": command,
                        "response": response,
                    }
                )
                + "\n"
            )
            verdict = classify(
                response, facts, supported, schema_errors, action, unsupported_history
            )
            calls_out.append(
                {
                    "trajectory": record["id"],
                    "dataset": record["dataset"],
                    "domain": record["domain"],
                    "model": record["model"],
                    "version": record["version"],
                    "call": number,
                    "source_message": message["source_message"],
                    "original_action": call["name"],
                    "action": action,
                    "arguments": args,
                    "resource": resource,
                    "supported": supported,
                    "prior_unsupported_dispatch": unsupported_history,
                    "mutating": action in mutating,
                    **verdict,
                    "native_decision": response["decision"],
                    "rules": response["rules"],
                    "response_matching": matching,
                    "recorded_outcome": (
                        "missing" if outcome is None else "failure" if is_failure else "success"
                    ),
                    "prior_recorded_dispatches": sum(e["kind"] == "dispatch" for e in history),
                }
            )
            # Continue the original trace even when LeanGuard would block this call.
            history.insert(0, {**request, "input": native_args})
            history.insert(0, {**request, "kind": "dispatch", "input": native_args})
            unsupported_history = unsupported_history or not supported
            # Even an error from a mutator/unknown tool does not certify no partial write.
            state.invalidate(
                action, args if isinstance(args, dict) else {}, action in mutating, supported
            )
            if outcome is not None:
                outcome_resource = str(resource)
                if not is_failure and supported and not schema_errors:
                    state.ingest(action, args, value)
                    if action in LOOKUPS:
                        outcome_resource = state.lookup_results.get(
                            digest([action, args]), outcome_resource
                        )
                if outcome_resource != resource:
                    # Lookup resource resolution occurs at its outcome, never before its verdict.
                    # These imported events are audit contexts, not a runtime admission journal.
                    diagnostics["lookup_resource_resolved_at_outcome"] += 1
                    history[0]["resource"] = history[1]["resource"] = outcome_resource
                history.insert(
                    0,
                    {
                        **request,
                        "kind": "failure" if is_failure else "success",
                        "resource": outcome_resource,
                        "input": native_args,
                    },
                )
        i = end
    summary = {k: v for k, v in record.items() if k != "messages"}
    summary.update(
        {
            "assistant_calls": len(calls_out),
            "categories": dict(Counter(c["category"] for c in calls_out)),
            "native_allowed": sum(c["native_allow"] for c in calls_out),
            "first_block": next((c["call"] for c in calls_out if not c["allow"]), None),
            "calls_with_recorded_policy_failures": sum(
                bool(c["recorded_policy_failures"]) for c in calls_out
            ),
            "diagnostics": dict(diagnostics),
        }
    )
    return calls_out, summary


def run(root, output, limit=None):
    output.mkdir(parents=True, exist_ok=False)
    normalized_path = root / "normalized.jsonl"
    if not normalized_path.exists():
        records, coverage = normalize_datasets(root)
        with normalized_path.open("x") as stream:
            for record in records:
                stream.write(canonical(record) + "\n")
        (root / "coverage.json").write_text(json.dumps(coverage, indent=2) + "\n")
    started = time.monotonic()
    groups = {}
    rule_failures, unavailable, diagnostics = Counter(), Counter(), Counter()
    manifests = {}
    with ExitStack() as stack:
        engines = {
            d: stack.enter_context(Engine(d, timeout=60)) for d in ("airline", "retail", "telecom")
        }
        adapters = {d: TauAdapter(d) for d in engines}
        schemas = {
            d: {a: Draft202012Validator(s["parameters"]) for a, s in adapter.tool_schemas().items()}
            for d, adapter in adapters.items()
        }
        mutations = {
            d: {a for a in schemas[d] if adapter.mutating(a)} for d, adapter in adapters.items()
        }
        manifests = {d: e.manifest for d, e in engines.items()}
        journal = stack.enter_context(
            gzip.open(output / "native-audits.jsonl.gz", "wt", compresslevel=1)
        )
        calls_file = stack.enter_context((output / "calls.jsonl").open("x"))
        traces_file = stack.enter_context((output / "trajectories.jsonl").open("x"))
        source = stack.enter_context(normalized_path.open())
        count = 0
        for index, line in enumerate(source):
            if limit is not None and index >= limit:
                break
            record = json.loads(line)
            calls, summary = replay(
                record,
                engines[record["domain"]],
                schemas[record["domain"]],
                mutations[record["domain"]],
                journal,
            )
            traces_file.write(canonical(summary) + "\n")
            key = record["dataset"] + "/" + record["domain"]
            group = groups.setdefault(key, Counter())
            group["trajectories"] += 1
            group["assistant_calls"] += len(calls)
            if any(c["recorded_policy_failures"] for c in calls):
                group["trajectories_with_recorded_policy_failure"] += 1
            if isinstance(record.get("reward"), (int, float)):
                group["trajectories_with_published_reward"] += 1
                if record["reward"] == 1:
                    group["published_successes"] += 1
                    group["published_successes_with_policy_failure"] += bool(
                        summary["calls_with_recorded_policy_failures"]
                    )
            for call in calls:
                calls_file.write(canonical(call) + "\n")
                group[call["category"]] += 1
                group["native_allowed"] += call["native_allow"]
                rule_failures.update(call["recorded_policy_failures"])
                unavailable.update(call["unavailable_rules"].keys())
            diagnostics.update(summary["diagnostics"])
            count += 1
            if count % 100 == 0:
                print(
                    canonical(
                        {"completed": count, "seconds": round(time.monotonic() - started, 1)}
                    ),
                    flush=True,
                )
        fingerprints = {d: e.fingerprint for d, e in engines.items()}
    report = {
        "completed_trajectories": count,
        "limit": limit,
        "groups": groups,
        "recorded_policy_failures": rule_failures,
        "unavailable_rule_counts": unavailable,
        "diagnostics": diagnostics,
        "policy_binary_sha256": fingerprints,
        "normalized_sha256": hashlib.sha256(normalized_path.read_bytes()).hexdigest(),
        "source_sha256": {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in (
                Path(__file__),
                Path(__file__).with_name("trajectory_data.py"),
                Path(__file__).with_name("rollout.py"),
            )
        },
        "seconds": time.monotonic() - started,
        "coverage": json.loads((root / "coverage.json").read_text()),
        "downloads": json.loads((root / "downloads.json").read_text()),
        "schemas_sha256": digest({d: a.tool_schemas() for d, a in adapters.items()}),
        "method": "native audit before each serial dispatch; fixed recorded continuation",
        "facts": "prior recognized tool observations and literal user identity/reason; no hidden database or reward facts",
        "confirmation": "absent trusted bindings remain unavailable; never inferred approval",
        "time": "pinned tau2 domain simulation clocks, not wall-clock trace timestamps",
        "task_success": "published reward only; no counterfactual success claim",
    }
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    (output / "policy-manifests.json").write_text(json.dumps(manifests, indent=2) + "\n")
    print(canonical({"completed_trajectories": count, "output": str(output)}), flush=True)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path, help="download directory with datasets/ snapshots")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--limit", type=int, help="debug only; omit for every trajectory")
    parser.add_argument(
        "--download", action="store_true", help="fetch the four pinned HF snapshots"
    )
    args = parser.parse_args()
    if args.download:
        download_datasets(args.root.resolve())
    run(args.root.resolve(), args.output.resolve(), args.limit)


if __name__ == "__main__":
    main()
