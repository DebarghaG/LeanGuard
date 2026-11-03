# Tutorial 4: Delegating to other agents

In this tutorial a planner agent will hand some of its work on the notebook to
two reader agents. We'll give each agent a grant that says what it may do and
how many calls it may make. We'll then see that the readers can't do more than
they were given, that all three agents share the planner's budget, and that
revoking a grant also cuts off every agent below it.

You'll need to have finished [Tutorial 1](01-first-guarded-tool.md). This
tutorial uses LeanGuard's built-in policy again, so it doesn't depend on the
Lean project from Tutorials 2 and 3.

## Open a host for several agents

Start Python in the tutorial directory:

```sh
cd ~/notes-tutorial
source ~/LeanGuard/.venv/bin/activate
python
```

When several agents share a backend, we use `MultiAgentHost` instead of
`GuardHost`. The policy is `multiagent.example`, which is the `example` policy
from Tutorial 1 with the rules for agents added:

```pycon
>>> from leanguard import MultiAgentHost
>>> from notebook import Notebook
>>> notebook = Notebook()
>>> host = MultiAgentHost("multiagent.example", "team-journal.sqlite", notebook, principal="alice", session="chat-1")
```

Try a read straight through the host:

```pycon
>>> result = host.execute("read", {})
>>> result["allow"], result["reasons"]
(False, ['agents.authority'])
```

It is refused. With a `MultiAgentHost`, every call has to come from an agent
holding a grant, and so far there are none.

## Grant authority to a planner

The host issues the first grant. We give it to an agent called `planner`, for a
piece of work called `shopping`:

```pycon
>>> planner = host.grant("planner", workflow="shopping", actions=["read", "write"], resources=["notebook"], calls=5, amount=0, expires=2000000000)
```

The planner may read and write the notebook, at most five times in total.
`amount` limits units that tools charge, and the notebook charges none, so we
leave it at 0. `expires` is the time at which the grant stops working, in
seconds since 1970; 2000000000 falls in 2033.

`host.grant` belongs to our own trusted code. The planner receives the object
it returns, a handle it uses to make calls, and has no way to create grants of
its own.

## Delegate to two readers

The planner hands part of its authority to two readers. Each may only read, at
most three times:

```pycon
>>> reader_a = planner.delegate("reader-a", actions=["read"], resources=["notebook"], peers=[""], calls=3, amount=0, expires=2000000000)
>>> reader_b = planner.delegate("reader-b", actions=["read"], resources=["notebook"], peers=[""], calls=3, amount=0, expires=2000000000)
```

`peers=[""]` means the readers may only use local tools. A grant can also allow
messages to remote agents, which we won't use here.

Let's see what happens if the planner tries to give away more than it has:

```pycon
>>> planner.delegate("greedy", actions=["read"], resources=["notebook"], peers=[""], calls=50, amount=0, expires=2000000000)
Traceback (most recent call last):
  ...
leanguard.engine.EngineError: delegation escalation
```

A grant can only be as large as the one it comes from, and the planner only has
five calls.

## Stay inside the grant

Reader A tries to write:

```pycon
>>> result = reader_a.execute("write", {"value": "Sell the car"})
>>> result["allow"], result["reasons"]
(False, ['example.confirm', 'example.read_first', 'agents.authority'])
>>> result["errors"]
['interaction exceeds active delegation or shared budget']
```

The reasons include the two rules from Tutorial 1, and also `agents.authority`,
because reader A's grant doesn't include writing. Even with the user's approval
and an earlier read, this write would be refused.

Now let reader A read four times in a row:

```pycon
>>> [reader_a.execute("read", {})["allow"] for _ in range(4)]
[True, True, True, False]
```

The first three reads are allowed and the fourth is refused, because reader A's
grant allows three calls.

## Share the planner's budget

The planner now writes, with the user's approval:

```pycon
>>> proposal = planner.prepare("write", {"value": "Buy milk and eggs"})
>>> host.confirm(proposal.id, True)
>>> result = planner.execute("write", {"value": "Buy milk and eggs"}, proposal_id=proposal.id)
>>> result["allow"], result["result"]
(True, {'text': 'Buy milk and eggs'})
```

The `example.read_first` rule asks for a read before a write. The planner
didn't read the note itself, but reader A did, as part of the same workflow,
and that counts.

Reader B hasn't made any calls yet. Let it read twice:

```pycon
>>> [reader_b.execute("read", {})["allow"] for _ in range(2)]
[True, False]
```

Reader B's own grant allows three calls, but its second read is refused. Every
call a reader makes also counts against the planner's grant, and the planner's
five calls are now used up: three reads by reader A, the planner's write, and
one read by reader B. Check what reached the notebook:

```pycon
>>> notebook.calls
['read', 'read', 'read', 'write', 'read']
```

There are exactly five calls.

## Revoke a grant

To see revocation, we'll start a second piece of work with a fresh budget. The
host grants an `editor` agent ten reads for a workflow called `tidy-up`, and the
editor delegates to a `helper`:

```pycon
>>> editor = host.grant("editor", workflow="tidy-up", actions=["read"], resources=["notebook"], calls=10, amount=0, expires=2000000000)
>>> helper = editor.delegate("helper", actions=["read"], resources=["notebook"], peers=[""], calls=10, amount=0, expires=2000000000)
>>> helper.execute("read", {})["allow"]
True
```

Now revoke the editor's grant:

```pycon
>>> host.revoke(editor.delegation)
>>> helper.execute("read", {})["allow"]
False
```

We revoked the editor's grant, and the helper was cut off too, since its
authority came from the editor. Like `grant`, `revoke` is only available to
our own code.

Close the host and leave Python:

```pycon
>>> host.close()
>>> exit()
```

## What we built

We gave a planner a grant to use the notebook and let it delegate reading to two
agents. The readers couldn't write or go over their own limits, and the planner
couldn't hand out more than it had. All the agents drew on the planner's budget,
so the five calls it was granted were the most the whole team could make. A read
by one agent counted as evidence for the planner's write, and revoking a grant
also stopped the agent that had received authority from it.

The journal records the grants along with every decision, so after a restart
`host.bind` gives each agent its handle back with its budget as it was. The
[multi-agent guide](../multi-agent.md) covers this and how agents call remote
agents over A2A. In [Tutorial 5](05-checking-old-conversations.md) we'll check a
recorded conversation against a new policy.
