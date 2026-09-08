"""Deterministic boundary and correlation cases, independent of expected.out.

Each scenario is separated by more than the largest seven-day window. Events
within it retain their order, including distinct timepoints at equal timestamps.
"""

import re

from run import CLOCK_EXAMPLES, SourceEvent

ALICE = 'Drupe::OAuthUser::"alice"'
BOB = 'Drupe::OAuthUser::"bob"'
GATEWAY = 'Drupe::Gateway::"gw1"'
TEAM = 'Drupe::Team::"traders"'
DEFAULTS = {
    "approver": "alice",
    "request_id": "request-1",
    "stock": "AMZN",
    "shares": 10,
    "user": "alice",
    "server": "s1",
    "document": "safe",
    "level": 2,
    "amount": 100,
    "resource": "doc1",
    "status": "approved",
    "trusted": True,
}


def generated(bundle):
    schema = (bundle / "schema.cedarschema").read_text()
    name = bundle.name
    types = dict(re.findall(r"type\s+(\w+)\s*=\s*\{([^}]*)\}", schema))
    action_inputs = {}
    for action, body in re.findall(r'action\s+"(\w+)"(.*?)(?=\n\s*action|\Z)', schema, re.DOTALL):
        match = re.search(r"\binput:\s*(\w+)", body)
        action_inputs[action] = re.findall(r"(\w+)\??:", types.get(match[1], "")) if match else []
    events, labels = [], []
    base = 0
    custom = name == "login_attempt_custom_kind"

    def make(
        action,
        *,
        time=0,
        kind="request",
        principal=ALICE,
        scope_resource=GATEWAY,
        output=None,
        context_output=None,
        clock=None,
        entities=None,
        **inputs,
    ):
        values = {key: DEFAULTS[key] for key in action_inputs[action]}
        values.update(inputs)
        context = {"input": values}
        if clock is not None:
            context["system"] = {"now": clock}
        if context_output is not None:
            context["output"] = context_output
        logged = {
            "input": values.copy(),
            "requestId": f"r{time}-{action}",
            "callerPrincipal": {"entity": principal},
            "callerResource": {"entity": scope_resource},
        }
        if custom:
            logged = {"input": values.copy(), "actor": {"entity": principal}}
            kind = {"request": "attempt", "response": "outcome"}[kind]
        if output is not None:
            logged["output"] = output
        return SourceEvent(
            time, action, kind, principal, scope_resource, context, logged, entities or {}
        )

    def scenario(label, sequence):
        nonlocal base
        for e in sequence:
            e.time += base
            events.append(e)
            if e.kind in ("request", "attempt"):
                labels.append(label)
        base = events[-1].time + 700000

    # Every declared action, plus numeric/string/boolean boundaries where its
    # schema declares that input. Extra temporal cases below supply witnesses.
    for action, keys in [] if name in CLOCK_EXAMPLES else action_inputs.items():
        scenario("action-scope", [make(action)])
        for key in keys:
            variants = {
                "shares": [
                    -1,
                    0,
                    1,
                    5,
                    6,
                    10,
                    11,
                    49,
                    50,
                    51,
                    99,
                    100,
                    101,
                    777,
                    1000,
                    1001,
                    10000,
                    10001,
                ],
                "stock": ["", "A", "AMZN", "MSFT", "FOO", "F", "BLOCKED", "TEST_A", "TEST_"],
                "document": [
                    "",
                    "A",
                    "ABC",
                    "abc",
                    "A\n",
                    "readme",
                    "manifest",
                    "abcd",
                    "evil",
                    "badword",
                    "A42b7",
                    "A420b",
                    "a42b7",
                    "x1",
                    "x12",
                    "x123",
                    "safe",
                    "spam",
                    "violent",
                    "hateful",
                    "é",
                    "１２",
                ],
                "trusted": [False, True],
                "level": [0, 1, 2, 3],
            }.get(key, [])
            for value in variants:
                scenario(f"{key}={value!r}", [make(action, **{key: value})])
        if "stock" in keys and "shares" in keys:
            for stock in ("FOO", "MSFT", "BLOCKED", "OTHER"):
                for shares in (10, 11, 50, 51, 99, 100, 1000, 1001):
                    scenario("stock-cap-cross", [make(action, stock=stock, shares=shares)])

    # Presence guards must see request context, not logged result data.
    if name in {
        "approve_has_output_guard",
        "sell_nonzero_proceeds_decimal",
        "sell_small_proceeds_decimal_method",
        "sell_zero_proceeds_if_has",
    }:
        action = "ApproveSale" if name == "approve_has_output_guard" else "SellShares"
        outputs = (
            [{"approved": False}, {"approved": True}]
            if action == "ApproveSale"
            else [{"proceeds": {"decimal4": n}} for n in (-10000, 0, 1, 4999, 5000, 5001)]
        )
        for output in outputs:
            scenario("context-output", [make(action, context_output=output)])
            scenario("logged-output-is-not-context", [make(action, output=output)])

    if name in {"principal_is_oauth", "cond_is_oauth_in_team", "traders_is_in_group_scope"}:
        principals = [ALICE, BOB]
        if "entity IamEntity" in schema:
            principals += ['Drupe::IamEntity::"alice"']
        for principal in principals:
            scenario("entity-type-without-membership", [make("GetStockInfo", principal=principal)])
        if name != "principal_is_oauth":
            scenario("direct-membership", [make("GetStockInfo", entities={ALICE: [TEAM]})])

    if name in {"sell_after_2024_datetime", "sell_datetime_window"}:
        for clock in (
            "2023-12-31T23:59:59.999Z",
            "2024-01-01T00:00:00Z",
            "2024-01-01T00:00:00.001Z",
            "2024-12-31T23:59:59.999Z",
            "2025-01-01T00:00:00Z",
            "2025-12-31T23:59:59.999Z",
            "2026-01-01T00:00:00Z",
        ):
            scenario("clock-boundary", [make("SellShares", clock=clock)])

    # General recent/previous witness tests include empty, wrong key, foreign
    # principal, unsuccessful response, and exact inclusive window boundaries.
    witnesses = {
        "read_after_login": ("Read", "Login", "response", 3600),
        "read_after_login_success": ("Read", "Login", "response", 3600),
        "read_prev_login_success": ("Read", "Login", "response", 3600),
        "read_prev_login": ("Read", "Login", "request", 3600),
        "read_login_not_logout": ("Read", "Login", "response", 3600),
        "max_window_raised": ("Read", "Login", "response", 604800),
        "login_attempt_custom_kind": ("Read", "Login", "request", 3600),
        "transfer_prev_nested_conj": ("Transfer", "Login", "request", 7200),
        "write_after_read": ("SellShares", "ApproveSale", "response", 3600),
        "macro_library_once_is_small": ("SellShares", "ApproveSale", "request", 3600),
        "sell_after_approval_valid_ticker": ("SellShares", "ApproveSale", "response", 3600),
        "write_after_read_formerly": ("Write", "Read", "response", 3600),
        "call_temporal_condition_macro_once": ("Write", "Read", "response", 3600),
        "temporal_once_read_recent": ("Write", "Read", "request", 3600),
        "submit_after_approval_injection": ("Submit", "Approve", "request", 3600),
        "heartbeat_scope_alias": ("Alert", "Heartbeat", "request", 3600),
        "sell_shares_temporal_subexpr": ("SellShares", "SellShares", "request", 3600),
    }
    for n in (
        "alert_login_in_last_hour",
        "alert_some_login",
        "temporal_count_formerly_login",
        "call_temporal_aggregation_macro_count",
        "cedar_macro_plus_temporal_leaf",
        "call_cedar_macro_with_temporal_leaf",
    ):
        witnesses[n] = ("Alert", "Login", "request", 3600)
    if name in witnesses:
        action, witness, kind, window = witnesses[name]
        for age in (0, 1, window - 1, window, window + 1):
            scenario(
                "window-boundary",
                [make(witness, kind=kind, output={"result": True}), make(action, time=age)],
            )
        for key in action_inputs[witness]:
            if isinstance(DEFAULTS[key], str):
                scenario(
                    f"mismatched-{key}",
                    [make(witness, kind=kind, **{key: "different"}), make(action, time=10)],
                )
        scenario(
            "foreign-principal-witness",
            [make(witness, kind=kind, principal=BOB), make(action, time=10)],
        )
        scenario(
            "foreign-interleaving",
            [
                make(witness, kind=kind, output={"result": True}),
                make(action, principal=BOB, time=1),
                make(action, time=2),
            ],
        )
        scenario(
            "same-principal-interleaving",
            [
                make(witness, kind=kind, output={"result": True}),
                make(action, time=1),
                make(action, time=2),
            ],
        )
        if kind == "response":
            scenario(
                "false-output",
                [
                    make(witness, kind=kind, output={"result": False, "approved": False}),
                    make(action, time=1),
                ],
            )
        if name == "heartbeat_scope_alias":
            scenario(
                "foreign-resource",
                [make(witness, scope_resource='Drupe::Gateway::"gw2"'), make(action, time=1)],
            )

    if name == "access_not_revoked_since_grant":
        for revoke in ({}, {"user": "other"}, {"resource": "other"}, {"principal": BOB}):
            scenario(
                "revocation-scope",
                [
                    make("Grant"),
                    make("Access", time=1),
                    make("Revoke", time=2, **revoke),
                    make("Access", time=3),
                ],
            )
        for age in (0, 3599, 3600, 3601):
            scenario("grant-window", [make("Grant"), make("Access", time=age)])
        scenario(
            "regrant",
            [make("Grant"), make("Revoke", time=1), make("Grant", time=2), make("Access", time=3)],
        )
        scenario("old-revocation", [make("Revoke"), make("Grant", time=1), make("Access", time=2)])

    if name == "read_login_not_logout":
        scenario(
            "past-logout-does-not-satisfy-current-negation",
            [
                make("Login", kind="response"),
                make("Logout", kind="response", time=1),
                make("Read", time=2),
            ],
        )
    if name in {"temporal_login_then_read", "call_temporal_condition_macros_composed"}:
        for document in ("safe", "different"):
            scenario(
                "composed-witnesses",
                [
                    make("Login", kind="response"),
                    make("Read", kind="response", time=1, document=document),
                    make("Write", time=2),
                ],
            )
        scenario(
            "read-before-login-is-also-allowed",
            [
                make("Read", kind="response"),
                make("Login", kind="response", time=1),
                make("Write", time=2),
            ],
        )
    if name == "read_prev_compute_open_session":
        for logout in (False, True):
            scenario(
                "open-session",
                [
                    make("Login"),
                    *([make("Logout", time=1)] if logout else []),
                    make("Compute", time=2),
                    make("Read", time=3),
                ],
            )
    if name in {"read_since_login", "read_heartbeat_since_login_30s"}:
        middle = "Login" if name == "read_since_login" else "Heartbeat"
        scenario(
            "current-read-breaks-continuity",
            [make("Login"), make(middle, time=1), make("Read", time=2)],
        )

    if name in {
        "alert_same_user_login_and_transfer",
        "alert_login_and_big_transfer",
        "alert_same_principal_login_transfer",
    }:
        for user in ("alice", "other"):
            for amount in (99, 100, 101):
                scenario(
                    "join-and-threshold",
                    [
                        make("Login"),
                        make("Transfer", time=1, user=user, amount=amount),
                        make("Alert", time=2),
                    ],
                )
        scenario(
            "foreign-login",
            [make("Login", principal=BOB), make("Transfer", time=1), make("Alert", time=2)],
        )
    if name == "alert_exactly_three_transfers":
        scenario(
            "count-timepoints-not-unique-values-or-timestamps",
            [
                make("Transfer", amount=7, principal=BOB),
                make("Transfer", time=0, amount=7),
                make("Alert", time=0),
                make("Transfer", time=0, amount=7),
                make("Alert", time=0),
                make("Transfer", time=1, amount=7),
                make("Alert", time=1),
                make("Alert", time=3601),
            ],
        )
    if name == "alert_pending_transfers":
        scenario(
            "pending-balanced-completed",
            [
                make("Alert"),
                make("Transfer", time=1),
                make("Alert", time=2),
                make("Transfer", kind="response", time=3),
                make("Alert", time=4),
            ],
        )
        scenario(
            "foreign-response",
            [
                make("Transfer"),
                make("Transfer", kind="response", time=1, principal=BOB),
                make("Alert", time=2),
            ],
        )
    if name in {"temporal_sum_formerly_transfer", "forbid_read_transfers_over_1000"}:
        resolved = name == "forbid_read_transfers_over_1000"
        kind, action = ("response", "Read") if resolved else ("request", "Alert")
        for amounts in (
            [50, 50],
            [50, 51],
            [75, 75, -100],
            [500, 500],
            [500, 501],
            [600, 600, -1000],
            [2**63 - 1, 1, -(2**63 - 1), 101],
            [-(2**63), -(2**63), 101],
        ):
            scenario(
                "signed-sum-with-repeated-values",
                [
                    *[
                        make("Transfer", kind=kind, time=i, amount=n, output={"amount": n})
                        for i, n in enumerate(amounts)
                    ],
                    make(action, time=len(amounts)),
                ],
            )
    if name in {
        "alert_login_current_tp",
        "alert_heartbeat_and_login_rate",
        "alert_total_transfer_over_200",
    }:
        action = "Transfer" if name == "alert_total_transfer_over_200" else "Login"
        sequence = [make("Heartbeat")] if "Heartbeat" in action_inputs else []
        sequence += [make(action, time=i + 1) for i in range(3)]
        sequence.append(make("Alert", time=4))
        scenario("past-events-do-not-count-as-current", sequence)
    return events, labels
