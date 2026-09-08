import io
import json
from copy import deepcopy

import pytest

pytest.importorskip("tau2")

from jsonschema import Draft202012Validator
from leanguard.engine import Engine
from leanguard.tau import TauAdapter
from leanguard.trajectory_data import messages, signature
from leanguard.trajectory_replay import Observations, classify, paired_responses, replay, translated


@pytest.fixture(scope="module")
def retail():
    adapter = TauAdapter("retail")
    schemas = {a: Draft202012Validator(s["parameters"]) for a, s in adapter.tool_schemas().items()}
    mutations = {a for a in schemas if adapter.mutating(a)}
    with Engine("retail") as engine:
        yield engine, schemas, mutations


def tool(name, arguments, id=None):
    return {"id": id, "function": {"name": name, "arguments": arguments}}


def record(raw):
    return {
        "id": "test",
        "dataset": "test",
        "domain": "retail",
        "model": "recorded",
        "version": "test",
        "reward": 1,
        "messages": messages(raw),
    }


def check(raw, retail):
    journal = io.StringIO()
    calls, summary = replay(record(raw), *retail, journal)
    return calls, summary, [json.loads(s) for s in journal.getvalue().splitlines()]


def test_native_temporal_replay_no_future_facts_or_invented_approval(retail):
    order = {"order_id": "o", "user_id": "alice", "items": [], "status": "pending"}
    address = {
        "order_id": "o",
        "address1": "1 Main",
        "address2": "",
        "city": "X",
        "state": "CA",
        "country": "USA",
        "zip": "12345",
    }
    raw = [
        {"role": "assistant", "tool_calls": [tool("find_user_id_by_email", {"email": "a@b.co"})]},
        {"role": "tool", "content": "alice"},
        {"role": "assistant", "tool_calls": [tool("get_order_details", {"order_id": "o"})]},
        {"role": "tool", "content": json.dumps(order)},
        {"role": "user", "content": "Yes, I confirm everything!"},
        {"role": "assistant", "tool_calls": [tool("modify_pending_order_address", address)]},
        {"role": "tool", "content": json.dumps(order)},
        {"role": "assistant", "tool_calls": [tool("modify_pending_order_address", address)]},
        {"role": "tool", "content": json.dumps(order)},
    ]
    calls, _, journal = check(raw, retail)
    assert calls[0]["allow"]
    assert "order" not in journal[1]["command"]["facts"]
    assert calls[1]["category"] == "insufficient_evidence"
    assert calls[2]["rules"]["retail.status_observed"]
    assert calls[2]["rules"]["retail.identity"]
    assert calls[2]["rules"]["retail.modify_once"]
    assert calls[2]["unavailable_rules"] == {
        "retail.confirmation": "no_trusted_bound_approval_in_dataset"
    }
    assert not calls[3]["rules"]["retail.modify_once"]
    assert calls[3]["recorded_policy_failures"] == ["retail.modify_once"]
    assert all(e["kind"] != "confirmed" for j in journal for e in j["command"]["history"])


def test_serial_batch_only_exposes_completed_earlier_call(retail):
    raw = [
        {
            "role": "assistant",
            "tool_calls": [
                tool("find_user_id_by_email", {"email": "a@b.co"}, "lookup"),
                tool("get_user_details", {"user_id": "alice"}, "profile"),
            ],
        },
        {"role": "tool", "tool_call_id": "lookup", "content": "alice"},
        {
            "role": "tool",
            "tool_call_id": "profile",
            "content": json.dumps(
                {
                    "user_id": "alice",
                    "payment_methods": {"gift": {"source": "gift_card", "balance": 20}},
                }
            ),
        },
    ]
    calls, _, journal = check(raw, retail)
    assert all(c["allow"] for c in calls)
    assert journal[0]["command"]["history"] == []
    assert journal[1]["command"]["facts"]["user"] == {}
    assert calls[1]["rules"]["host.no_overlap"]


def test_recorded_code_is_never_executed_or_accepted_as_facts(retail, tmp_path):
    marker = tmp_path / "executed"
    expression = f"__import__('pathlib').Path({str(marker)!r}).touch()"
    raw = [
        {"role": "assistant", "tool_calls": [tool("code_evaluation", {"expression": expression})]},
        {"role": "tool", "content": '{"user_id":"alice","payment_methods":{}}'},
        {"role": "assistant", "tool_calls": [tool("calculate", {"expression": expression})]},
        {"role": "tool", "content": "0"},
    ]
    calls, _, journal = check(raw, retail)
    assert calls[0]["category"] == "unsupported_tool"
    assert not calls[0]["native_allow"]
    assert journal[1]["command"]["facts"]["user"] == {}
    assert not marker.exists()


def test_missing_results_and_conflicting_ids_do_not_get_guessed():
    calls = messages(
        [
            {
                "role": "assistant",
                "tool_calls": [
                    tool("get_user_details", {"user_id": "a"}, "a"),
                    tool("get_user_details", {"user_id": "b"}, "b"),
                ],
            }
        ]
    )[0]["calls"]
    responses = messages(
        [
            {"role": "tool", "tool_call_id": "wrong", "content": "a"},
            {"role": "tool", "tool_call_id": "b", "content": "b"},
        ]
    )
    pairs, orphans = paired_responses(calls, responses)
    assert pairs[0][0] is None
    assert pairs[1][1] == "call_id"
    assert orphans == 1
    pairs, _ = paired_responses(calls, messages([{"role": "tool", "content": "ambiguous"}]))
    assert all(r is None for r, _ in pairs)


def test_user_tool_cannot_promote_itself_to_assistant_or_supply_identity(retail):
    call = tool("find_user_id_by_email", {"email": "a@b.co"})
    call["requestor"] = "assistant"
    calls, summary, _ = check(
        [
            {"role": "user", "tool_calls": [call]},
            {"role": "tool", "content": "alice"},
            {"role": "assistant", "tool_calls": [tool("get_user_details", {"user_id": "alice"})]},
            {"role": "tool", "content": "{}"},
        ],
        retail,
    )
    assert len(calls) == 1
    assert not calls[0]["rules"]["retail.identity"]
    assert summary["diagnostics"]["requestor_role_conflict"] == 1


def test_unobserved_collections_and_postmutation_payment_state_remain_unknown():
    state = Observations("telecom")
    state.customer = "c"
    state.objects["users"]["c"] = {"line_ids": ["l"], "bill_ids": ["b", "b2"]}
    state.objects["bills"]["b"] = {"bill_id": "b", "status": "Paid"}
    facts, _, _ = state.facts("resume_line", {"customer_id": "c", "line_id": "l"})
    assert "bills" not in facts
    state = Observations("retail")
    state.objects["users"]["a"] = {"payment_methods": {"gift": {"balance": 20}}}
    state.invalidate("modify_pending_order_payment", {"order_id": "o"}, True, True)
    assert "payment_methods" not in state.objects["users"]["a"]


def test_aliases_are_narrow_and_prefix_identity_preserves_errors():
    dataset = "fuvty--tau-bench-synthetic"
    assert (
        translated("retail", "find_user_by_contact", {"phone": "123"}, dataset)[0]
        == "find_user_by_contact"
    )
    assert (
        translated("retail", "find_user_by_contact", {"email": "a@b"}, dataset)[0]
        == "find_user_id_by_email"
    )
    assert translated(
        "airline", "cancel_order", {"order_id": "r", "reason": "health"}, dataset
    ) == ("cancel_reservation", {"reservation_id": "r"})
    m = messages([{"role": "tool", "content": "same"}])[0]
    changed = deepcopy(m)
    changed["error"] = True
    assert signature(m) != signature(changed)


@pytest.mark.parametrize("customer", ["emma_kim_9957", "timothy_allen_d7d300"])
def test_airline_identity_is_available_before_first_reservation_lookup(customer):
    state = Observations("airline")
    state.user_message(f"My user ID is {customer} and my reservation is EHGLP3.")
    facts, _, identity = state.facts("get_reservation_details", {"reservation_id": "EHGLP3"})
    assert identity
    assert facts["customer_id"] == customer
    assert "reservation" not in facts
    state = Observations("airline")
    state.user_message("emma_kim_9957 and daiki_muller_1116 both have bookings.")
    assert state.customer == ""
    state = Observations("airline")
    state.user_message("Please use my gift_card_123 for the payment.")
    assert state.customer == ""
    assert not state.supplied("gift_card_123")
    state.user_message("The literal words are not_a_user_id.")
    assert state.customer == ""
    state.user_message("emma_kim_9957 and timothy_allen_d7d300 both have bookings.")
    assert state.customer == ""


def test_business_check_errors_are_not_misreported_as_absent_data():
    response = {
        "decision": {
            "allow": False,
            "reasons": ["airline.booking"],
            "errors": ["airline.booking/booking_constraints: insufficient seats"],
        }
    }
    verdict = classify(response, {}, True, [])
    assert verdict["category"] == "recorded_policy_failure"
    assert verdict["recorded_policy_failures"] == ["airline.booking"]


def test_incomplete_outcomes_and_unsupported_evidence_remain_unavailable():
    response = {
        "decision": {
            "allow": False,
            "reasons": ["host.no_overlap", "airline.observed"],
            "errors": [],
        }
    }
    verdict = classify(response, {}, True, [], "cancel_reservation", True)
    assert verdict["category"] == "insufficient_evidence"
    assert not verdict["recorded_policy_failures"]


def test_saved_native_audits_cover_all_calls_and_detect_tampered_export(tmp_path):
    from leanguard.trajectory_replay import run
    from leanguard.trajectory_verify import verify

    raw = record(
        [
            {"role": "assistant", "tool_calls": [tool("calculate", {"expression": "2+2"})]},
            {"role": "tool", "content": "4"},
        ]
    )
    (tmp_path / "normalized.jsonl").write_text(json.dumps(raw) + "\n")
    (tmp_path / "coverage.json").write_text('{"test":{"rollout_rows":1}}')
    (tmp_path / "downloads.json").write_text("[]")
    output = tmp_path / "replay"
    run(tmp_path, output)
    verified = verify(tmp_path, output)
    assert verified["assistant_calls"] == verified["trajectories"] == 1
    path = output / "calls.jsonl"
    call = json.loads(path.read_text())
    call["allow"] = False
    path.write_text(json.dumps(call) + "\n")
    with pytest.raises(ValueError, match="classification differs"):
        verify(tmp_path, output)


def test_failed_mutator_cannot_leave_stale_object_as_authoritative(retail):
    order = {"order_id": "o", "user_id": "alice", "items": [], "status": "pending"}
    _, _, audits = check(
        [
            {"role": "assistant", "tool_calls": [tool("get_order_details", {"order_id": "o"})]},
            {"role": "tool", "content": json.dumps(order)},
            {
                "role": "assistant",
                "tool_calls": [
                    tool("cancel_pending_order", {"order_id": "o", "reason": "no longer needed"})
                ],
            },
            {"role": "tool", "content": "Error: disconnected after starting mutation"},
            {"role": "assistant", "tool_calls": [tool("get_order_details", {"order_id": "o"})]},
            {"role": "tool", "content": json.dumps(order)},
        ],
        retail,
    )
    assert "order" in audits[1]["command"]["facts"]
    assert "order" not in audits[2]["command"]["facts"]
