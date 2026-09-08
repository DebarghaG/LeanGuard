import pytest

pytest.importorskip("tau2")

from leanguard import GuardHost
from leanguard.tau import TauAdapter


@pytest.fixture(params=["retail", "airline", "telecom"])
def adapter(request):
    return TauAdapter(request.param)


def test_compiled_actions_cover_actual_tool_set(adapter, tmp_path):
    with GuardHost(
        adapter.domain,
        tmp_path / "journal.sqlite",
        adapter,
        principal="actor",
        session="conversation",
        clock=lambda: adapter.clock,
    ) as host:
        declared = {a for rule in host.engine.manifest["rules"] for a in rule["actions"]}
        assert set(adapter.tool_schemas()) == declared


def test_native_schemas_match_pinned_tool_definitions():
    import subprocess
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    generated = subprocess.run(
        [sys.executable, "scripts/emit_schemas.py"],
        cwd=root,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    )
    assert generated.stdout == (root / "LeanGuard" / "ToolSchemas.lean").read_text()


def test_retail_confirmation_and_real_mutation(tmp_path):
    adapter = TauAdapter("retail")
    db = adapter.environment.tools.db
    order = next(o for o in db.orders.values() if o.status == "pending")
    user = db.users[order.user_id]
    args = {"order_id": order.order_id, "reason": "no longer needed"}
    with GuardHost(
        "retail",
        tmp_path / "journal.sqlite",
        adapter,
        principal="actor",
        session="conversation",
        clock=lambda: adapter.clock,
    ) as host:
        before = db.get_hash()
        denied = host.execute("cancel_pending_order", args)
        assert not denied["allow"]
        assert db.get_hash() == before
        assert host.execute("find_user_id_by_email", {"email": user.email})["allow"]
        assert host.customer() == user.user_id
        assert host.execute("get_order_details", {"order_id": order.order_id})["allow"]
        proposal = host.prepare("cancel_pending_order", args)
        host.confirm(proposal.id, True)
        result = host.execute("cancel_pending_order", args, proposal_id=proposal.id)
        assert result.get("outcome") == "success", result
        assert order.status == "cancelled"


def test_retail_cross_customer_denied(tmp_path):
    adapter = TauAdapter("retail")
    db = adapter.environment.tools.db
    user = next(iter(db.users.values()))
    order = next(o for o in db.orders.values() if o.user_id != user.user_id)
    with GuardHost(
        "retail",
        tmp_path / "journal.sqlite",
        adapter,
        principal="actor",
        session="conversation",
        clock=lambda: adapter.clock,
    ) as host:
        host.execute("find_user_id_by_email", {"email": user.email})
        result = host.execute("get_order_details", {"order_id": order.order_id})
        assert not result["allow"]
        assert "retail.order_owner" in result["reasons"]


def test_airline_tool_would_cancel_but_policy_blocks(tmp_path):
    from tau2.domains.airline.data_model import FlightDateStatusAvailable

    adapter = TauAdapter("airline")
    db = adapter.environment.tools.db
    reservation = next(iter(db.reservations.values()))
    reservation.created_at = "2024-01-01T00:00:00"
    reservation.cabin = "basic_economy"
    reservation.insurance = "no"
    reservation.status = None
    # An ordinary unflown flight; cancellation outside 24h has no eligible exception.
    for segment in reservation.flights:
        db.flights[segment.flight_number].dates[segment.date] = FlightDateStatusAvailable(
            status="available", available_seats={}, prices={}
        )
    adapter.user_evidence["cancellation_reason"] = "change of plan"
    with GuardHost(
        "airline",
        tmp_path / "journal.sqlite",
        adapter,
        principal="actor",
        session="conversation",
        clock=lambda: adapter.clock,
    ) as host:
        host.observe_trusted("identity", reservation.user_id)
        args = {"reservation_id": reservation.reservation_id}
        host.execute("get_reservation_details", args)
        proposal = host.prepare("cancel_reservation", args)
        host.confirm(proposal.id, True)
        before = db.get_hash()
        denied = host.execute("cancel_reservation", args, proposal_id=proposal.id)
        assert not denied["allow"]
        assert "airline.cancel" in denied["reasons"]
        assert db.get_hash() == before
        # Direct invocation demonstrates the missing tool-level eligibility check.
        adapter.execute("cancel_reservation", args)
        assert reservation.status == "cancelled"


def test_airline_valid_cancellation(tmp_path):
    from tau2.domains.airline.data_model import FlightDateStatusAvailable

    adapter = TauAdapter("airline")
    db = adapter.environment.tools.db
    reservation = next(iter(db.reservations.values()))
    reservation.created_at = "2024-05-15T14:00:00"
    reservation.status = None
    for segment in reservation.flights:
        db.flights[segment.flight_number].dates[segment.date] = FlightDateStatusAvailable(
            status="available", available_seats={}, prices={}
        )
    adapter.user_evidence["cancellation_reason"] = "change of plan"
    with GuardHost(
        "airline",
        tmp_path / "journal.sqlite",
        adapter,
        principal="actor",
        session="conversation",
        clock=lambda: adapter.clock,
    ) as host:
        host.observe_trusted("identity", reservation.user_id)
        args = {"reservation_id": reservation.reservation_id}
        host.execute("get_reservation_details", args)
        proposal = host.prepare("cancel_reservation", args)
        host.confirm(proposal.id, True)
        result = host.execute("cancel_reservation", args, proposal_id=proposal.id)
        assert result.get("outcome") == "success", result
        assert reservation.status == "cancelled"


def test_telecom_overdue_status_and_actual_payment_request(tmp_path):
    from tau2.domains.telecom.data_model import BillStatus

    adapter = TauAdapter("telecom")
    db = adapter.environment.tools.db
    customer = next(u for u in db.customers if u.bill_ids)
    bills = [b for b in db.bills if b.bill_id in customer.bill_ids]
    for bill in bills:
        bill.status = BillStatus.PAID
    bill = bills[0]
    with GuardHost(
        "telecom",
        tmp_path / "journal.sqlite",
        adapter,
        principal="actor",
        session="conversation",
        clock=lambda: adapter.clock,
    ) as host:
        assert host.execute("get_customer_by_id", {"customer_id": customer.customer_id})["allow"]
        assert host.execute("get_bills_for_customer", {"customer_id": customer.customer_id})[
            "allow"
        ]
        args = {"customer_id": customer.customer_id, "bill_id": bill.bill_id}
        before = db.get_hash()
        denied = host.execute("send_payment_request", args)
        assert not denied["allow"]
        assert "telecom.payment_request" in denied["reasons"]
        assert db.get_hash() == before
        bill.status = BillStatus.OVERDUE
        result = host.execute("send_payment_request", args)
        assert result.get("outcome") == "success", result
        assert bill.status == BillStatus.AWAITING_PAYMENT
        assert not host.execute("send_payment_request", args)["allow"]


def test_empty_bill_lookup_does_not_authorize_payment(tmp_path):
    from tau2.domains.telecom.data_model import BillStatus

    adapter = TauAdapter("telecom")
    db = adapter.environment.tools.db
    customer = next(u for u in db.customers if u.bill_ids)
    bills = [b for b in db.bills if b.bill_id in customer.bill_ids]
    for bill in bills:
        bill.status = BillStatus.PAID
    bill = bills[0]
    bill.status = BillStatus.OVERDUE
    with GuardHost(
        "telecom",
        tmp_path / "journal.sqlite",
        adapter,
        principal="actor",
        session="conversation",
        clock=lambda: adapter.clock,
    ) as host:
        assert (
            host.execute("get_customer_by_id", {"customer_id": customer.customer_id})["outcome"]
            == "success"
        )
        result = host.execute(
            "get_bills_for_customer", {"customer_id": customer.customer_id, "limit": 0}
        )
        assert result["result"] == []
        args = {"customer_id": customer.customer_id, "bill_id": bill.bill_id}
        before = db.get_hash()
        denied = host.execute("send_payment_request", args)
        assert not denied["allow"]
        assert "telecom.bill_observed" in denied["reasons"]
        assert db.get_hash() == before
        assert host.execute("get_details_by_id", {"id": bill.bill_id})["outcome"] == "success"
        assert host.execute("send_payment_request", args)["outcome"] == "success"
        assert bill.status == BillStatus.AWAITING_PAYMENT


def test_airline_rebooking_compensation_survives_restart(tmp_path):
    from tau2.domains.airline.data_model import FlightDateStatusAvailable, FlightDateStatusDelayed

    adapter = TauAdapter("airline")
    db = adapter.environment.tools.db
    reservation = next(
        r
        for r in db.reservations.values()
        if r.flights
        and r.passengers
        and any(p.source == "credit_card" for p in db.users[r.user_id].payment_methods.values())
    )
    user = db.users[reservation.user_id]
    user.membership = "silver"
    reservation.status = None
    reservation.cabin = "economy"
    reservation.flight_type = "one_way"
    reservation.flights = reservation.flights[:1]
    old = reservation.flights[0]
    reservation.origin, reservation.destination = old.origin, old.destination
    db.flights[old.flight_number].dates[old.date] = FlightDateStatusDelayed(
        status="delayed",
        estimated_departure_time_est="2024-05-16T10:00:00",
        estimated_arrival_time_est="2024-05-16T12:00:00",
    )
    replacement = next(
        f
        for f in db.flights.values()
        if f.origin == old.origin
        and f.destination == old.destination
        and f.flight_number != old.flight_number
    )
    replacement.dates[old.date] = FlightDateStatusAvailable(
        status="available", available_seats={"economy": 10}, prices={"economy": old.price}
    )
    card = next(k for k, p in user.payment_methods.items() if p.source == "credit_card")
    adapter.user_evidence["compensation_reservation"] = reservation.reservation_id
    path = tmp_path / "journal.sqlite"
    with GuardHost(
        "airline",
        path,
        adapter,
        principal="actor",
        session="conversation",
        clock=lambda: adapter.clock,
    ) as host:
        host.observe_trusted("identity", user.user_id)
        host.observe_trusted("compensation_requested", reservation.reservation_id)
        lookup = {"reservation_id": reservation.reservation_id}
        assert host.execute("get_reservation_details", lookup)["outcome"] == "success"
        args = lookup | {
            "cabin": "economy",
            "flights": [{"flight_number": replacement.flight_number, "date": old.date}],
            "payment_id": card,
        }
        proposal = host.prepare("update_reservation_flights", args)
        host.confirm(proposal.id, True)
        assert (
            host.execute("update_reservation_flights", args, proposal_id=proposal.id)["outcome"]
            == "success"
        )
        assert all(f.flight_number != old.flight_number for f in reservation.flights)
        completed = host.events()[-1]
        assert (
            completed["facts"]["flights"][old.flight_number]["dates"][old.date]["status"]
            == "delayed"
        )
        assert host.execute("get_reservation_details", lookup)["outcome"] == "success"
    with GuardHost(
        "airline",
        path,
        adapter,
        principal="actor",
        session="conversation",
        clock=lambda: adapter.clock,
    ) as host:
        args = {"user_id": user.user_id, "amount": 50 * len(reservation.passengers)}
        # Retained disruption evidence cannot substitute for fresh bound consent.
        denied = host.execute("send_certificate", args)
        assert not denied["allow"]
        assert "airline.confirmation" in denied["reasons"]
        assert "airline.compensation" not in denied["reasons"]
        proposal = host.prepare("send_certificate", args)
        host.confirm(proposal.id, True)
        assert (
            host.execute("send_certificate", args, proposal_id=proposal.id)["outcome"] == "success"
        )


def test_airline_booking_rejects_backward_dates(tmp_path):
    from tau2.domains.airline.data_model import FlightDateStatusAvailable

    adapter = TauAdapter("airline")
    db = adapter.environment.tools.db
    user = next(
        u
        for u in db.users.values()
        if u.saved_passengers and any(p.source == "credit_card" for p in u.payment_methods.values())
    )
    first = next(iter(db.flights.values()))
    second = next(
        f
        for f in db.flights.values()
        if f.origin == first.destination and f.destination != first.origin
    )
    for flight, day in [(first, "2024-05-20"), (second, "2024-05-19"), (second, "2024-05-22")]:
        flight.dates[day] = FlightDateStatusAvailable(
            status="available", available_seats={"economy": 10}, prices={"economy": 100}
        )
    card = next(k for k, p in user.payment_methods.items() if p.source == "credit_card")
    args = {
        "user_id": user.user_id,
        "origin": first.origin,
        "destination": second.destination,
        "flight_type": "one_way",
        "cabin": "economy",
        "flights": [
            {"flight_number": first.flight_number, "date": "2024-05-20"},
            {"flight_number": second.flight_number, "date": "2024-05-19"},
        ],
        "passengers": [user.saved_passengers[0].model_dump()],
        "payment_methods": [{"payment_id": card, "amount": 200}],
        "total_baggages": 0,
        "nonfree_baggages": 0,
        "insurance": "no",
    }
    with GuardHost(
        "airline",
        tmp_path / "journal.sqlite",
        adapter,
        principal="actor",
        session="conversation",
        clock=lambda: adapter.clock,
    ) as host:
        host.observe_trusted("identity", user.user_id)
        proposal = host.prepare("book_reservation", args)
        host.confirm(proposal.id, True)
        before = db.get_hash()
        denied = host.execute("book_reservation", args, proposal_id=proposal.id)
        assert not denied["allow"]
        assert "airline.booking" in denied["reasons"]
        assert db.get_hash() == before
        args["flights"][1]["date"] = "2024-05-22"
        proposal = host.prepare("book_reservation", args)
        host.confirm(proposal.id, True)
        assert (
            host.execute("book_reservation", args, proposal_id=proposal.id)["outcome"] == "success"
        )


@pytest.mark.parametrize("domain", ["retail", "telecom"])
def test_unresolved_lookup_does_not_authenticate_or_lock_out_recovery(tmp_path, domain):
    from leanguard.tau import GuardedEnvironment
    from tau2.data_model.message import ToolCall

    adapter = TauAdapter(domain)
    if domain == "retail":
        first, second = list(adapter.environment.tools.db.users.values())[:2]
        action, missing = "find_user_id_by_email", {"email": "missing@example.invalid"}
        correct, other = {"email": first.email}, {"email": second.email}
        customer = first.user_id
    else:
        first, second = adapter.environment.tools.db.customers[:2]
        action, missing = "get_customer_by_phone", {"phone_number": "missing"}
        correct, other = {"phone_number": first.phone_number}, {"phone_number": second.phone_number}
        customer = first.customer_id
    with GuardHost(
        domain,
        tmp_path / "journal.sqlite",
        adapter,
        principal="actor",
        session="test",
        clock=lambda: adapter.clock,
    ) as host:
        proxy = GuardedEnvironment(host)
        reply = proxy.get_response(ToolCall(id="missing", name=action, arguments=missing))
        assert reply.error
        assert reply.content.startswith("Error:")
        assert host.customer() == ""
        assert host.events()[-1]["kind"] == "failure"
        assert host.execute(action, correct)["outcome"] == "success"
        assert host.customer() == customer
        assert not host.execute(action, other)["allow"]
        assert host.execute(action, missing)["outcome"] == "failure"
        assert host.customer() == customer
        assert host.execute(action, correct)["outcome"] == "success"


def test_telecom_date_output_completes_and_preserves_wire(tmp_path):
    import json

    from leanguard.tau import GuardedEnvironment
    from tau2.data_model.message import ToolCall

    adapter = TauAdapter("telecom")
    with GuardHost(
        "telecom",
        tmp_path / "journal.sqlite",
        adapter,
        principal="actor",
        session="conversation",
        clock=lambda: adapter.clock,
    ) as host:
        wrapper = GuardedEnvironment(host)
        assert host.execute("get_customer_by_id", {"customer_id": "C1001"})["allow"]
        args = {"customer_id": "C1001", "line_id": "L1002"}
        expected = adapter.environment.get_response(
            ToolCall(id="reference", name="get_data_usage", arguments=args)
        )
        for id in ("first", "second"):
            actual = wrapper.get_response(ToolCall(id=id, name="get_data_usage", arguments=args))
            assert not actual.error, actual.content
            assert json.loads(actual.content) == json.loads(expected.content)
            assert any(e["id"] == id and e["kind"] == "success" for e in host.events())
        assert json.loads(actual.content)["cycle_end_date"] == "2025-02-28"


def test_retail_mutation_preserves_native_wire_types(tmp_path):
    import json

    from leanguard.tau import GuardedEnvironment
    from tau2.data_model.message import ToolCall

    adapter = TauAdapter("retail")
    reference = TauAdapter("retail")
    db = adapter.environment.tools.db
    order = next(o for o in db.orders.values() if o.status == "pending")
    user = db.users[order.user_id]
    args = {"order_id": order.order_id, "reason": "no longer needed"}
    expected = reference.environment.get_response(
        ToolCall(id="reference", name="cancel_pending_order", arguments=args)
    )
    with GuardHost(
        "retail",
        tmp_path / "journal.sqlite",
        adapter,
        principal="actor",
        session="conversation",
        clock=lambda: adapter.clock,
    ) as host:
        wrapper = GuardedEnvironment(host, confirmation=lambda proposal: True)
        assert host.execute("find_user_id_by_email", {"email": user.email})["allow"]
        assert host.execute("get_order_details", {"order_id": order.order_id})["allow"]
        actual = wrapper.get_response(
            ToolCall(id="cancel", name="cancel_pending_order", arguments=args)
        )
        assert not actual.error, actual.content
        assert json.loads(actual.content) == json.loads(expected.content)
        assert adapter.environment.get_db_hash() == reference.environment.get_db_hash()


def test_intent_evidence_cannot_replace_database_facts(adapter):
    adapter.user_evidence["user"] = {"membership": "gold"}
    with pytest.raises(ValueError, match="authoritative"):
        adapter.snapshot("calculate", {"expression": "1+1"}, "")


def test_environment_wrapper_intercepts_all_assistant_entrypoints(tmp_path):
    from leanguard.tau import GuardedEnvironment
    from tau2.data_model.message import ToolCall

    adapter = TauAdapter("retail")
    order = next(o for o in adapter.environment.tools.db.orders.values() if o.status == "pending")
    args = {"order_id": order.order_id, "reason": "no longer needed"}
    with GuardHost(
        "retail",
        tmp_path / "journal.sqlite",
        adapter,
        principal="actor",
        session="conversation",
        clock=lambda: adapter.clock,
    ) as host:
        wrapper = GuardedEnvironment(host)
        before = adapter.environment.tools.db.get_hash()
        for call in (wrapper.make_tool_call, wrapper.use_tool):
            with pytest.raises(PermissionError):
                call("cancel_pending_order", **args)
        response = wrapper.get_response(
            ToolCall(id="test-call", name="cancel_pending_order", arguments=args)
        )
        assert response.error
        assert adapter.environment.tools.db.get_hash() == before
