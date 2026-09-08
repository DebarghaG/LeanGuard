"""Native predicate tests use Lean's read-only audit interface, not a Python evaluator."""

from copy import deepcopy

import pytest
from leanguard import Engine


def event(kind, action, resource="resource", binding="approval", time=100000):
    return {
        "id": kind + action + resource,
        "time": time,
        "kind": kind,
        "principal": "actor",
        "session": "conversation",
        "action": action,
        "resource": resource,
        "binding": binding,
        "amount": 0,
    }


def audit(domain, action, arguments, facts, history=()):
    with Engine(domain) as engine:
        return engine.request(
            {
                "op": "audit",
                "version": 0,
                "event": event("request", action),
                "arguments": arguments,
                "facts": facts,
                "history": list(history),
            }
        )


RETAIL = {
    "customer_id": "customer",
    "lookup_customer_id": "customer",
    "user": {
        "payment_methods": {
            "old": {"source": "credit_card"},
            "new": {"source": "credit_card"},
            "gift": {"source": "gift_card", "balance": 5000},
        }
    },
    "order": {
        "user_id": "customer",
        "status": "pending",
        "items": [{"item_id": "a", "product_id": "product", "price": 2000}],
        "payment_history": [{"payment_method_id": "old", "transaction_type": "payment"}],
    },
    "products": {"product": {"variants": {"b": {"available": True, "price": 3000}}}},
}


@pytest.mark.parametrize(
    "action,rule,args,negative",
    [
        (
            "cancel_pending_order",
            "retail.cancel_reason",
            {"order_id": "resource", "reason": "no longer needed"},
            {"reason": "arbitrary"},
        ),
        (
            "modify_pending_order_payment",
            "retail.payment",
            {"order_id": "resource", "payment_method_id": "new"},
            {"payment_method_id": "old"},
        ),
        (
            "modify_pending_order_items",
            "retail.modify_items",
            {
                "order_id": "resource",
                "item_ids": ["a"],
                "new_item_ids": ["b"],
                "payment_method_id": "gift",
            },
            {"new_item_ids": ["a"]},
        ),
        (
            "exchange_delivered_order_items",
            "retail.exchange_items",
            {
                "order_id": "resource",
                "item_ids": ["a"],
                "new_item_ids": ["b"],
                "payment_method_id": "gift",
            },
            {"item_ids": ["a", "a"], "new_item_ids": ["b", "b"]},
        ),
        (
            "return_delivered_order_items",
            "retail.return",
            {"order_id": "resource", "item_ids": ["a"], "payment_method_id": "old"},
            {"payment_method_id": "new"},
        ),
    ],
)
def test_retail_value_rules(action, rule, args, negative):
    good = audit("retail", action, args, RETAIL)
    assert good["rules"][rule]
    bad = audit("retail", action, args | negative, RETAIL)
    assert not bad["rules"][rule]


def test_retail_insufficient_balance_and_unavailable_variant():
    args = {
        "order_id": "resource",
        "item_ids": ["a"],
        "new_item_ids": ["b"],
        "payment_method_id": "gift",
    }
    facts = deepcopy(RETAIL)
    facts["user"]["payment_methods"]["gift"]["balance"] = 999
    assert not audit("retail", "modify_pending_order_items", args, facts)["rules"][
        "retail.modify_items"
    ]
    facts = deepcopy(RETAIL)
    facts["products"]["product"]["variants"]["b"]["available"] = False
    assert not audit("retail", "modify_pending_order_items", args, facts)["rules"][
        "retail.modify_items"
    ]


def test_schema_rejects_wrong_scalar_types():
    result = audit(
        "retail", "cancel_pending_order", {"order_id": 42, "reason": "no longer needed"}, RETAIL
    )
    assert not result["decision"]["allow"]
    assert not result["rules"]["schema.cancel_pending_order"]


def test_modification_reservation_is_per_resource_across_sessions():
    past = event("dispatch", "modify_pending_order_address")
    past["session"] = "earlier"
    args = {"order_id": "resource", "payment_method_id": "new"}
    assert not audit("retail", "modify_pending_order_payment", args, RETAIL, [past])["rules"][
        "retail.modify_once"
    ]
    past["resource"] = "different"
    assert audit("retail", "modify_pending_order_payment", args, RETAIL, [past])["rules"][
        "retail.modify_once"
    ]


AIRLINE = {
    "customer_id": "customer",
    "cancellation_reason": "change of plan",
    "user": {
        "membership": "regular",
        "payment_methods": {
            "card": {"source": "credit_card"},
            "gift": {"source": "gift_card", "amount": 50000},
            "cert": {"source": "certificate", "amount": 50000},
        },
    },
    "reservation": {
        "reservation_id": "resource",
        "user_id": "customer",
        "status": None,
        "cabin": "economy",
        "insurance": "no",
        "origin": "SFO",
        "destination": "JFK",
        "flight_type": "one_way",
        "created_epoch": 99900,
        "total_baggages": 1,
        "nonfree_baggages": 0,
        "passengers": [{"first_name": "A", "last_name": "B", "dob": "2000-01-01"}],
        "flights": [{"flight_number": "F1", "date": "2024-05-16", "price": 10000}],
    },
    "flights": {
        "F1": {
            "origin": "SFO",
            "destination": "JFK",
            "dates": {
                "2024-05-16": {
                    "departure_epoch": 1000,
                    "arrival_epoch": 2000,
                    "status": "available",
                    "available_seats": {"economy": 10, "business": 10},
                    "prices": {"economy": 10000, "business": 20000},
                }
            },
        },
        "F2": {
            "origin": "SFO",
            "destination": "JFK",
            "dates": {
                "2024-05-16": {
                    "departure_epoch": 1000,
                    "arrival_epoch": 2000,
                    "status": "available",
                    "available_seats": {"economy": 10},
                    "prices": {"economy": 12000},
                }
            },
        },
    },
}


def test_airline_booking_payment_limits_and_total():
    r = AIRLINE["reservation"]
    args = {
        k: deepcopy(r[k])
        for k in ("origin", "destination", "flight_type", "cabin", "passengers", "insurance")
    }
    args |= {
        "user_id": "customer",
        "flights": [{"flight_number": "F1", "date": "2024-05-16"}],
        "total_baggages": 1,
        "nonfree_baggages": 0,
        "payment_methods": [{"payment_id": "card", "amount": 10000}],
    }
    assert audit("airline", "book_reservation", args, AIRLINE)["rules"]["airline.booking"]
    for bad in (
        {"passengers": args["passengers"] * 6},
        {"nonfree_baggages": 1},
        {"payment_methods": [{"payment_id": "card", "amount": 9999}]},
        {"payment_methods": [{"payment_id": "card", "amount": 5000}] * 2},
        {"destination": "LAX"},
    ):
        assert not audit("airline", "book_reservation", args | bad, AIRLINE)["rules"][
            "airline.booking"
        ]


def test_airline_passenger_and_baggage_updates():
    args = {"reservation_id": "resource", "passengers": AIRLINE["reservation"]["passengers"]}
    assert audit("airline", "update_reservation_passengers", args, AIRLINE)["rules"][
        "airline.passengers"
    ]
    assert not audit(
        "airline", "update_reservation_passengers", args | {"passengers": []}, AIRLINE
    )["rules"]["airline.passengers"]
    args = {
        "reservation_id": "resource",
        "total_baggages": 2,
        "nonfree_baggages": 1,
        "payment_id": "card",
    }
    assert audit("airline", "update_reservation_baggages", args, AIRLINE)["rules"][
        "airline.baggage"
    ]
    assert not audit(
        "airline", "update_reservation_baggages", args | {"total_baggages": 0}, AIRLINE
    )["rules"]["airline.baggage"]
    assert not audit(
        "airline", "update_reservation_baggages", args | {"payment_id": "cert"}, AIRLINE
    )["rules"]["airline.baggage"]
    facts = deepcopy(AIRLINE)
    facts["user"]["payment_methods"]["gift"]["amount"] = 4999
    assert not audit(
        "airline", "update_reservation_baggages", args | {"payment_id": "gift"}, facts
    )["rules"]["airline.baggage"]


def test_airline_flight_changes_and_cabin_exception():
    args = {
        "reservation_id": "resource",
        "cabin": "economy",
        "payment_id": "card",
        "flights": [{"flight_number": "F2", "date": "2024-05-16"}],
    }
    assert audit("airline", "update_reservation_flights", args, AIRLINE)["rules"]["airline.flights"]
    facts = deepcopy(AIRLINE)
    facts["reservation"]["cabin"] = "basic_economy"
    assert not audit("airline", "update_reservation_flights", args, facts)["rules"][
        "airline.flights"
    ]
    args |= {"cabin": "business", "flights": [{"flight_number": "F1", "date": "2024-05-16"}]}
    assert audit("airline", "update_reservation_flights", args, facts)["rules"]["airline.flights"]
    facts["flights"]["F1"]["dates"]["2024-05-16"]["status"] = "landed"
    assert not audit("airline", "update_reservation_flights", args, facts)["rules"][
        "airline.flights"
    ]


def test_airline_compensation_requested_amount_and_predecessor():
    facts = deepcopy(AIRLINE)
    facts["user"]["membership"] = "silver"
    facts["flights"]["F1"]["dates"]["2024-05-16"]["status"] = "delayed"
    args = {"user_id": "customer", "amount": 5000}
    history = [
        event("compensation_requested", "user"),
        event("success", "update_reservation_flights") | {"facts": deepcopy(facts)},
    ]
    assert audit("airline", "send_certificate", args, facts, history)["rules"][
        "airline.compensation"
    ]
    assert not audit("airline", "send_certificate", args, facts, history[:1])["rules"][
        "airline.compensation"
    ]
    assert not audit("airline", "send_certificate", args, facts, history[1:])["rules"][
        "airline.compensation"
    ]
    assert not audit("airline", "send_certificate", args | {"amount": 10000}, facts, history)[
        "rules"
    ]["airline.compensation"]


@pytest.mark.parametrize(
    "departure,arrival,allowed",
    [
        (1999, 3000, False),
        (2000, 3000, False),
        (2001, 3000, True),
        (2001, 2001, False),
        (2001, 2000, False),
    ],
)
@pytest.mark.parametrize("action", ["book_reservation", "update_reservation_flights"])
def test_airline_itinerary_requires_chronological_connections(action, departure, arrival, allowed):
    facts = deepcopy(AIRLINE)
    facts["flights"]["F1"]["destination"] = "ORD"
    facts["flights"]["F2"]["origin"] = "ORD"
    facts["flights"]["F2"]["dates"]["2024-05-16"].update(
        departure_epoch=departure, arrival_epoch=arrival
    )
    args = {
        "reservation_id": "resource",
        "cabin": "economy",
        "payment_id": "card",
        "flights": [{"flight_number": f, "date": "2024-05-16"} for f in ["F1", "F2"]],
    }
    rule = "airline.flights"
    if action == "book_reservation":
        args.update(
            {
                k: facts["reservation"][k]
                for k in ["origin", "destination", "flight_type", "passengers", "insurance"]
            }
        )
        args.update(
            user_id="customer",
            total_baggages=0,
            nonfree_baggages=0,
            payment_methods=[{"payment_id": "card", "amount": 22000}],
        )
        rule = "airline.booking"
    assert audit("airline", action, args, facts)["rules"][rule] is allowed
    if allowed:
        del facts["flights"]["F2"]["dates"]["2024-05-16"]["departure_epoch"]
        missing = audit("airline", action, args, facts)
        assert not missing["rules"][rule]
        assert missing["decision"]["errors"]


@pytest.mark.parametrize(
    "change",
    [
        None,
        "failure",
        "unknown",
        "dispatch",
        "session",
        "principal",
        "resource",
        "future",
        "customer",
        "reservation",
        "owner",
        "passengers",
        "no_delay",
        "missing_snapshot",
        "ineligible",
    ],
)
def test_compensation_requires_correlated_success_with_prior_delay(change):
    facts = deepcopy(AIRLINE)
    before = deepcopy(facts)
    # Eligibility for the original delay survives a later cabin downgrade.
    before["reservation"]["cabin"] = "business"
    before["flights"]["F1"]["dates"]["2024-05-16"]["status"] = "delayed"
    past = event("success", "update_reservation_flights") | {"facts": before}
    if change in {"failure", "unknown", "dispatch"}:
        past["kind"] = change
    elif change in {"session", "principal", "resource"}:
        past[change] = "other"
    elif change == "future":
        past["time"] += 1
    elif change == "customer":
        before["customer_id"] = "other"
    elif change == "reservation":
        before["reservation"]["reservation_id"] = "other"
    elif change == "owner":
        before["reservation"]["user_id"] = "other"
    elif change == "passengers":
        before["reservation"]["passengers"] *= 2
    elif change == "no_delay":
        before["flights"]["F1"]["dates"]["2024-05-16"]["status"] = "available"
    elif change == "missing_snapshot":
        past.pop("facts")
    elif change == "ineligible":
        before["reservation"]["cabin"] = "economy"
    args = {"user_id": "customer", "amount": 5000}
    history = [event("compensation_requested", "user"), past]
    assert audit("airline", "send_certificate", args, facts, history)["rules"][
        "airline.compensation"
    ] is (change is None)


@pytest.mark.parametrize("delayed_at_dispatch", [True, False])
def test_live_outcome_cannot_replace_admission_snapshot(delayed_at_dispatch):
    before = deepcopy(AIRLINE)
    before["user"]["membership"] = "silver"
    before["flights"]["F1"]["dates"]["2024-05-16"]["status"] = (
        "delayed" if delayed_at_dispatch else "available"
    )
    forged = deepcopy(before)
    forged["flights"]["F1"]["dates"]["2024-05-16"]["status"] = (
        "available" if delayed_at_dispatch else "delayed"
    )
    current = deepcopy(before)
    current["reservation"]["flights"] = [
        {"flight_number": "F2", "date": "2024-05-16", "price": 12000}
    ]
    with Engine("airline") as engine:

        def observe(e, **extra):
            return engine.request({"op": "observe", "version": engine.version, "event": e, **extra})

        def admit(action, args, facts):
            request = event("request", action, binding=action) | {"input": args, "facts": forged}
            result = engine.request(
                {
                    "op": "admit",
                    "version": engine.version,
                    "event": request,
                    "arguments": args,
                    "facts": facts,
                }
            )["decision"]
            return request, result

        observe(event("identity", "user", "customer"))
        observe(event("compensation_requested", "user"))
        read, result = admit("get_reservation_details", {"reservation_id": "resource"}, before)
        assert result["allow"]
        observe(read | {"kind": "success"}, outcome=before["reservation"])
        observe(
            event("confirmed", "update_reservation_flights", binding="update_reservation_flights")
        )
        args = {
            "reservation_id": "resource",
            "cabin": "economy",
            "payment_id": "card",
            "flights": [{"flight_number": "F2", "date": "2024-05-16"}],
        }
        update, result = admit("update_reservation_flights", args, before)
        assert result["allow"]
        observe(update | {"kind": "success", "facts": forged}, outcome=current["reservation"])
        observe(event("confirmed", "send_certificate", binding="certificate"))
        request = event("request", "send_certificate", binding="certificate")
        result = engine.request(
            {
                "op": "admit",
                "version": engine.version,
                "event": request,
                "arguments": {"user_id": "customer", "amount": 5000},
                "facts": current,
            }
        )["decision"]
        assert result["allow"] is delayed_at_dispatch


TELECOM = {
    "customer_id": "customer",
    "lookup_customer_id": "customer",
    "user": {"line_ids": ["resource"], "bill_ids": ["bill"]},
    "line": {
        "status": "Suspended",
        "contract_end_epoch": 100001,
        "data_used_gb_milli": 10001,
        "roaming_enabled": False,
    },
    "plan": {"data_limit_gb_milli": 10000},
    "bills": [{"status": "Paid", "bill_id": "bill"}],
    "bill": {"status": "Overdue", "bill_id": "bill"},
}


@pytest.mark.parametrize("action", ["get_bills_for_customer", "get_details_by_id"])
@pytest.mark.parametrize(
    "change",
    [None, "empty", "bill", "customer", "status", "amount", "session", "principal", "future"],
)
def test_bill_observation_requires_target_details_in_actual_response(action, change):
    bill = {
        "bill_id": "resource",
        "customer_id": "customer",
        "status": "Overdue",
        "total_due": 10.5,
    }
    if change == "bill":
        bill["bill_id"] = "another"
    elif change == "customer":
        bill["customer_id"] = "another"
    elif change == "status":
        del bill["status"]
    elif change == "amount":
        bill["total_due"] = "unknown"
    resource = "customer" if action == "get_bills_for_customer" else "resource"
    output = [bill] if action == "get_bills_for_customer" else bill
    if change == "empty":
        output = [] if action == "get_bills_for_customer" else {}
    past = event("success", action, resource) | {"output": output}
    if change in {"session", "principal"}:
        past[change] = "another"
    elif change == "future":
        past["time"] += 1
    args = {"customer_id": "customer", "bill_id": "resource"}
    assert audit("telecom", "send_payment_request", args, TELECOM, [past])["rules"][
        "telecom.bill_observed"
    ] is (change is None)


def test_telecom_resume_and_contract_boundary():
    args = {"customer_id": "customer", "line_id": "resource"}
    assert audit("telecom", "resume_line", args, TELECOM)["rules"]["telecom.resume"]
    for change in ("expired", "overdue"):
        facts = deepcopy(TELECOM)
        if change == "expired":
            facts["line"]["contract_end_epoch"] = 99999
        else:
            facts["bills"][0]["status"] = "Overdue"
        assert not audit("telecom", "resume_line", args, facts)["rules"]["telecom.resume"]


@pytest.mark.parametrize("amount,expected", [(0, False), (1, True), (2000, True), (2001, False)])
def test_telecom_refueling_boundaries(amount, expected):
    args = {
        "customer_id": "customer",
        "line_id": "resource",
        "gb_amount": amount / 1000,
        "gb_amount_milli": amount,
    }
    assert audit("telecom", "refuel_data", args, TELECOM)["rules"]["telecom.refuel"] is expected


def test_telecom_roaming_requires_trusted_travel_observation():
    args = {"customer_id": "customer", "line_id": "resource"}
    assert not audit("telecom", "enable_roaming", args, TELECOM)["rules"]["telecom.roaming"]
    assert audit("telecom", "enable_roaming", args, TELECOM, [event("travelling", "user")])[
        "rules"
    ]["telecom.roaming"]


def test_telecom_suspension_needs_real_reason():
    args = {"customer_id": "customer", "line_id": "resource", "reason": "overdue bill"}
    assert not audit("telecom", "suspend_line", args, TELECOM)["rules"]["telecom.suspend"]
    facts = deepcopy(TELECOM)
    facts["bills"][0]["status"] = "Overdue"
    assert audit("telecom", "suspend_line", args, facts)["rules"]["telecom.suspend"]
