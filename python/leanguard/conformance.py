"""Article trace fixtures. Every policy verdict is computed by the Lean executable.

The unsafe response-only fixture is a negative control, not an enforcement option.
"""

import json
import subprocess
from dataclasses import dataclass

from .engine import default_binary


def event(time, action, kind, arguments, output=None, *, principal="alice", session="one"):
    return {
        "id": f"{principal}/{time}/{action}/{kind}",
        "time": time,
        "kind": kind,
        "principal": principal,
        "session": session,
        "action": action,
        "resource": "gateway",
        "binding": "",
        "amount": arguments.get("amount", arguments.get("shares", 0)),
        "input": arguments,
        "output": output,
    }


def sale(time, shares, stock="AMZN", **kwargs):
    return event(time, "SellShares", "request", {"stock": stock, "shares": shares}, **kwargs)


def approval(time, shares, approved=True, stock="AMZN", **kwargs):
    return event(
        time,
        "ApproveSale",
        "response",
        {"stock": stock, "shares": shares},
        {"approved": approved},
        **kwargs,
    )


def transfer(time, amount, kind="request", **kwargs):
    return event(time, "Transfer", kind, {"amount": amount}, **kwargs)


@dataclass(frozen=True)
class Case:
    name: str
    scenario: str
    events: list[dict]
    expected: list[bool]
    origin: str = "article"


ASYNC_TRACE = [
    transfer(0, 2000),
    transfer(1, 2000),
    transfer(2, 2000),
    transfer(3, 2000, "response"),
    transfer(4, 2000, "response"),
    transfer(5, 2000),
]

CASES = [
    Case(
        "approval_before_sale",
        "dogwood.approval",
        [sale(0, 100), approval(1700, 100), sale(1800, 100), sale(7200, 100)],
        [False, True, False],
    ),
    Case(
        "mixed_stateless_temporal",
        "dogwood.mixed",
        [sale(0, 50), approval(60, 50), sale(120, 50), approval(180, 500), sale(240, 500)],
        [False, True, False],
    ),
    Case(
        "count_six_requests",
        "dogwood.count",
        [transfer(t, 20) for t in range(0, 360, 60)],
        [True, True, True, True, True, False],
    ),
    Case(
        "distinct_includes_denied_recipient",
        "dogwood.distinct",
        [
            event(t, "Transfer", "request", {"user": user})
            for t, user in zip(
                range(0, 300, 60), ["bob", "carol", "dave", "erin", "bob"], strict=True
            )
        ],
        [True, True, True, False, False],
    ),
    Case(
        "request_sum_blocks_inflight_burst", "dogwood.sum", ASYNC_TRACE, [True, True, False, False]
    ),
    Case(
        "unsafe_response_sum_allows_burst",
        "dogwood.unsafe_response_sum",
        ASYNC_TRACE,
        [True, True, True, True],
    ),
    Case(
        "bind_settled_total",
        "dogwood.spike",
        [transfer(0, 1000, "response"), transfer(60, 500), transfer(120, 2000), transfer(180, 800)],
        [True, False, True],
    ),
    Case(
        "sum_exact_cap",
        "dogwood.sum",
        [transfer(0, 2000), transfer(1, 2000), transfer(2, 1000), transfer(3, 1)],
        [True, True, True, False],
        "added boundary",
    ),
    Case(
        "confidentiality",
        "dogwood.confidential",
        [
            event(0, "ContactExternal", "request", {}),
            event(1, "ReadDocument", "response", {}, {"confidential": True}),
            event(2, "ContactExternal", "request", {}),
            event(3, "ContactExternal", "request", {}, principal="bob"),
        ],
        [True, False, True],
        "introduction narrative",
    ),
    Case(
        "approval_inclusive_expiry_and_reuse",
        "dogwood.approval",
        [approval(0, 100), sale(1, 100), sale(3600, 100), sale(3601, 100)],
        [True, True, False],
        "added boundary",
    ),
    Case(
        "approval_exact_fields_and_principal",
        "dogwood.approval",
        [
            approval(0, 100),
            sale(1, 50),
            sale(2, 100, "MSFT"),
            sale(3, 100, principal="bob"),
            sale(4, 100),
        ],
        [False, False, False, True],
        "added adversarial",
    ),
    Case(
        "approval_false_is_not_success",
        "dogwood.approval",
        [approval(0, 100, approved=False), sale(1, 100)],
        [False],
        "added adversarial",
    ),
    Case(
        "distinct_duplicates_do_not_increase_count",
        "dogwood.distinct",
        [event(t, "Transfer", "request", {"user": "bob"}) for t in range(7)],
        [True] * 7,
        "added boundary",
    ),
    Case(
        "distinct_expiry",
        "dogwood.distinct",
        [
            event(t, "Transfer", "request", {"user": user})
            for t, user in [
                (0, "bob"),
                (1, "carol"),
                (2, "dave"),
                (3, "erin"),
                (3600, "bob"),
                (3604, "bob"),
            ]
        ],
        [True, True, True, False, False, True],
        "added boundary",
    ),
    Case(
        "request_sum_counts_denials",
        "dogwood.sum",
        [transfer(0, 5001), transfer(1, 1), transfer(3600, 1), transfer(3601, 1)],
        [False, False, False, True],
        "added adversarial",
    ),
    Case(
        "count_equal_timestamps_are_occurrences",
        "dogwood.count",
        [{**transfer(0, 1), "id": str(i)} for i in range(6)],
        [True, True, True, True, True, False],
        "added boundary",
    ),
    Case(
        "sum_ignores_foreign_principal",
        "dogwood.sum",
        [transfer(0, 5000, principal="bob"), transfer(1, 5000)],
        [True, True],
        "added adversarial",
    ),
    Case("spike_without_settlement", "dogwood.spike", [transfer(0, 1)], [False], "added boundary"),
    Case(
        "public_read_allows_contact",
        "dogwood.confidential",
        [
            event(0, "ReadDocument", "response", {}, {"confidential": False}),
            event(1, "ContactExternal", "request", {}),
        ],
        [True],
        "added boundary",
    ),
    Case(
        "default_principal_scope_spans_sessions",
        "dogwood.approval",
        [approval(0, 100, session="earlier"), sale(1, 100, session="later")],
        [True],
        "added boundary",
    ),
    Case(
        "sum_unbounded_precision",
        "dogwood.sum",
        [transfer(0, 10**50), transfer(1, 1)],
        [False, False],
        "added adversarial",
    ),
]


def replay(scenario, events):
    binary = default_binary().with_name("leanguard-conformance")
    completed = subprocess.run(
        [str(binary)],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        input=json.dumps({"scenario": scenario, "events": events}) + "\n",
        timeout=15,
    )
    result = json.loads(completed.stdout)
    if not result["ok"]:
        raise ValueError(result["error"])
    return result["result"]["decisions"]


def run_case(case):
    decisions = replay(case.scenario, case.events)
    actual = [row["decision"]["allow"] for row in decisions]
    errors = [error for row in decisions for error in row["decision"]["errors"]]
    return {
        "name": case.name,
        "origin": case.origin,
        "expected": case.expected,
        "actual": actual,
        "errors": errors,
        "passed": actual == case.expected and not errors,
    }


def main():
    results = [run_case(case) for case in CASES]
    print(
        json.dumps(
            {
                "cases": len(results),
                "decisions": sum(len(r["actual"]) for r in results),
                "passed": all(r["passed"] for r in results),
                "results": results,
            },
            indent=2,
        )
    )
    if not all(r["passed"] for r in results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
