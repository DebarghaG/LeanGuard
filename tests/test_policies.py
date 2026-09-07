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
        event("success", "update_reservation_flights"),
    ]
    assert audit("airline", "send_certificate", args, facts, history)["rules"][
        "airline.compensation"
    ]
    assert not audit("airline", "send_certificate", args, facts, history[:1])["rules"][
        "airline.compensation"
    ]
    assert not audit("airline", "send_certificate", args | {"amount": 10000}, facts, history)[
        "rules"
    ]["airline.compensation"]


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
