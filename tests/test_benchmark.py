from types import SimpleNamespace

import pytest

pytest.importorskip("tau2")

from leanguard.benchmark import (
    RecordingEnvironment,
    SimulatedConfirmation,
    aggregate,
    executed_trajectory,
    generation_usage,
    local_endpoint,
    observe_customer,
)
from tau2.data_model.message import AssistantMessage, ToolCall, ToolMessage, UserMessage


@pytest.mark.parametrize("url", ["https://example.com/v1", "http://192.168.1.2:8000/v1"])
def test_no_remote_model_endpoint(url):
    with pytest.raises(ValueError, match="localhost"):
        local_endpoint(url)


def test_local_endpoint():
    assert local_endpoint("http://127.0.0.1:18000/v1/") == "http://127.0.0.1:18000/v1"


def test_generation_usage_includes_rejected_attempts():
    records = [
        {
            "problem": "empty_response",
            "message": {
                "usage": {"prompt_tokens": 10, "completion_tokens": 8192},
                "raw_data": {"choices": [{"finish_reason": "length"}]},
            },
        },
        {
            "problem": None,
            "message": {
                "usage": {"prompt_tokens": 12, "completion_tokens": 30},
                "raw_data": {"choices": [{"finish_reason": "tool_calls"}]},
            },
        },
    ]
    usage = generation_usage(records)
    assert usage["generations"] == 2
    assert usage["completion_tokens"] == 8222
    assert usage["prompt_tokens"] == 22
    assert usage["finish_reasons"] == {"length": 1, "tool_calls": 1}


def test_only_undispatched_calls_removed():
    messages = [
        AssistantMessage(
            role="assistant",
            tool_calls=[
                ToolCall(id="blocked", name="cancel", arguments={}),
                ToolCall(id="executed", name="read", arguments={}),
            ],
        ),
        ToolMessage(id="blocked", role="tool", requestor="assistant", content="denied", error=True),
        ToolMessage(id="executed", role="tool", requestor="assistant", content="ok"),
    ]
    filtered = executed_trajectory(messages, {"blocked"})
    assert len(filtered) == 2
    assert [c.id for c in filtered[0].tool_calls] == ["executed"]
    assert len(messages[0].tool_calls) == 2


def test_keep_user_calls_and_failed_dispatched_calls():
    messages = [
        UserMessage(
            role="user",
            tool_calls=[ToolCall(id="same", name="toggle", arguments={}, requestor="user")],
        ),
        ToolMessage(id="same", role="tool", requestor="user", content="ok"),
        AssistantMessage(
            role="assistant", tool_calls=[ToolCall(id="failed", name="cancel", arguments={})]
        ),
        ToolMessage(
            id="failed", role="tool", requestor="assistant", content="partial failure", error=True
        ),
    ]
    assert executed_trajectory(messages, {"same"}) == messages


def test_remove_empty_assistant_message_after_block():
    messages = [
        AssistantMessage(
            role="assistant", tool_calls=[ToolCall(id="blocked", name="cancel", arguments={})]
        )
    ]
    assert executed_trajectory(messages, {"blocked"}) == []


def test_failed_episodes_stay_in_denominator():
    base = {"domain": "retail", "mode": "baseline"}
    report = aggregate(
        [
            {**base, "score": {"deterministic": {"reward": 1.0}, "local_combined_reward": 1.0}},
            {**base, "error": "endpoint unavailable"},
        ]
    )["retail/baseline"]
    assert report["episodes"] == 2
    assert report["scored"] == 1
    assert report["deterministic_success_rate_all_attempted"] == 0.5


def test_halted_batch_cannot_dispatch_a_tool(tmp_path):
    from leanguard.batch import ExperimentHalted

    def dispatch(message):
        pytest.fail("a halted batch must not dispatch")

    environment = RecordingEnvironment(
        SimpleNamespace(get_response=dispatch), tmp_path, stop_check=lambda: True
    )
    with pytest.raises(ExperimentHalted, match="before tool dispatch"):
        environment.get_response(ToolCall(id="x", name="read", arguments={}))


def test_customer_confirmation_requires_boolean(monkeypatch):
    response = SimpleNamespace(
        raise_for_status=lambda: None,
        json=lambda: {
            "choices": [{"finish_reason": "stop", "message": {"content": '{"approved": "true"}'}}]
        },
    )
    monkeypatch.setattr("leanguard.benchmark.httpx.post", lambda *a, **kw: response)
    confirmation = SimulatedConfirmation("http://localhost:18000/v1", "local", "scenario", 1)
    assert confirmation(SimpleNamespace(details={"action": "cancel"})) is False
    assert "error" in confirmation.records[0]


def test_identity_requires_literal_customer_origin():
    events = []
    host = SimpleNamespace(
        adapter=SimpleNamespace(
            domain="airline",
            environment=SimpleNamespace(
                tools=SimpleNamespace(db=SimpleNamespace(users={"alice_1": {}}))
            ),
            user_evidence={},
        ),
        customer=lambda: "",
        observe_trusted=lambda *args: events.append(args),
    )
    confirmation = SimpleNamespace(user_messages=[])
    observe_customer(host, confirmation, AssistantMessage(role="assistant", content="alice_1"))
    assert events == []
    assert confirmation.user_messages == []
    observe_customer(host, confirmation, UserMessage(role="user", content="My id is alice_10"))
    assert events == []
    observe_customer(host, confirmation, UserMessage(role="user", content="My id is alice_1."))
    assert events == [("identity", "alice_1")]
