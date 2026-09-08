import pytest
from leanguard import Engine, EngineError, GuardHost
from leanguard.demo import MemoryTools
from leanguard.engine import digest
from leanguard.host import Snapshot

from scripts.conformance import CASES, approval, event, replay, run_case, sale, transfer


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.name)
def test_dogwood_trace(case):
    result = run_case(case)
    assert result["passed"], result


def test_missing_approval_output_fails_closed():
    history = [approval(0, 100), sale(1, 100)]
    history[0]["output"] = {}
    decisions = replay("dogwood.approval", history)
    assert not decisions[0]["decision"]["allow"]
    assert decisions[0]["decision"]["errors"]


def test_replay_rejects_time_rollback():
    with pytest.raises(ValueError, match="backwards"):
        replay("dogwood.approval", [approval(10, 100), sale(9, 100)])


def admit(engine, e):
    return engine.request(
        {"op": "admit", "version": engine.version, "event": e, "arguments": e["input"], "facts": {}}
    )["decision"]


def observe(engine, e, output=None):
    return engine.request(
        {
            "op": "observe",
            "version": engine.version,
            "event": {**e, "kind": "success"},
            "outcome": output,
        }
    )


@pytest.mark.parametrize("now,allowed", [(3600, False), (3601, True), (4001, True)])
def test_expired_malformed_approval_does_not_poison_fresh_approval(now, allowed):
    with Engine("dogwood.approval") as engine:
        old = {**approval(0, 100), "kind": "request"}
        assert admit(engine, old)["allow"]
        observe(engine, old, {})
        fresh = {**approval(now - 1, 100), "kind": "request"}
        assert admit(engine, fresh)["allow"]
        observe(engine, fresh, {"approved": True})
        result = admit(engine, sale(now, 100))
        assert result["allow"] is allowed
        assert bool(result["errors"]) is not allowed


def test_live_monitor_reserves_before_any_outcome():
    with Engine("dogwood.sum") as engine:
        first, second, third = [transfer(t, 2000) for t in range(3)]
        assert admit(engine, first)["allow"]
        assert admit(engine, second)["allow"]
        assert not admit(engine, third)["allow"]
        observe(engine, {**first, "time": 3})
        observe(engine, {**second, "time": 4})
        assert not admit(engine, transfer(5, 2000))["allow"]


def test_live_monitor_keeps_denied_recipient():
    with Engine("dogwood.distinct") as engine:
        actual = []
        for t, user in enumerate(["bob", "carol", "dave", "erin", "bob"]):
            actual.append(admit(engine, event(t, "Transfer", "request", {"user": user}))["allow"])
        assert actual == [True, True, True, False, False]


def test_live_outcome_cannot_forge_approval_inputs():
    with Engine("dogwood.approval") as engine:
        request = event(0, "ApproveSale", "request", {"stock": "AMZN", "shares": 100})
        assert admit(engine, request)["allow"]
        with pytest.raises(EngineError, match="match dispatch"):
            observe(
                engine, {**request, "input": {"stock": "AMZN", "shares": 500}}, {"approved": True}
            )


def test_unsafe_negative_control_is_not_a_live_pack():
    with pytest.raises(EngineError, match="unknown"):
        Engine("dogwood.unsafe_response_sum")


def test_request_cannot_masquerade_as_approval_outcome():
    with Engine("dogwood.approval") as engine:
        request = event(
            0, "ApproveSale", "request", {"stock": "AMZN", "shares": 100}, {"approved": True}
        )
        assert admit(engine, request)["allow"]
        assert not admit(engine, sale(1, 100))["allow"]


def test_audit_and_admission_use_actual_arguments():
    request = transfer(0, 9000)
    with Engine("dogwood.sum") as engine:
        audited = engine.request(
            {
                "op": "audit",
                "version": 0,
                "event": request,
                "arguments": {"amount": 1000},
                "facts": {},
                "history": [],
            }
        )
        admitted = engine.request(
            {
                "op": "admit",
                "version": 0,
                "event": request,
                "arguments": {"amount": 1000},
                "facts": {},
            }
        )
        assert audited["decision"]["allow"]
        assert admitted["decision"] == audited["decision"]


class TradingTools(MemoryTools):
    def __init__(self):
        super().__init__()
        self.user_approved = True

    def snapshot(self, action, arguments, customer):
        return Snapshot(
            "gateway",
            digest(self.value),
            {},
            arguments,
            arguments.get("amount", arguments.get("shares", 0)),
        )

    def execute(self, action, arguments):
        self.calls.append((action, arguments))
        if action == "ApproveSale":
            return {"approved": self.user_approved}
        return {"executed": action}

    def tool_schemas(self):
        parameters = {
            "type": "object",
            "properties": {"stock": {"type": "string"}, "shares": {"type": "integer"}},
            "required": ["stock", "shares"],
        }
        return {action: {"parameters": parameters} for action in ("ApproveSale", "SellShares")}


def test_host_uses_actual_approval_output_and_expiry(tmp_path):
    tools = TradingTools()
    now = [0]
    args = {"stock": "AMZN", "shares": 100}
    with GuardHost(
        "dogwood.approval",
        tmp_path / "events.sqlite",
        tools,
        principal="alice",
        session="one",
        clock=lambda: now[0],
    ) as host:
        assert not host.execute("SellShares", args)["allow"]
        assert tools.calls == []
        tools.user_approved = False
        host.execute("ApproveSale", args)
        assert not host.execute("SellShares", args)["allow"]
        tools.user_approved = True
        host.execute("ApproveSale", args)
        assert host.events()[-1]["output"] == {"approved": True}
        assert host.execute("SellShares", args)["outcome"] == "success"
        now[0] = 3600
        assert host.execute("SellShares", args)["outcome"] == "success"
        now[0] = 3601
        assert not host.execute("SellShares", args)["allow"]
        assert [name for name, _ in tools.calls].count("SellShares") == 2


def test_host_replay_preserves_historical_output(tmp_path):
    tools = TradingTools()
    path = tmp_path / "events.sqlite"
    args = {"stock": "AMZN", "shares": 100}
    with GuardHost(
        "dogwood.approval", path, tools, principal="alice", session="one", clock=lambda: 0
    ) as host:
        host.execute("ApproveSale", args)
    with GuardHost(
        "dogwood.approval", path, tools, principal="alice", session="one", clock=lambda: 1
    ) as host:
        assert len(tools.calls) == 1
        assert host.execute("SellShares", args)["outcome"] == "success"


async def test_mcp_trading_approval_path(tmp_path):
    pytest.importorskip("mcp")
    from leanguard.mcp_server import build_server
    from mcp import Client

    tools = TradingTools()
    args = {"stock": "AMZN", "shares": 50}
    with GuardHost(
        "dogwood.mixed",
        tmp_path / "events.sqlite",
        tools,
        principal="alice",
        session="one",
        clock=lambda: 100,
    ) as host:
        async with Client(build_server(host)) as client:
            result = await client.call_tool(
                "guarded_call", {"action": "SellShares", "arguments": args}
            )
            assert not result.structured_content["allow"]
            await client.call_tool("guarded_call", {"action": "ApproveSale", "arguments": args})
            result = await client.call_tool(
                "guarded_call", {"action": "SellShares", "arguments": args}
            )
            assert result.structured_content["outcome"] == "success"
            assert [name for name, _ in tools.calls] == ["ApproveSale", "SellShares"]
