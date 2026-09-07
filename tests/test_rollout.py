import os
from types import SimpleNamespace

import pytest

pytest.importorskip("tau2")

from leanguard.batch import ExperimentHalted
from leanguard.benchmark import MODEL, llm_args
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


@pytest.mark.parametrize(
    "content,expected",
    [
        ("I have a health problem. I want Economy, not Basic Economy.", "health"),
        ("I don't have a health problem.", ""),
        ("My health is not the reason for cancellation.", ""),
        ("It is not due to health but a change of plan.", ""),
        ("It could be health or weather.", ""),
        ("The weatherproof bag is missing.", ""),
    ],
)
def test_reason_negation_does_not_cross_sentences(content, expected):
    assert customer_reason(content) == expected


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
        assert len(state.system_messages) == 1
        assert "ORIGINAL_POLICY" in state.system_messages[0].content
        if len(attempts) > 1:
            assert "previous generation" in state.system_messages[0].content
        state.messages.append(message)
        reply = AssistantMessage(role="assistant", content=None if len(attempts) == 1 else "Hello")
        state.messages.append(reply)
        return reply, state

    monkeypatch.setattr(LLMAgent, "generate_next_message", generate)
    agent = ReliableAgent(
        tools=[],
        domain_policy="ORIGINAL_POLICY",
        llm="local",
        llm_args=llm_args("http://localhost/v1", thinking=True),
    )
    state = agent.get_init_state()
    reply, after = agent.generate_next_message(UserMessage(role="user", content="Hi"), state)
    assert reply.content == "Hello"
    assert attempts == [True, False]
    assert state.messages == []
    assert after.system_messages == state.system_messages
    assert "previous generation" not in state.system_messages[0].content
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


@pytest.mark.skipif(os.getenv("LEANGUARD_LIVE_TESTS") != "1", reason="requires local Qwen server")
@pytest.mark.parametrize("incoming_kind", ["user", "tool"])
@pytest.mark.parametrize("defect", ["empty", "mixed", "multiple"])
def test_live_qwen_retry(monkeypatch, incoming_kind, defect):
    """Inject one invalid response, then exercise the real server and chat template."""
    from tau2.agent import llm_agent
    from tau2.environment.tool import as_tool

    def read_note() -> str:
        """Read a demonstration note."""
        pytest.fail("a request-format regression must not dispatch tools")

    agent = ReliableAgent(
        tools=[as_tool(read_note)],
        domain_policy="Read notes only when asked. Briefly report a received note.",
        llm="openai/" + MODEL,
        llm_args=llm_args("http://127.0.0.1:18000/v1", thinking=True, max_tokens=512, timeout=120),
    )
    state = agent.get_init_state()
    incoming = UserMessage(role="user", content="Say hello. No tool is needed.")
    if incoming_kind == "tool":
        state.messages = [
            UserMessage(role="user", content="Read the note and report its contents."),
            AssistantMessage(
                role="assistant", tool_calls=[ToolCall(id="prior", name="read_note", arguments={})]
            ),
        ]
        incoming = ToolMessage(
            role="tool", requestor="assistant", id="prior", content="The note says hello."
        )
    original = state.model_dump(mode="json")
    actual_generate = llm_agent.generate
    attempts = []

    def generate(**kwargs):
        assert sum(m.role == "system" for m in kwargs["messages"]) == 1
        attempts.append(kwargs["extra_body"]["chat_template_kwargs"]["enable_thinking"])
        if len(attempts) == 1:
            call = ToolCall(id="undispatched", name="read_note", arguments={})
            return AssistantMessage(
                role="assistant",
                content="Reading now" if defect == "mixed" else None,
                tool_calls=None
                if defect == "empty"
                else [call] * (2 if defect == "multiple" else 1),
            )
        return actual_generate(**kwargs)

    monkeypatch.setattr(llm_agent, "generate", generate)
    reply, after = agent.generate_next_message(incoming, state)
    assert protocol_problem(reply) is None
    assert attempts == [True, False]
    assert state.model_dump(mode="json") == original
    assert after.system_messages == state.system_messages
    assert len(after.messages) == len(state.messages) + 2


def test_completed_handoff_is_observed_not_invented():
    user = BoundedUser(llm="local", instructions="", tools=[], handoff=lambda: True)
    reply, state = user.generate_next_message(
        AssistantMessage(role="assistant", content="Transferring you."), user.get_init_state()
    )
    assert reply.content == "###TRANSFER###"
    assert len(state.messages) == 2
    assert user.controls[0]["kind"] == "completed_tool_handoff"


def test_halted_batch_does_not_issue_more_generations():
    agent = ReliableAgent(tools=[], domain_policy="", llm="local", stop_check=lambda: True)
    with pytest.raises(ExperimentHalted):
        agent.generate_next_message(UserMessage(role="user", content="Hi"), agent.get_init_state())
    assert agent.generation_records == []
    user = BoundedUser(llm="local", instructions="", tools=[], stop_check=lambda: True)
    with pytest.raises(ExperimentHalted):
        user.generate_next_message(
            AssistantMessage(role="assistant", content="Hi"), user.get_init_state()
        )
    assert user.generation_records == []


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
