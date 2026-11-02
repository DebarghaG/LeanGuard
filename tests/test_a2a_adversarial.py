"""Protocol-boundary matrices with independent expected lifecycle outcomes."""

import asyncio
import sqlite3
from copy import deepcopy

import pytest
import test_a2a
from leanguard import EngineError
from leanguard.a2a import A2AClient, Peer, PeerFacts
from leanguard.multiagent import Interaction
from test_a2a import message, task

setup = test_a2a.setup

PHASES = [
    "SUBMITTED",
    "WORKING",
    "INPUT_REQUIRED",
    "AUTH_REQUIRED",
    "COMPLETED",
    "CANCELED",
    "REJECTED",
    "FAILED",
]
TERMINAL = {"COMPLETED", "CANCELED", "REJECTED", "FAILED"}


@pytest.mark.parametrize("before", PHASES)
@pytest.mark.parametrize("after", PHASES)
async def test_all_native_task_transitions(setup, before, after):
    _, _, transport, client, _ = setup
    transport.frames = [task(before)]
    assert (await client.send("remote", message()))["outcome"] == "success"
    transport.frames = [task(after)]
    result = await client.get("remote", "task-1")
    expected = before not in TERMINAL or before == after
    assert result["outcome"] == ("success" if expected else "unknown")
    expected_phase = (after if expected else before).lower()
    assert client.task("remote", "task-1")["state"] == expected_phase


@pytest.mark.parametrize(
    "bad",
    [
        {},
        [],
        {"task": []},
        {"task": task()["task"], "message": {}},
        task("UNSPECIFIED"),
        task("NOT_A_STATE"),
        task(id=""),
        task(context=""),
        {
            "statusUpdate": {
                "taskId": "unseen",
                "contextId": "c",
                "status": {"state": "TASK_STATE_COMPLETED"},
            }
        },
        {"message": {"messageId": "m", "role": "ROLE_USER", "parts": []}},
    ],
)
async def test_malformed_or_unmatched_remote_evidence_is_never_success(setup, bad):
    host, _, transport, client, _ = setup
    transport.frames = [bad]
    result = await client.send("remote", message())
    assert result["allow"] and result["outcome"] == "unknown"
    assert host._status()["tasks"] == []
    assert not any(e["kind"] in {"identity", "confirmed"} for e in host.events())


async def test_message_replay_and_context_mismatch_do_not_dispatch(setup):
    _, _, transport, client, _ = setup
    await client.send("remote", message())
    replayed = await client.send("remote", message())
    assert not replayed["allow"] and "agents.message_replay" in replayed["reasons"]
    mismatch = await client.send(
        "remote", message(messageId="new", taskId="task-1", contextId="wrong")
    )
    assert not mismatch["allow"]
    assert len(transport.calls) == 1


async def test_task_identifiers_are_namespaced_by_peer(setup):
    _, _, _, client, _ = setup
    assert (await client.send("remote", message()))["outcome"] == "success"
    assert (await client.send("other", message()))["outcome"] == "success"
    assert client.task("remote", "task-1")["peer"] == "remote"
    assert client.task("other", "task-1")["peer"] == "other"


async def test_profile_cannot_rewrite_the_admitted_wire_payload(setup):
    _, agent, transport, _, _ = setup

    def profile(operation, envelope):
        envelope["payload"]["message"]["parts"] = [{"text": "substituted"}]
        return PeerFacts("document")

    client = A2AClient(agent, {"remote": Peer(transport, profile)})
    original = message()
    assert (await client.send("remote", original))["outcome"] == "success"
    assert transport.calls[0][1]["message"] == original


async def test_duplicate_status_updates_do_not_consume_additional_budget(setup):
    host, agent, transport, client, _ = setup
    update = {
        "statusUpdate": {
            "taskId": "task-1",
            "contextId": "context-1",
            "status": {"state": "TASK_STATE_WORKING"},
        }
    }
    transport.frames = [task(), *[deepcopy(update) for _ in range(64)]]
    assert len([r async for r in client.send_stream("remote", message())]) == 65
    usage = dict(host._status()["usages"])[agent.delegation]
    assert usage == {"calls": 1, "amount": 0}
    assert len(host._status()["responses"]) == 1


async def test_context_takeover_is_rejected_even_on_a_new_task(setup):
    host, _, transport, client, peer = setup
    await client.send("remote", message())
    stranger = host.grant(
        "stranger",
        workflow="other",
        actions=["a2a.send"],
        resources=["document"],
        peers=["remote"],
        calls=2,
        amount=0,
        expires=1000,
    )
    transport.frames = [task(id="new-task", context="context-1")]
    other = A2AClient(stranger, {"remote": peer})
    assert (await other.send("remote", message(messageId="stranger")))["outcome"] == "unknown"
    assert len(host._status()["tasks"]) == 1


@pytest.mark.parametrize("initial_payload", ["task", "message"])
@pytest.mark.parametrize("resource", ["document", "other"])
async def test_context_only_sends_require_the_original_resource(setup, initial_payload, resource):
    host, _, transport, _, _ = setup
    agent = host.grant(
        "multi-resource",
        workflow="multi-resource",
        actions=["a2a.send"],
        resources=["document", "other"],
        peers=["remote"],
        calls=10,
        amount=100,
        expires=1000,
    )
    current_resource = "document"
    peer = Peer(transport, lambda operation, envelope: PeerFacts(current_resource, amount=10))
    client = A2AClient(agent, {"remote": peer})
    if initial_payload == "message":
        transport.frames = [
            {
                "message": {
                    "messageId": "reply",
                    "role": "ROLE_AGENT",
                    "parts": [],
                    "contextId": "context-1",
                }
            }
        ]
    assert (await client.send("remote", message()))["outcome"] == "success"
    usage = dict(host._status()["usages"])[agent.delegation]
    current_resource = resource
    result = await client.send("remote", message(messageId="followup", contextId="context-1"))
    assert result["allow"] == (resource == "document")
    assert len(transport.calls) == (2 if result["allow"] else 1)
    if result["allow"]:
        assert result["outcome"] == "success"
    else:
        assert dict(host._status()["usages"])[agent.delegation] == usage
        # Exercise native admission directly, bypassing the Python client entirely.
        event = host._event("a2a.send", resource, scope=agent._scope("remote"))
        arguments = {
            "peer": "remote",
            "task_id": "",
            "context_id": "context-1",
            "payload": {"message": message(messageId="native", contextId="context-1")},
        }
        response = host._record(
            {"op": "admit", "event": event, "arguments": arguments, "facts": {}}
        )
        assert not response["decision"]["allow"]
        assert dict(host._status()["usages"])[agent.delegation] == usage


def task_delta(kind, id, context):
    payload = {"taskId": id, "contextId": context}
    if kind == "statusUpdate":
        payload["status"] = {"state": "TASK_STATE_COMPLETED"}
    else:
        payload["artifact"] = {"artifactId": "a", "parts": [{"text": "result"}]}
    return {kind: payload}


@pytest.mark.parametrize("kind", ["statusUpdate", "artifactUpdate"])
@pytest.mark.parametrize("shared_context", [False, True])
async def test_stream_cannot_update_another_owned_task(setup, kind, shared_context):
    host, _, transport, client, _ = setup
    transport.frames = [task(id="task-a", context="context-a")]
    assert (await client.send("remote", message()))["outcome"] == "success"
    context = "context-a" if shared_context else "context-b"
    transport.frames = [
        task(id="task-b", context=context),
        task_delta(kind, "task-a", "context-a"),
    ]
    results = [r async for r in client.send_stream("remote", message(messageId="stream"))]
    assert [r["outcome"] for r in results] == ["success", "unknown"]
    assert client.task("remote", "task-a")["state"] == "working"
    assert client.task("remote", "task-b")["state"] == "working"
    assert host.events()[-1]["kind"] == "stream_error"


@pytest.mark.parametrize(
    "wrong_frame",
    [
        task("COMPLETED", id="task-a", context="context-a"),
        task("COMPLETED", id="task-c", context="context-c"),
        task_delta("statusUpdate", "task-a", "context-a"),
        task_delta("artifactUpdate", "task-a", "context-a"),
        {
            "message": {
                "messageId": "m",
                "role": "ROLE_AGENT",
                "parts": [],
                "contextId": "context-b",
            }
        },
    ],
)
@pytest.mark.parametrize("reconcile", [False, True])
async def test_native_response_target_survives_recovery_and_cannot_be_substituted(
    setup, wrong_frame, reconcile
):
    host, agent, transport, client, _ = setup
    transport.frames = [task(id="task-a", context="context-a")]
    assert (await client.send("remote", message()))["outcome"] == "success"
    arguments = {
        "peer": "remote",
        "task_id": "",
        "context_id": "",
        "payload": {"message": message(messageId="native-stream")},
    }
    event, decision = host._begin_interaction(
        agent, Interaction("a2a.send", "remote", "document", arguments, {})
    )
    assert decision["allow"]
    try:
        first = task(id="task-b", context="context-b")
        host._update_interaction(event, first)
        host._finish_interaction(event, first, unknown=reconcile)
        if reconcile:
            host._release_interaction(event)
        with host._lock:
            host._recover()

        def receive(frame):
            if reconcile:
                host.reconcile(event["id"], frame)
            else:
                host._update_interaction(event, frame)

        with pytest.raises(EngineError, match="response target mismatch"):
            receive(wrong_frame)
        assert client.task("remote", "task-a")["state"] == "working"
        assert client.task("remote", "task-b")["state"] == "working"
        with pytest.raises(ValueError, match="inaccessible"):
            client.task("remote", "task-c")
        receive(task_delta("statusUpdate", "task-b", "context-b"))
        assert client.task("remote", "task-b")["state"] == "completed"
        assert len(transport.calls) == 1
    finally:
        host._release_interaction(event)


@pytest.mark.parametrize("context", ["", "context-1"])
async def test_native_message_response_cannot_be_reinterpreted_as_a_task(setup, context):
    host, agent, _, _, _ = setup
    arguments = {
        "peer": "remote",
        "task_id": "",
        "context_id": "",
        "payload": {"message": message()},
    }
    event, decision = host._begin_interaction(
        agent, Interaction("a2a.send", "remote", "document", arguments, {})
    )
    assert decision["allow"]
    try:
        reply = {"message": {"messageId": "m", "role": "ROLE_AGENT", "parts": []}}
        if context:
            reply["message"]["contextId"] = context
        host._update_interaction(event, reply)
        host._finish_interaction(event, reply)
        with host._lock:
            host._recover()
        with pytest.raises(EngineError, match="response target mismatch"):
            host._update_interaction(event, task(context=context or "context-1"))
        assert host._status()["tasks"] == []
    finally:
        host._release_interaction(event)


async def test_failed_first_receipt_write_does_not_leak_native_response_bindings(setup):
    host, agent, _, client, _ = setup
    arguments = {
        "peer": "remote",
        "task_id": "",
        "context_id": "",
        "payload": {"message": message()},
    }
    event, decision = host._begin_interaction(
        agent, Interaction("a2a.send", "remote", "document", arguments, {})
    )
    assert decision["allow"]
    try:
        host.db.execute("""CREATE TEMP TRIGGER refuse BEFORE INSERT ON journal
                        BEGIN SELECT RAISE(FAIL, 'injected receipt write failure'); END""")
        with pytest.raises(sqlite3.IntegrityError):
            host._update_interaction(event, task())
        assert host._status()["responses"] == []
        assert host._status()["tasks"] == []
        host.db.execute("DROP TRIGGER refuse")
        host._update_interaction(event, task())
        host._finish_interaction(event, task())
        assert client.task("remote", "task-1")["state"] == "working"
        assert len(host._status()["responses"]) == 1
    finally:
        host._release_interaction(event)


async def test_task_updates_after_revocation_remain_evidence_without_new_authority(setup):
    host, agent, transport, client, _ = setup

    async def stream(operation, payload):
        yield task()
        host.revoke(agent.delegation)
        yield {
            "statusUpdate": {
                "taskId": "task-1",
                "contextId": "context-1",
                "status": {"state": "TASK_STATE_COMPLETED"},
            }
        }

    transport.stream = stream
    # Revocation is prospective. It doesn't erase evidence for an already admitted operation.
    assert all([r["outcome"] == "success" async for r in client.send_stream("remote", message())])
    assert not (await client.send("remote", message(messageId="next")))["allow"]


async def test_async_cancellation_leaves_unknown_reservation_and_releases_close_fence(setup):
    host, _, transport, client, _ = setup
    entered = asyncio.Event()

    async def slow(operation, payload):
        entered.set()
        await asyncio.Event().wait()

    transport.request = slow
    operation = asyncio.create_task(client.send("remote", message()))
    await entered.wait()
    operation.cancel()
    with pytest.raises(asyncio.CancelledError):
        await operation
    assert host.events()[-1]["kind"] == "unknown"
    assert not host._pending_interactions


async def test_failed_admission_journal_write_does_not_spend_budget_or_send(setup):
    host, agent, transport, client, _ = setup
    host.db.execute("""CREATE TEMP TRIGGER refuse BEFORE INSERT ON journal
                    BEGIN SELECT RAISE(FAIL, 'injected storage failure'); END""")
    with pytest.raises(sqlite3.IntegrityError):
        await client.send("remote", message())
    assert transport.calls == []
    assert agent.delegation not in dict(host._status()["usages"])
    host.db.execute("DROP TRIGGER refuse")
    assert (await client.send("remote", message()))["outcome"] == "success"


async def test_native_scope_is_checked_against_the_actual_message(setup):
    host, agent, transport, _, _ = setup
    envelope = {
        "peer": "remote",
        "task_id": "",
        "context_id": "",
        "payload": {"message": message(taskId="someone-elses-task")},
    }
    event = host._event("a2a.send", "document", scope=agent._scope("remote"))
    response = host._record({"op": "admit", "event": event, "arguments": envelope, "facts": {}})
    assert not response["decision"]["allow"]
    assert "message scope mismatch" in response["decision"]["errors"]
    assert transport.calls == []


async def test_task_state_survives_native_recovery_without_resending(setup):
    host, _, transport, client, _ = setup
    await client.send("remote", message())
    version = host.engine.version
    host.engine.close()
    with pytest.raises(EngineError):
        host._record({"op": "observe", "event": host._event("user", "alice", kind="identity")})
    assert host.engine.version == version
    assert client.task("remote", "task-1")["state"] == "working"
    assert len(transport.calls) == 1


async def test_trusted_reconciliation_settles_unknown_without_resend_or_refund(setup):
    host, agent, transport, client, _ = setup
    request = transport.request

    async def lost_ack(operation, payload):
        transport.calls.append((operation, payload))
        raise ConnectionError("acknowledgement lost")

    transport.request = lost_ack
    result = await client.send("remote", message())
    assert result["outcome"] == "unknown"
    before = dict(host._status()["usages"])[agent.delegation]
    host.reconcile(result["request_id"], task())
    assert dict(host._status()["usages"])[agent.delegation] == before
    assert len(transport.calls) == 1
    assert host.events()[-1]["kind"] == "reconciled"
    transport.request = request
    assert (
        await client.send(
            "remote",
            message(
                messageId="continue",
                taskId="task-1",
                contextId="context-1",
            ),
        )
    )["outcome"] == "success"
    with pytest.raises(EngineError, match="already settled"):
        host.reconcile(result["request_id"], task())


async def test_reconciliation_does_not_restore_revoked_authority(setup):
    host, agent, transport, client, _ = setup

    async def lost_ack(operation, payload):
        raise ConnectionError("acknowledgement lost")

    transport.request = lost_ack
    result = await client.send("remote", message())
    host.revoke(agent.delegation)
    host.reconcile(result["request_id"], task("COMPLETED"))
    assert client.task("remote", "task-1")["state"] == "completed"
    assert not (await client.get("remote", "task-1"))["allow"]


async def test_reconciliation_cannot_substitute_an_existing_task_identity(setup):
    host, _, transport, client, _ = setup
    await client.send("remote", message())

    async def lost_ack(operation, payload):
        raise ConnectionError("acknowledgement lost")

    transport.request = lost_ack
    result = await client.get("remote", "task-1")
    with pytest.raises(EngineError, match="response task mismatch"):
        host.reconcile(result["request_id"], task(id="someone-else"))
    assert client.task("remote", "task-1")["state"] == "working"


async def test_inflight_sends_share_reserved_amount_before_any_response(setup):
    _, agent, first_transport, _, _ = setup
    entered, release = asyncio.Event(), asyncio.Event()

    async def slow(operation, payload):
        entered.set()
        await release.wait()
        return task()

    first_transport.request = slow
    second_transport = test_a2a.Transport()
    profile = lambda operation, envelope: PeerFacts("document", amount=60)
    client = A2AClient(
        agent,
        {
            "remote": Peer(first_transport, profile),
            "other": Peer(second_transport, profile),
        },
    )
    first = asyncio.create_task(client.send("remote", message()))
    await entered.wait()
    try:
        assert not (await client.send("other", message()))["allow"]
        assert second_transport.calls == []
    finally:
        release.set()
    assert (await first)["outcome"] == "success"


@pytest.mark.parametrize("line_end", [b"\n", b"\r\n", b"\r"])
async def test_sse_accepts_multiline_data_keepalives_and_all_line_endings(line_end):
    httpx = pytest.importorskip("httpx")
    from leanguard.a2a import A2AHTTPTransport

    wire = line_end.join(
        [
            b"\xef\xbb\xbf: keepalive",
            b"event: update",
            b'data: {"task":',
            b'data: {"id":"t","contextId":"c","status":{"state":"TASK_STATE_WORKING"}}}',
            b"",
            b"",
        ]
    )

    def serve(request):
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=wire)

    async with httpx.AsyncClient(transport=httpx.MockTransport(serve)) as http:
        transport = A2AHTTPTransport("https://agent.example", client=http)
        frames = [r async for r in transport.stream("a2a.send", {"message": message()})]
    assert frames == [task(id="t", context="c")]


@pytest.mark.parametrize(
    "wire",
    [
        b'data: {"task":{},"task":{}}\n\n',
        b'data: {"task":{}}',
        b'data: {"task":{}}\n',
        b":" + b"x" * (8 * 1024 * 1024 + 1),
        b":" + b"x" * (8 * 1024 * 1024 + 1) + b"\n\n",
    ],
)
async def test_sse_rejects_duplicate_json_fields_incomplete_frames_and_oversized_comments(wire):
    httpx = pytest.importorskip("httpx")
    from leanguard.a2a import A2AHTTPTransport

    def serve(request):
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=wire)

    async with httpx.AsyncClient(transport=httpx.MockTransport(serve)) as http:
        transport = A2AHTTPTransport("https://agent.example", client=http)
        with pytest.raises(ValueError):
            _ = [r async for r in transport.stream("a2a.send", {"message": message()})]


@pytest.mark.parametrize("task_id", ["", ".", ".."])
async def test_transport_cannot_turn_task_identifiers_into_relative_routes(task_id):
    httpx = pytest.importorskip("httpx")
    from leanguard.a2a import A2AHTTPTransport

    def forbidden(request):
        pytest.fail("invalid path must not reach the network")

    async with httpx.AsyncClient(transport=httpx.MockTransport(forbidden)) as http:
        transport = A2AHTTPTransport("https://agent.example", client=http)
        with pytest.raises(ValueError):
            await transport.request("a2a.get", {"id": task_id})
