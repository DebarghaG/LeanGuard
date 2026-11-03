"""Guarded A2A 1.0 client over HTTP+JSON or gRPC, with polling and streamed task updates.

Peer profiles are trusted host code: they decide the resource and charge of each
message. Remote responses are untrusted data and cannot create identity,
approval, delegations or tool facts. The transport is replaceable.
"""

from __future__ import annotations

import json
import re
from collections.abc import AsyncGenerator, Callable, Mapping
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Protocol
from urllib.parse import quote, urlparse

from .engine import canonical
from .multiagent import Agent, Interaction
from .types import CallResult


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate A2A JSON field")
        result[key] = value
    return result


class A2AStream(Protocol):
    """A response stream owned by the caller. Await `aclose()` when finished with it."""

    def __aiter__(self) -> A2AStream: ...

    async def __anext__(self) -> dict: ...

    async def aclose(self) -> None: ...


class A2ATransport(Protocol):
    async def request(self, operation: str, payload: dict) -> dict: ...

    def stream(self, operation: str, payload: dict) -> A2AStream: ...


@dataclass(frozen=True)
class PeerFacts:
    """What the host decides a message touches and costs. Says nothing about remote state."""

    resource: str
    amount: int = 0
    facts: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Peer:
    transport: A2ATransport
    profile: Callable[[str, dict], PeerFacts]


class A2AHTTPTransport:
    """Transport for the A2A 1.0 HTTP+JSON (REST) binding.

    Put credentials in the headers of the HTTP client you pass in. Task IDs are
    escaped as single path components and redirects are never followed. Send
    Message is never retried automatically.
    """

    def __init__(self, endpoint: str, *, client=None, headers=None, timeout=30):
        import httpx

        parsed = urlparse(endpoint)
        if (
            (
                parsed.scheme != "https"
                and not (
                    parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1", "::1"}
                )
            )
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError(
                "A2A endpoint requires HTTPS (or loopback HTTP), without credentials/query"
            )
        self.endpoint = endpoint.rstrip("/")
        self._owns_client = client is None
        self.client = client or httpx.AsyncClient(timeout=timeout, follow_redirects=False)
        self.headers = {**(headers or {}), "A2A-Version": "1.0"}

    @staticmethod
    def _task_id(value):
        if not isinstance(value, str) or not value or value in {".", ".."}:
            raise ValueError("invalid remote task path component")
        return quote(value, safe="")

    def _route(self, operation, payload):
        if operation == "a2a.send":
            return "POST", "/message:send", payload
        task = self._task_id(payload["id"])
        if operation == "a2a.get":
            return "GET", f"/tasks/{task}", None
        if operation == "a2a.cancel":
            return "POST", f"/tasks/{task}:cancel", {}
        raise ValueError("unsupported A2A operation")

    async def request(self, operation, payload):
        method, path, body = self._route(operation, payload)
        headers = {**self.headers, "Content-Type": "application/a2a+json"}
        async with self.client.stream(
            method,
            self.endpoint + path,
            content=None if body is None else canonical(body),
            headers=headers,
            follow_redirects=False,
        ) as response:
            response.raise_for_status()
            data = bytearray()
            async for chunk in response.aiter_bytes(chunk_size=65536):
                data.extend(chunk)
                if len(data) > 8 * 1024 * 1024:
                    raise ValueError("A2A response exceeds 8 MiB")
            value = json.loads(data, object_pairs_hook=_unique_object)
        return value if operation == "a2a.send" else {"task": value}

    async def stream(self, operation, payload):
        if operation == "a2a.send":
            method, path, body = "POST", "/message:stream", payload
        elif operation == "a2a.subscribe":
            method, path, body = "GET", f"/tasks/{self._task_id(payload['id'])}:subscribe", None
        else:
            raise ValueError("unsupported streaming operation")
        headers = {
            **self.headers,
            "Accept": "text/event-stream",
            "Content-Type": "application/a2a+json",
        }
        async with self.client.stream(
            method,
            self.endpoint + path,
            content=None if body is None else canonical(body),
            headers=headers,
            follow_redirects=False,
        ) as response:
            response.raise_for_status()
            if response.headers.get("content-type", "").split(";", 1)[0] != "text/event-stream":
                raise ValueError("A2A stream did not return text/event-stream")
            data, size = [], 0
            async for line in self._sse_lines(response):
                size += len(line) + 1
                if size > 8 * 1024 * 1024:
                    raise ValueError("A2A stream frame exceeds 8 MiB")
                if not line:
                    if data:
                        yield json.loads(b"\n".join(data), object_pairs_hook=_unique_object)
                    data, size = [], 0
                elif line.startswith(b"data:"):
                    data.append(line[5:].removeprefix(b" "))
            if data:
                raise ValueError("incomplete A2A stream frame")

    @staticmethod
    async def _sse_lines(response):
        # Enforce the frame limit before decoding, so one huge line or comment can't
        # slip past it. SSE allows LF, CRLF and CR line endings.
        pending, first, skip_lf = bytearray(), True, False
        # Read whatever has arrived. Waiting for fixed-size chunks would delay live events.
        async for chunk in response.aiter_bytes():
            if skip_lf:
                chunk, skip_lf = chunk.removeprefix(b"\n"), False
            pending.extend(chunk)
            while match := re.search(rb"\r\n|\r|\n", pending):
                if match.start() > 8 * 1024 * 1024:
                    raise ValueError("A2A stream line exceeds 8 MiB")
                # CR ends a line at once; drop the following LF if a CRLF was split across reads.
                skip_lf = match.group() == b"\r" and match.end() == len(pending)
                line = bytes(pending[: match.start()])
                del pending[: match.end()]
                if first:
                    line, first = line.removeprefix(b"\xef\xbb\xbf"), False
                yield line
            if len(pending) > 8 * 1024 * 1024:
                raise ValueError("A2A stream line exceeds 8 MiB")
        if pending:
            raise ValueError("incomplete A2A stream line")

    async def aclose(self):
        if self._owns_client:
            await self.client.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        await self.aclose()


_GRPC_LOOPBACK = frozenset({"localhost", "127.0.0.1", "::1"})
_GRPC_MAX_MESSAGE = 8 * 1024 * 1024


class _GRPCStream:
    """Owns one server-streaming call and converts each response to a frame."""

    def __init__(self, call, frame):
        self._call = call
        self._frame = frame

    def __aiter__(self):
        return self

    async def __anext__(self):
        import grpc

        if self._call.cancelled():
            # A locally cancelled call raises CancelledError from read(); a
            # closed stream should end quietly, like a closed async generator.
            raise StopAsyncIteration
        response = await self._call.read()
        if response is grpc.aio.EOF:
            raise StopAsyncIteration
        return self._frame(response)

    async def aclose(self):
        # Cancel, then wait for the call to settle so no work is left running once
        # the client releases its close fence. `code()` never raises.
        self._call.cancel()
        await self._call.code()


class A2AGRPCTransport:
    """Transport for the A2A 1.0 gRPC binding.

    `target` is a `host:port` pair. Channels use TLS; pass `credentials` for mTLS
    or a private root. Plain-text channels are allowed for loopback targets only.
    Alternatively pass your own `channel`, on its own: it is trusted host
    configuration, like the HTTP transport's client, so its target, credentials
    and options are yours to get right, and this class cannot check them. Retries
    are off on channels it creates,
    so Send Message is never retried automatically. Responses are capped at 8 MiB
    per message. Unary calls get a deadline; streams get none, since a
    subscription may stay open for a long time. `metadata` is sent with every
    call, as a mapping or a sequence of pairs. The protocol version is carried by
    the proto package, so no version metadata is sent. Outbound payloads are
    parsed strictly and unknown fields are rejected.
    """

    def __init__(
        self,
        target=None,
        *,
        channel=None,
        credentials=None,
        insecure=False,
        timeout=30,
        metadata=None,
    ):
        import grpc

        from .a2a_grpc import a2a_pb2, a2a_pb2_grpc

        self._pb2 = a2a_pb2
        self.timeout = timeout
        pairs = metadata.items() if isinstance(metadata, Mapping) else metadata or ()
        self.metadata = tuple((str(key), value) for key, value in pairs) or None
        self._owns_channel = channel is None
        if channel is not None and (target is not None or credentials is not None or insecure):
            raise ValueError("pass either a channel or target/credentials/insecure, not both")
        if channel is None:
            if target is None:
                raise ValueError("A2A gRPC transport requires a target or a channel")
            host = self._host(target)
            options = [
                ("grpc.enable_retries", 0),
                ("grpc.max_receive_message_length", _GRPC_MAX_MESSAGE),
            ]
            if insecure:
                if host not in _GRPC_LOOPBACK:
                    raise ValueError("plain-text A2A gRPC is allowed for loopback targets only")
                channel = grpc.aio.insecure_channel(target, options=options)
            else:
                channel = grpc.aio.secure_channel(
                    target, credentials or grpc.ssl_channel_credentials(), options=options
                )
        self.channel = channel
        self.stub = a2a_pb2_grpc.A2AServiceStub(channel)

    @staticmethod
    def _host(target):
        # Plain host:port only. Resolver schemes such as dns:/// or unix: would
        # bypass the loopback check, so they are rejected.
        if not isinstance(target, str) or not target or "/" in target:
            raise ValueError("A2A gRPC target must be host:port")
        parsed = urlparse("//" + target)
        if (
            parsed.username is not None
            or parsed.password is not None
            or not parsed.hostname
            or parsed.port is None
        ):
            raise ValueError("A2A gRPC target must be host:port, without credentials")
        return parsed.hostname

    @staticmethod
    def _task_id(value):
        if not isinstance(value, str) or not value:
            raise ValueError("invalid remote task id")
        return value

    @staticmethod
    def _parse(payload, message_type):
        from google.protobuf.json_format import ParseDict

        return ParseDict(payload, message_type())

    @staticmethod
    def _frame(message):
        from google.protobuf.json_format import MessageToDict

        # Default options give camelCase keys and enum names, the JSON shapes the
        # client already validates. Fields at their default value are omitted.
        return MessageToDict(message)

    def _unary(self, operation, payload):
        pb2 = self._pb2
        if operation == "a2a.send":
            return self.stub.SendMessage, self._parse(payload, pb2.SendMessageRequest), False
        if operation == "a2a.get":
            return self.stub.GetTask, pb2.GetTaskRequest(id=self._task_id(payload["id"])), True
        if operation == "a2a.cancel":
            request = pb2.CancelTaskRequest(id=self._task_id(payload["id"]))
            return self.stub.CancelTask, request, True
        raise ValueError("unsupported A2A operation")

    async def request(self, operation, payload):
        method, request, wrap = self._unary(operation, payload)
        response = await method(request, timeout=self.timeout, metadata=self.metadata)
        frame = self._frame(response)
        return {"task": frame} if wrap else frame

    def stream(self, operation, payload):
        pb2 = self._pb2
        if operation == "a2a.send":
            request = self._parse(payload, pb2.SendMessageRequest)
            call = self.stub.SendStreamingMessage(request, metadata=self.metadata)
        elif operation == "a2a.subscribe":
            request = pb2.SubscribeToTaskRequest(id=self._task_id(payload["id"]))
            call = self.stub.SubscribeToTask(request, metadata=self.metadata)
        else:
            raise ValueError("unsupported streaming operation")
        return _GRPCStream(call, self._frame)

    async def aclose(self):
        if self._owns_channel:
            await self.channel.close()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        await self.aclose()


class A2AClient:
    """Sends A2A messages for one authenticated agent to an allowlist of peers.

    `outcome="success"` only means the protocol call returned. The remote task may
    still be running and its claimed effects are unverified; `task()` gives the
    last reported state. Each new send or continuation uses up the agent's
    authority. Streaming and polling never create new delegations.
    """

    def __init__(self, agent: Agent, peers: Mapping[str, Peer]):
        self.agent = agent
        self._peers = dict(peers)

    def task(self, peer: str, task_id: str) -> dict:
        return self.agent._host.task(self.agent, peer, task_id)

    def _begin(self, peer, operation, payload, task_id="", context_id=""):
        configured = self._peers.get(peer)
        if configured is None:
            raise ValueError("unknown A2A peer")
        envelope = json.loads(
            canonical(
                {
                    "peer": peer,
                    "task_id": task_id,
                    "context_id": context_id,
                    "payload": payload,
                }
            )
        )
        facts = configured.profile(operation, deepcopy(envelope))
        event, decision = self.agent._host._begin_interaction(
            self.agent,
            Interaction(operation, peer, facts.resource, envelope, facts.facts, facts.amount),
        )
        return configured, event, decision, envelope["payload"]

    def _receive(self, event, frame):
        frame = json.loads(canonical(frame))
        if not isinstance(frame, dict):
            raise TypeError("invalid A2A response")
        keys = {"task", "message", "statusUpdate", "artifactUpdate"} & frame.keys()
        if len(keys) != 1 or not isinstance(frame[next(iter(keys))], dict):
            raise ValueError("A2A response requires exactly one payload")
        key = next(iter(keys))
        if key == "message":
            message = frame[key]
            if (
                not isinstance(message.get("messageId"), str)
                or not message["messageId"]
                or message.get("role") != "ROLE_AGENT"
                or not isinstance(message.get("parts"), list)
            ):
                raise ValueError("invalid A2A message")
        self.agent._host._update_interaction(event, frame)
        return frame

    async def _call(self, peer, operation, payload, task_id="", context_id="") -> CallResult:
        configured, event, decision, wire = self._begin(
            peer, operation, payload, task_id, context_id
        )
        if not decision["allow"]:
            return decision
        try:
            frame = self._receive(event, await configured.transport.request(operation, wire))
            self.agent._host._finish_interaction(event, frame)
            return {**decision, "outcome": "success", "result": frame}
        except BaseException as exc:
            self.agent._host._finish_interaction(
                event, {"error_type": type(exc).__name__}, unknown=True
            )
            if not isinstance(exc, Exception):
                raise
            return {**decision, "outcome": "unknown", "error": type(exc).__name__}

        finally:
            self.agent._host._release_interaction(event)

    @staticmethod
    def _message(message):
        # Copy before awaiting so callers cannot change admitted bytes in flight.
        message = json.loads(canonical(message))
        if (
            not isinstance(message, dict)
            or message.get("role") != "ROLE_USER"
            or not isinstance(message.get("messageId"), str)
            or not message["messageId"]
            or not isinstance(message.get("parts"), list)
        ):
            raise ValueError("send requires an A2A 1.0 user Message with messageId and parts")
        for key in ("taskId", "contextId"):
            if key in message and (not isinstance(message[key], str) or not message[key]):
                raise ValueError("taskId/contextId must be nonempty strings when supplied")
        return message

    async def send(self, peer: str, message: dict) -> CallResult:
        message = self._message(message)
        return await self._call(
            peer,
            "a2a.send",
            {"message": message},
            message.get("taskId", ""),
            message.get("contextId", ""),
        )

    async def get(self, peer: str, task_id: str) -> CallResult:
        return await self._call(peer, "a2a.get", {"id": task_id}, task_id)

    async def cancel(self, peer: str, task_id: str) -> CallResult:
        return await self._call(peer, "a2a.cancel", {"id": task_id}, task_id)

    def send_stream(self, peer: str, message: dict) -> AsyncGenerator[CallResult, None]:
        message = self._message(message)
        return self._stream(
            peer,
            "a2a.send",
            {"message": message},
            message.get("taskId", ""),
            message.get("contextId", ""),
        )

    def subscribe(self, peer: str, task_id: str) -> AsyncGenerator[CallResult, None]:
        return self._stream(peer, "a2a.subscribe", {"id": task_id}, task_id)

    async def _stream(
        self, peer, operation, payload, task_id="", context_id=""
    ) -> AsyncGenerator[CallResult, None]:
        configured, event, decision, wire = self._begin(
            peer, operation, payload, task_id, context_id
        )
        if not decision["allow"]:
            yield decision
            return
        settled, first, message_only = False, True, False
        stream = None

        async def close_stream():
            nonlocal stream
            # Transfer ownership before awaiting so cleanup failures are not retried.
            owned, stream = stream, None
            if owned is not None:
                await owned.aclose()

        try:
            stream = configured.transport.stream(operation, wire)
            async for frame in stream:
                if first:
                    if not isinstance(frame, dict) or not ({"task", "message"} & frame.keys()):
                        raise ValueError("A2A stream must begin with a Task or Message")
                    if operation == "a2a.subscribe" and "task" not in frame:
                        raise ValueError("subscription must begin with a Task")
                    message_only = "message" in frame
                elif message_only or not ({"statusUpdate", "artifactUpdate"} & frame.keys()):
                    raise ValueError("unexpected A2A stream payload")
                frame = self._receive(event, frame)
                if not settled:
                    self.agent._host._finish_interaction(event, frame)
                    settled = True
                first = False
                yield {**decision, "outcome": "success", "result": frame}
            if first:
                raise ValueError("empty A2A stream")
        except BaseException as exc:
            if settled:
                self.agent._host._stream_error(event, type(exc).__name__)
            else:
                self.agent._host._finish_interaction(
                    event, {"error_type": type(exc).__name__}, unknown=True
                )
            if not isinstance(exc, Exception):
                raise
            await close_stream()
            yield {**decision, "outcome": "unknown", "error": type(exc).__name__}

        finally:
            try:
                await close_stream()
            finally:
                self.agent._host._release_interaction(event)
