from types import SimpleNamespace

import pytest

pytest.importorskip("tau2")

from leanguard.benchmark import llm_args
from leanguard.rollout import (
    BoundedUser,
    ReliableAgent,
    customer_reason,
    denial_feedback,
    observe_simulator_travel,
    protocol_problem,
    recovery_summary,
)
from tau2.agent.llm_agent import LLMAgent
from tau2.data_model.message import AssistantMessage, ToolCall, ToolMessage, UserMessage


def test_generic_does_not_leak_rule_or_evidence():
    decision = {"allow": False, "reasons": ["airline.identity"], "evidence": ["secret"]}
    generic = denial_feedback(decision, False)
    detailed = denial_feedback(decision, True)
    assert generic["dispatched"] is False
    assert "violations" not in generic
    assert detailed["violations"][0]["category"] == "prerequisite"
    assert "secret" not in str(detailed)


def test_recovery_counts_incidents_separately_from_repeated_denials():
    calls = [
        {"id": "a", "action": "read", "arguments": {}, "result": {"allow": False}},
        {"id": "b", "action": "read", "arguments": {}, "result": {"allow": False}},
        {
            "id": "c",
            "action": "read",
            "arguments": {},
            "result": {"allow": True, "outcome": "success"},
        },
    ]
    messages = [
        AssistantMessage(
            role="assistant", tool_calls=[ToolCall(id=c["id"], name="read", arguments={})]
        )
        for c in calls
    ]
    result = recovery_summary(calls, messages)
    assert len(result["incidents"]) == 1
    assert result["incidents"][0]["blocked_attempts"] == 2
    assert result["same_call_recoveries"] == 1
    assert result["admission_recovery_at_turns"] == {"1": 0, "3": 1, "5": 1}
    messages.insert(1, ToolMessage(id="a", role="tool", requestor="assistant", content="denied"))
    assert recovery_summary(calls, messages)["same_call_recoveries"] == 1


def test_reason_persists_across_incidental_confirmation():
    assert customer_reason("Please cancel due to health reasons.") == "health"
    assert customer_reason("Yes please cancel it", "health") == "health"
    assert customer_reason("It is not a health reason", "health") == ""
    assert customer_reason("My reason is a change of plan", "health") == "change of plan"


def test_protocol_defects_are_not_tool_actions():
    call = ToolCall(id="one", name="read", arguments={})
    assert protocol_problem(AssistantMessage(role="assistant", content=" ")) == "empty_response"
    assert (
        protocol_problem(AssistantMessage(role="assistant", content="Done", tool_calls=[call]))
        == "mixed_text_and_tool_call"
    )
    assert (
        protocol_problem(AssistantMessage(role="assistant", tool_calls=[call, call]))
        == "multiple_tool_calls"
    )
    assert protocol_problem(AssistantMessage(role="assistant", tool_calls=[call])) is None


def test_retry_does_not_duplicate_input_or_promote_reasoning(monkeypatch):
    attempts = []

    def generate(self, message, state):
        attempts.append(self.llm_args["extra_body"]["chat_template_kwargs"]["enable_thinking"])
        state.messages.append(message)
        reply = AssistantMessage(role="assistant", content=None if len(attempts) == 1 else "Hello")
        state.messages.append(reply)
        return reply, state

    monkeypatch.setattr(LLMAgent, "generate_next_message", generate)
    agent = ReliableAgent(
        tools=[],
        domain_policy="",
        llm="local",
        llm_args=llm_args("http://localhost/v1", thinking=True),
    )
    state = agent.get_init_state()
    reply, after = agent.generate_next_message(UserMessage(role="user", content="Hi"), state)
    assert reply.content == "Hello"
    assert attempts == [True, False]
    assert state.messages == []
    assert len(after.messages) == 2
    assert len(agent.generation_records) == 2
    assert agent.llm_args["extra_body"]["chat_template_kwargs"]["enable_thinking"] is True


def test_retry_budget_exhausted_remains_failure(monkeypatch):
    monkeypatch.setattr(
        LLMAgent,
        "generate_next_message",
        lambda self, m, s: (AssistantMessage(role="assistant"), s),
    )
    agent = ReliableAgent(
        tools=[],
        domain_policy="",
        llm="local",
        llm_args=llm_args("http://localhost/v1", thinking=True),
    )
    with pytest.raises(ValueError, match="budget exhausted"):
        agent.generate_next_message(UserMessage(role="user", content="Hi"), agent.get_init_state())
    assert len(agent.generation_records) == 2


def test_completed_handoff_is_observed_not_invented():
    user = BoundedUser(llm="local", instructions="", tools=[], handoff=lambda: True)
    reply, state = user.generate_next_message(
        AssistantMessage(role="assistant", content="Transferring you."), user.get_init_state()
    )
    assert reply.content == "###TRANSFER###"
    assert len(state.messages) == 2
    assert user.controls[0]["kind"] == "completed_tool_handoff"


def test_user_tool_burst_yields_actual_observations():
    user = BoundedUser(llm="local", instructions="", tools=[], max_tool_burst=1)
    state = user.get_init_state()
    state.messages = [
        UserMessage(
            role="user",
            tool_calls=[ToolCall(id="c", name="run_speed_test", arguments={}, requestor="user")],
        )
    ]
    reply, _ = user.generate_next_message(
        ToolMessage(id="c", role="tool", content="No connection", requestor="user"), state
    )
    assert not reply.tool_calls
    assert "No connection" in reply.content
    assert user.controls[0]["kind"] == "tool_burst_yield"


def test_travel_sensor_binds_only_matching_owned_phone():
    events = []
    world = SimpleNamespace(is_abroad=True, phone_number="555")
    db = SimpleNamespace(
        customers=[SimpleNamespace(customer_id="c", line_ids=["l", "other"])],
        lines=[
            SimpleNamespace(line_id="l", phone_number="555"),
            SimpleNamespace(line_id="other", phone_number="666"),
        ],
    )
    host = SimpleNamespace(
        adapter=SimpleNamespace(
            domain="telecom",
            environment=SimpleNamespace(
                tools=SimpleNamespace(db=db),
                user_tools=SimpleNamespace(db=SimpleNamespace(surroundings=world)),
            ),
        ),
        customer=lambda: "c",
        events=lambda: events,
        observe_trusted=lambda kind, resource, **kw: events.append(
            {"kind": kind, "resource": resource}
        ),
    )
    observe_simulator_travel(host)
    observe_simulator_travel(host)
    assert events == [{"kind": "travelling", "resource": "l"}]
    world.is_abroad = False
    with pytest.raises(ValueError, match="fresh session"):
        observe_simulator_travel(host)
