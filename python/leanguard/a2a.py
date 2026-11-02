"""Guarded A2A 1.0 HTTP+JSON client with polling and SSE task updates.

The transport is replaceable. Peer profiles are trusted host code defining the
resource and charge of each exact message. A remote response is untrusted data;
it never creates identity, approval, a delegation, or authoritative tool facts.
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
    """An owned response iterator whose cleanup must be awaited."""

    def __aiter__(self) -> A2AStream: ...

    async def __anext__(self) -> dict: ...

    async def aclose(self) -> None: ...


class A2ATransport(Protocol):
    async def request(self, operation: str, payload: dict) -> dict: ...

    def stream(self, operation: str, payload: dict) -> A2AStream: ...


@dataclass(frozen=True)
class PeerFacts:
    """Host interpretation of a message; no assertion about remote state."""

    resource: str
    amount: int = 0
    facts: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Peer:
    transport: A2ATransport
    profile: Callable[[str, dict], PeerFacts]


class A2AHTTPTransport:
    """A2A 1.0 REST binding. Never automatically retry a Send Message.

    Credentials belong in the host-created HTTP client's headers. Task identifiers
    are escaped as single path components. Redirects are disabled on every call.
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
        # Bound a line before decoding it; a malicious unbroken line/comment
        # must not bypass the frame limit. SSE permits LF, CRLF and CR.
        pending, first, skip_lf = bytearray(), True, False
        # Consume available bytes immediately; fixed-size chunks buffer live events.
        async for chunk in response.aiter_bytes():
            if skip_lf:
                chunk, skip_lf = chunk.removeprefix(b"\n"), False
            pending.extend(chunk)
            while match := re.search(rb"\r\n|\r|\n", pending):
                if match.start() > 8 * 1024 * 1024:
                    raise ValueError("A2A stream line exceeds 8 MiB")
                # CR ends a line immediately. Swallow a later LF if CRLF was split.
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


class A2AClient:
    """A peer allowlist and authenticated Agent bound by trusted orchestration.

    `outcome=success` means the protocol operation returned, not that a remote
    task completed or that its claimed effects occurred. Inspect `task()` for
    the last reported lifecycle state. Every new send/continuation consumes
    authority; streams and polling do not mint fresh delegations.
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
