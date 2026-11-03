# Tutorial 3: Rules that depend on time

In this tutorial we will add two rules to the notes policy from
[Tutorial 2](02-your-own-policy.md). The first says that the user's approval of
a write lasts five minutes. The second limits the notebook to three calls in any
hour. We'll control LeanGuard's clock ourselves, so we can move time forward and
watch the decisions change.

You'll need to have finished Tutorial 2.

## Add the rules

Open `~/notes-tutorial/notes-policy/Notes.lean` and replace the definition of
`pack` with this one:

```lean
def pack : PolicyPack := withSchemas {
  name := "notes"
  rules := [
    permit "notes.tools" ["read", "write"],
    require "notes.read_first" ["write"] (observed ["read"]) "read the note before replacing it",
    short,
    require "notes.approved" ["write"] (confirmedWithin 300) "approved in the last five minutes",
    require "notes.hourly" ["write"] (quota 3 1000 3600) "at most three calls an hour"
  ]
} [("read", .object [] []), ("write", .object ["value"] [("value", .string)])]
```

The last two rules are new. `confirmedWithin 300` holds when the user approved
this exact write at most 300 seconds ago and the approval hasn't been used yet.
`quota 3 1000 3600` holds when fewer than three calls have gone through in the
last 3600 seconds. Its middle number limits units that a tool can charge, such
as money spent. The notebook charges nothing, so it plays no part here.

Leave the rest of the file as it is, including the proof. Build the policy and
run the audit:

```sh
cd ~/notes-tutorial/notes-policy
source ~/LeanGuard/.venv/bin/activate
lake build
lake env lean NotesAudit.lean
```

The build ends with `Build completed successfully` and the audit prints the same
two lines as in Tutorial 2:

```text
LeanGuard axiom audit passed for 926 declarations
'Notes.safe' depends on axioms: [propext, Classical.choice, Quot.sound]
```

We added two rules without touching the proof, and it still holds. The proof
only relies on `notes.short` being in the pack, and adding requirements can
only make the policy refuse more.

## Start with a clock we control

Go back to the tutorial directory and start Python:

```sh
cd ~/notes-tutorial
python
```

`GuardHost` normally reads the time from the computer's clock, in seconds. It
also accepts a `clock` argument, a function that returns the current time. We'll
keep the time in a variable called `now` and give `GuardHost` a function that
returns it:

```pycon
>>> from pathlib import Path
>>> from leanguard import GuardHost
>>> from notebook import Notebook
>>> engine = Path("notes-policy/.lake/build/bin/notes-guard")
>>> now = 0
>>> host = GuardHost("notes", "timed-journal.sqlite", Notebook(), principal="alice", session="chat-1", binary=engine, clock=lambda: now)
```

We use a new journal, `timed-journal.sqlite`, because the policy has been
rebuilt and the journal from Tutorial 2 belongs to the old build.

## Let an approval expire

At time 0 we read the note, and the user approves a write:

```pycon
>>> host.execute("read", {})["allow"]
True
>>> proposal = host.prepare("write", {"value": "Buy milk and eggs"})
>>> host.confirm(proposal.id, True)
```

Now ten minutes pass before the agent makes the write. Set the clock to 600
seconds and try it:

```pycon
>>> now = 600
>>> result = host.execute("write", {"value": "Buy milk and eggs"}, proposal_id=proposal.id)
>>> result["allow"], result["reasons"]
(False, ['notes.approved'])
```

The approval is ten minutes old, and our rule only accepts approvals from the
last five, so the write is refused. Ask the user again, and this time make the
write a minute later:

```pycon
>>> proposal = host.prepare("write", {"value": "Buy milk and eggs"})
>>> host.confirm(proposal.id, True)
>>> now = 660
>>> result = host.execute("write", {"value": "Buy milk and eggs"}, proposal_id=proposal.id)
>>> result["allow"], result["result"]
(True, {'text': 'Buy milk and eggs'})
```

A one-minute-old approval is accepted.

## Reach the hourly limit

Each write from now on needs a fresh approval, so let's write a small function
that asks for one and makes the write. Type it line by line, and press Enter on
the empty `...` line at the end:

```pycon
>>> def approved_write(value):
...     proposal = host.prepare("write", {"value": value})
...     host.confirm(proposal.id, True)
...     result = host.execute("write", {"value": value}, proposal_id=proposal.id)
...     return result["allow"], result["reasons"]
...
```

Twenty minutes in, make another write:

```pycon
>>> now = 1200
>>> approved_write("Buy bread")
(True, [])
```

Ten minutes later, try one more:

```pycon
>>> now = 1800
>>> approved_write("Buy cheese")
(False, ['notes.hourly'])
```

This time the hourly limit refuses it. Three calls have gone through in the last
hour: the read at time 0 and the writes at 660 and 1200. The rule counts every
call that reached the notebook, reads included.

Now move the clock to 3700 seconds, a little over an hour after the first read,
and try the same write again:

```pycon
>>> now = 3700
>>> approved_write("Buy cheese")
(True, [])
```

The read at time 0 is now more than an hour old, so only two calls fall inside
the window and the write is allowed.

Close the host and leave Python:

```pycon
>>> host.close()
>>> exit()
```

## What we built

We added an approval that lasts five minutes and an hourly limit to the notes
policy, and saw that the proof from Tutorial 2 still held. With a clock under
our control, we saw an approval expire, a fresh one accepted, a write refused
for going over the limit, and the same write allowed once the oldest call had
left the hour.

The clock we used is only for learning and testing. In a real application,
leave out the `clock` argument and LeanGuard uses the computer's clock. The
[policy authoring guide](../native-dsl.md) lists the other conditions that look
back in time. In [Tutorial 4](04-delegating-to-other-agents.md) we'll let
several agents share the notebook.
