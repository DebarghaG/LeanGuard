# Tutorial 5: Checking an old conversation against a new policy

In this tutorial we will record a conversation under LeanGuard's built-in
policy, save it to a file, and then replay it against the notes policy from
[Tutorial 3](03-rules-that-depend-on-time.md). Replay tells us, call by call,
what the notes policy would have decided. It runs nothing and changes nothing,
so it is a safe way to try a new policy on what agents have already done.

You'll need to have finished Tutorial 3.

## Record a conversation

Start Python in the tutorial directory:

```sh
cd ~/notes-tutorial
source ~/LeanGuard/.venv/bin/activate
python
```

Open a host with the built-in `example` policy and a clock we control, as in
Tutorial 3. This conversation is called `chat-2`:

```pycon
>>> import json
>>> from leanguard import GuardHost
>>> from notebook import Notebook
>>> now = 0
>>> host = GuardHost("example", "chat-2-journal.sqlite", Notebook(), principal="alice", session="chat-2", clock=lambda: now)
```

Define a function that gets the user's approval for a write and then makes it.
Press Enter on the empty `...` line at the end:

```pycon
>>> def approved_write(value):
...     proposal = host.prepare("write", {"value": value})
...     host.confirm(proposal.id, True)
...     return host.execute("write", {"value": value}, proposal_id=proposal.id)["allow"]
...
```

Now play out the conversation. The agent reads the note, then makes two
approved writes a minute apart, the second one long:

```pycon
>>> host.execute("read", {})["allow"]
True
>>> now = 60
>>> approved_write("Buy milk and eggs")
True
>>> now = 120
>>> approved_write("Buy milk, eggs, flour, butter, sugar, and a birthday candle")
True
```

Then the user approves one more write, and the agent waits twelve minutes
before making it:

```pycon
>>> now = 180
>>> proposal = host.prepare("write", {"value": "Buy bread"})
>>> host.confirm(proposal.id, True)
>>> now = 900
>>> host.execute("write", {"value": "Buy bread"}, proposal_id=proposal.id)["allow"]
True
```

The built-in policy allowed all four calls.

## Save it to a file

`host.events()` returns everything the journal recorded, oldest first:

```pycon
>>> events = host.events()
>>> len(events)
15
>>> [event["kind"] for event in events[:3]]
['request', 'dispatch', 'success']
```

Each call shows up as several events. For the read, there is the `request`, a
`dispatch` when LeanGuard let it through, and a `success` when the notebook
answered. Each approval is a `confirmed` event.

Write the events to a file, one JSON object per line, and leave Python:

```pycon
>>> with open("chat-2.jsonl", "w") as file:
...     for event in events:
...         print(json.dumps(event), file=file)
...
>>> host.close()
>>> exit()
```

`chat-2.jsonl` is now an ordinary text file with fifteen lines. It doesn't
depend on the journal or on the policy that made the decisions.

## Replay it against the notes policy

Start Python again. This time we don't open a host, because we won't call the
notebook. We only need the compiled notes policy:

```pycon
>>> import json
>>> from pathlib import Path
>>> from leanguard import Engine, replay
>>> events = [json.loads(line) for line in open("chat-2.jsonl")]
>>> engine = Engine("notes", binary=Path("notes-policy/.lake/build/bin/notes-guard"))
```

`replay` goes through the events in order and, for each request, asks the
engine what it would have decided at that point. To show which call each answer
belongs to, we look the request up by its id:

```pycon
>>> requests = {event["id"]: event for event in events if event["kind"] == "request"}
>>> for row in replay(engine, events):
...     print(requests[row["request_id"]]["input"], row["assessment"], row["decision"]["reasons"])
...
{} allowed []
{'value': 'Buy milk and eggs'} allowed []
{'value': 'Buy milk, eggs, flour, butter, sugar, and a birthday candle'} denied ['notes.short']
{'value': 'Buy bread'} denied ['notes.approved', 'notes.hourly']
```

The notes policy would have refused two of the four calls. The long note breaks
`notes.short`. The last write breaks `notes.approved`, because its approval was
twelve minutes old, and `notes.hourly`, because three calls had already gone
through that hour.

Notice that the long note counts toward the hourly limit even though the notes
policy would have refused it. Replay keeps the history as it really happened,
and the long note did reach the notebook, so it is one of the three calls.

## Look at one decision in detail

Each row also says which rules held. Look at the last write:

```pycon
>>> rows = list(replay(engine, events))
>>> rows[3]["rules"]
{'notes.approved': False, 'notes.hourly': False, 'notes.read_first': True, 'notes.short': True, 'notes.tools': True, 'schema.write': True}
```

Every rule that applies to a write is listed, with `False` for the two it broke.

## Replay part of a conversation

Logs are sometimes incomplete. Suppose ours had lost its first three events, the
read and its outcome. Without them, the notes policy can't see that the note was
read before the writes. If we tell `replay` that the history is incomplete, it
won't present the result as a refusal:

```pycon
>>> [row["assessment"] for row in replay(engine, events[3:], history_complete=False)]
['insufficient_evidence', 'insufficient_evidence', 'insufficient_evidence']
```

Each write is marked `insufficient_evidence` instead of `denied`. The missing
events might have allowed it, so the replay doesn't claim it would have been
refused.

Close the engine and leave Python:

```pycon
>>> engine.close()
>>> exit()
```

## Replay from the shell

The same check runs from the shell. Give `leanguard replay` the policy name, the
file, and the compiled policy:

```sh
leanguard replay notes chat-2.jsonl --binary notes-policy/.lake/build/bin/notes-guard
```

It prints four lines, one for each request. Each line is a JSON object with the
same `assessment`, `decision` and `rules` we looked at in Python.

## What we built

We recorded a conversation under one policy, saved it as a file of events, and
replayed it against another policy without running any tools. The replay showed
which calls the notes policy would have refused and which rules each one broke.
It counted calls that really happened even when the new policy would have
refused them, and it reported a shortened log as insufficient evidence.

Any log can be replayed this way once it is converted to the same events. The
[recorded trace API](../native-dsl.md#recorded-trace-api) describes what each
event needs, and
[Tutorial 6](06-guarding-an-agent-over-mcp.md) puts the notebook in front of an
agent over MCP.
