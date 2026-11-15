import asyncio
import threading

import pytest
from leanguard import GuardHost
from leanguard.demo import MemoryTools
from leanguard.integrations.call import bind_async_guarded_call, bind_guarded_call


@pytest.fixture
def host(tmp_path):
    with GuardHost(
        "example", tmp_path / "events.sqlite", MemoryTools(), principal="alice", session="one"
    ) as host:
        yield host


def test_model_boundary_and_bound_approval(host):
    call = bind_guarded_call(host)
    denied = call("write", {"value": "new"})
    assert not denied["allow"]
    assert set(denied) == {"allow", "request_id", "message"}
    assert not host.adapter.calls
    assert call("read", {})["outcome"] == "success"
    proposal = host.prepare("write", {"value": "new"})
    host.confirm(proposal.id, True)
    assert not call("write", {"value": "different"}, proposal.id)["allow"]
    assert call("write", {"value": "new"}, proposal.id)["outcome"] == "success"
    assert not call("write", {"value": "new"}, proposal.id)["allow"]
    assert host.adapter.value == "new"


@pytest.mark.parametrize("args", [(1, {}), ("read", []), ("read", {}, True)])
def test_invalid_tool_arguments_do_not_dispatch(host, args):
    with pytest.raises(TypeError):
        bind_guarded_call(host)(*args)
    assert not host.adapter.calls


async def test_async_cancellation_drains_the_host_transaction(host):
    entered, finish = threading.Event(), threading.Event()
    execute = host.adapter.execute

    def blocked(action, arguments):
        entered.set()
        assert finish.wait(5)
        return execute(action, arguments)

    host.adapter.execute = blocked
    task = asyncio.create_task(bind_async_guarded_call(host)("read", {}))
    try:
        assert await asyncio.to_thread(entered.wait, 5)
        task.cancel()
        await asyncio.sleep(0)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
    finally:
        finish.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert host.events()[-1]["kind"] == "success"
    assert len(host.adapter.calls) == 1


async def test_unknown_outcome_is_preserved_without_leaking_exception(host):
    def fail(action, arguments):
        raise RuntimeError("private backend detail")

    host.adapter.execute = fail
    result = await bind_async_guarded_call(host)("read", {})
    assert result["outcome"] == "unknown"
    assert "error" not in result
    assert "private" not in str(result)
    assert host.events()[-1]["kind"] == "unknown"
