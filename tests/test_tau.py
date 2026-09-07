import pytest

pytest.importorskip("tau2")

from leanguard import GuardHost
from leanguard.tau import TauAdapter, normalize, scaled


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


@pytest.mark.parametrize(
    "reason,allowed",
    [
        ("I have a health problem. I want Economy, not Basic Economy.", True),
        ("I understand not changing the destination. Please cancel due to health reasons.", True),
        ("It is not a health reason.", False),
        ("I want to cancel due to a change of plan.", False),
    ],
)
def test_customer_reason_reaches_native_cancellation_rule(tmp_path, reason, allowed):
    from types import SimpleNamespace

    from leanguard.benchmark import observe_customer
    from tau2.data_model.message import UserMessage

    adapter = TauAdapter("airline")
    reservation = adapter.environment.tools.db.reservations["VA5SGQ"]
    assert reservation.insurance == "yes"
    with GuardHost(
        "airline",
        tmp_path / "journal.sqlite",
        adapter,
        principal="actor",
        session="conversation",
        clock=lambda: adapter.clock,
    ) as host:
        customer_ui = SimpleNamespace(user_messages=[])
        observe_customer(
            host,
            customer_ui,
            UserMessage(role="user", content=f"My ID is {reservation.user_id}. {reason}"),
        )
        args = {"reservation_id": reservation.reservation_id}
        assert host.execute("get_reservation_details", args)["allow"]
        observe_customer(host, customer_ui, UserMessage(role="user", content="Yes, please cancel."))
        proposal = host.prepare("cancel_reservation", args)
        host.confirm(proposal.id, True)
        before = adapter.environment.get_db_hash()
        result = host.execute("cancel_reservation", args, proposal_id=proposal.id)
        assert result["allow"] is allowed, result
        if allowed:
            assert result["outcome"] == "success"
            assert reservation.status == "cancelled"
        else:
            assert "airline.cancel" in result["reasons"]
            assert adapter.environment.get_db_hash() == before


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


def test_exact_unit_conversion():
    assert normalize({"price": 12.34, "gb_amount": 1.5}) == {
        "price": 1234,
        "gb_amount": 1.5,
        "gb_amount_milli": 1500,
    }


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


def test_plain_date_values_are_json_data():
    import json
    from datetime import UTC, date, datetime

    from leanguard.tau import jsonable

    value = jsonable(
        {
            "date": date(2025, 2, 28),
            "nested": [datetime(2025, 2, 25, 12, 8, tzinfo=UTC)],
        }
    )
    assert json.loads(json.dumps(value)) == {
        "date": "2025-02-28",
        "nested": ["2025-02-25T12:08:00+00:00"],
    }


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
    with pytest.raises(ValueError):
        scaled(0.001, 100)
    with pytest.raises(ValueError):
        scaled(float("nan"), 100)


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
