import asyncio

import pytest

grpc = pytest.importorskip("grpc")
json_format = pytest.importorskip("google.protobuf.json_format")
pytest.importorskip("google.api.annotations_pb2")

from leanguard.a2a import A2AGRPCTransport
from leanguard.a2a_grpc import a2a_pb2, a2a_pb2_grpc

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")


def task(state="WORKING", id="task-1", context="context-1"):
    return {"task": {"id": id, "contextId": context, "status": {"state": "TASK_STATE_" + state}}}


def message(**extra):
    return {"messageId": "message-1", "role": "ROLE_USER", "parts": [{"text": "Research"}], **extra}


def status_update(state="COMPLETED"):
    return {
        "statusUpdate": {
            "taskId": "task-1",
            "contextId": "context-1",
            "status": {"state": "TASK_STATE_" + state},
        }
    }


class Servicer(a2a_pb2_grpc.A2AServiceServicer):
    def __init__(self):
        self.requests = []
        self.frames = [task()]
        self.error = None
        self.delay = 0
        self.hold = False
        self.cancelled = asyncio.Event()

    async def _admit(self, name, request, context):
        self.requests.append((name, request))
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.error is not None:
            await context.abort(self.error, "refused")

    async def SendMessage(self, request, context):
        await self._admit("SendMessage", request, context)
        return json_format.ParseDict(self.frames[0], a2a_pb2.SendMessageResponse())

    async def GetTask(self, request, context):
        await self._admit("GetTask", request, context)
        return json_format.ParseDict(self.frames[0]["task"], a2a_pb2.Task())

    async def CancelTask(self, request, context):
        await self._admit("CancelTask", request, context)
        return json_format.ParseDict(self.frames[0]["task"], a2a_pb2.Task())

    async def SendStreamingMessage(self, request, context):
        await self._admit("SendStreamingMessage", request, context)
        for frame in self.frames:
            yield json_format.ParseDict(frame, a2a_pb2.StreamResponse())

    async def SubscribeToTask(self, request, context):
        await self._admit("SubscribeToTask", request, context)
        for frame in self.frames:
            yield json_format.ParseDict(frame, a2a_pb2.StreamResponse())
        if self.hold:
            try:
                await asyncio.sleep(30)
            except asyncio.CancelledError:
                self.cancelled.set()
                raise


@pytest.fixture
async def peer():
    servicer = Servicer()
    server = grpc.aio.server()
    a2a_pb2_grpc.add_A2AServiceServicer_to_server(servicer, server)
    port = server.add_insecure_port("127.0.0.1:0")
    await server.start()
    try:
        yield servicer, f"127.0.0.1:{port}"
    finally:
        await server.stop(None)


async def test_grpc_unary_calls_return_the_http_frame_shapes(peer):
    servicer, target = peer
    async with A2AGRPCTransport(target, insecure=True) as transport:
        assert await transport.request("a2a.send", {"message": message()}) == task()
        assert await transport.request("a2a.get", {"id": "task-1"}) == task()
        assert await transport.request("a2a.cancel", {"id": "task-1"}) == task()
    names = [name for name, _ in servicer.requests]
    assert names == ["SendMessage", "GetTask", "CancelTask"]
    sent = servicer.requests[0][1].message
    assert sent.message_id == "message-1"
    assert sent.role == a2a_pb2.ROLE_USER
    assert [part.text for part in sent.parts] == ["Research"]
    assert servicer.requests[1][1].id == "task-1"
    assert servicer.requests[2][1].id == "task-1"


async def test_grpc_send_returns_direct_agent_messages(peer):
    servicer, target = peer
    reply = {"message": {"messageId": "m-2", "role": "ROLE_AGENT", "parts": [{"text": "Done"}]}}
    servicer.frames = [reply]
    async with A2AGRPCTransport(target, insecure=True) as transport:
        assert await transport.request("a2a.send", {"message": message()}) == reply


async def test_grpc_streams_yield_each_response_as_a_frame(peer):
    servicer, target = peer
    servicer.frames = [task(), status_update()]
    async with A2AGRPCTransport(target, insecure=True) as transport:
        frames = [f async for f in transport.stream("a2a.send", {"message": message()})]
        assert frames == [task(), status_update()]
        frames = [f async for f in transport.stream("a2a.subscribe", {"id": "task-1"})]
        assert frames == [task(), status_update()]
    names = [name for name, _ in servicer.requests]
    assert names == ["SendStreamingMessage", "SubscribeToTask"]
    assert servicer.requests[1][1].id == "task-1"


async def test_grpc_stream_close_cancels_the_call(peer):
    servicer, target = peer
    servicer.hold = True
    async with A2AGRPCTransport(target, insecure=True) as transport:
        stream = transport.stream("a2a.subscribe", {"id": "task-1"})
        assert await stream.__anext__() == task()
        await stream.aclose()
        await asyncio.wait_for(servicer.cancelled.wait(), 5)


async def test_grpc_rejects_oversized_responses(peer):
    servicer, target = peer
    big = dict(task())
    big["task"] = {
        **big["task"],
        "artifacts": [{"artifactId": "a", "parts": [{"text": "x" * (9 << 20)}]}],
    }
    servicer.frames = [big]
    async with A2AGRPCTransport(target, insecure=True) as transport:
        with pytest.raises(grpc.aio.AioRpcError) as failure:
            await transport.request("a2a.get", {"id": "task-1"})
        assert failure.value.code() == grpc.StatusCode.RESOURCE_EXHAUSTED
        with pytest.raises(grpc.aio.AioRpcError):
            [f async for f in transport.stream("a2a.subscribe", {"id": "task-1"})]


async def test_grpc_errors_propagate_without_retry(peer):
    servicer, target = peer
    servicer.error = grpc.StatusCode.UNAVAILABLE
    async with A2AGRPCTransport(target, insecure=True) as transport:
        with pytest.raises(grpc.aio.AioRpcError) as failure:
            await transport.request("a2a.send", {"message": message()})
        assert failure.value.code() == grpc.StatusCode.UNAVAILABLE
    assert len(servicer.requests) == 1


async def test_grpc_unary_calls_have_a_deadline(peer):
    servicer, target = peer
    servicer.delay = 2
    async with A2AGRPCTransport(target, insecure=True, timeout=0.2) as transport:
        with pytest.raises(grpc.aio.AioRpcError) as failure:
            await transport.request("a2a.get", {"id": "task-1"})
        assert failure.value.code() == grpc.StatusCode.DEADLINE_EXCEEDED


async def test_grpc_rejects_unknown_fields_and_bad_task_ids(peer):
    servicer, target = peer
    async with A2AGRPCTransport(target, insecure=True) as transport:
        with pytest.raises(json_format.ParseError):
            await transport.request("a2a.send", {"message": message(bogus=1)})
        with pytest.raises(json_format.ParseError):
            transport.stream("a2a.send", {"message": message(role="ROLE_ADMIN")})
        for bad in ["", None, 7]:
            with pytest.raises(ValueError):
                await transport.request("a2a.get", {"id": bad})
            with pytest.raises(ValueError):
                transport.stream("a2a.subscribe", {"id": bad})
        with pytest.raises(ValueError):
            await transport.request("a2a.subscribe", {"id": "task-1"})
        with pytest.raises(ValueError):
            transport.stream("a2a.get", {"id": "task-1"})
    assert servicer.requests == []


async def test_grpc_plain_text_is_loopback_only():
    for target in ["agent.example:443", "10.0.0.5:50051", "[2001:db8::1]:50051"]:
        with pytest.raises(ValueError):
            A2AGRPCTransport(target, insecure=True)
    for target in ["localhost:50051", "127.0.0.1:50051", "[::1]:50051"]:
        async with A2AGRPCTransport(target, insecure=True):
            pass
    with pytest.raises(ValueError):
        A2AGRPCTransport()


async def test_grpc_target_must_be_a_bare_host_and_port():
    for target in [
        "dns:///localhost:50051",
        "unix:/tmp/a2a.sock",
        "https://agent.example:443",
        "user:password@agent.example:443",
        "agent.example",
        "agent.example:port",
        "",
    ]:
        with pytest.raises(ValueError):
            A2AGRPCTransport(target)
    async with A2AGRPCTransport("agent.example:443"):
        pass  # TLS channels are created lazily, so nothing is dialled here


async def test_grpc_caller_owned_channel_is_left_open(peer):
    _, target = peer
    channel = grpc.aio.insecure_channel(target)
    try:
        async with A2AGRPCTransport(channel=channel):
            pass
        async with A2AGRPCTransport(channel=channel) as transport:
            assert await transport.request("a2a.get", {"id": "task-1"}) == task()
        for kwargs in [{"target": target}, {"insecure": True}, {"credentials": object()}]:
            with pytest.raises(ValueError):
                A2AGRPCTransport(channel=channel, **kwargs)
    finally:
        await channel.close()


async def test_grpc_stream_close_waits_for_the_call_to_settle(peer):
    servicer, target = peer
    servicer.hold = True
    async with A2AGRPCTransport(target, insecure=True) as transport:
        stream = transport.stream("a2a.subscribe", {"id": "task-1"})
        assert await stream.__anext__() == task()
        await stream.aclose()
        assert stream._call.done()
        assert await stream._call.code() == grpc.StatusCode.CANCELLED
        await stream.aclose()  # idempotent, like the HTTP transport's generator
        with pytest.raises(StopAsyncIteration):
            await stream.__anext__()


async def test_grpc_metadata_is_sent_from_mappings_and_pairs(peer):
    servicer, target = peer
    seen = []

    async def admit(name, request, context):
        seen.append(dict(context.invocation_metadata()))
        if servicer.error is not None:
            await context.abort(servicer.error, "refused")

    servicer._admit = admit
    async with A2AGRPCTransport(target, insecure=True, metadata={"authorization": "Bearer t"}) as t:
        await t.request("a2a.get", {"id": "task-1"})
    async with A2AGRPCTransport(target, insecure=True, metadata=[("x-peer", "remote")]) as t:
        await t.request("a2a.get", {"id": "task-1"})
    async with A2AGRPCTransport(target, insecure=True) as t:
        await t.request("a2a.get", {"id": "task-1"})
    assert seen[0]["authorization"] == "Bearer t"
    assert seen[1]["x-peer"] == "remote"
    assert "authorization" not in seen[2] and "x-peer" not in seen[2]
