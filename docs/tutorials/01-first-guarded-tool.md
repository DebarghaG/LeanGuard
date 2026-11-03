# Tutorial 1: Your first guarded tool

In this tutorial we will put LeanGuard in front of a tiny notebook service, the
kind of tool an AI agent might be given. By the end, the notebook will only
accept a change after the agent has read it and the user has approved, and it
will keep track of this across a restart.

We won't write any Lean in this tutorial. LeanGuard ships with a small built-in
policy called `example`, and we'll use that. [Tutorial 2](02-your-own-policy.md)
is where we write a policy of our own.

## Before you start

You need a LeanGuard checkout where `bash scripts/setup.sh` has finished, as
described in the [main README](../../README.md#try-it). The last thing the setup
script prints is a short demo ending in this line:

```text
Backend calls: ['read', 'write']
```

If you see that, you're ready.

## Make a working directory

We'll work outside the checkout so nothing we create gets mixed up with
LeanGuard's own files. Make a fresh directory and activate LeanGuard's Python
environment. Replace `~/LeanGuard` with wherever your checkout lives:

```sh
mkdir ~/notes-tutorial
cd ~/notes-tutorial
source ~/LeanGuard/.venv/bin/activate
```

Your shell prompt now starts with `(.venv)`. Every command from here on runs in
this directory, with that environment active.

## Build the notebook

Create a file called `notebook.py` with this content:

```python
import hashlib
import threading

from leanguard import Snapshot


class Notebook:
    """A one-page notebook that an agent can read and overwrite."""

    def __init__(self):
        self.lock = threading.RLock()
        self.text = "Buy milk"
        self.calls = []

    def snapshot(self, action, arguments, customer):
        revision = hashlib.sha256(self.text.encode()).hexdigest()
        return Snapshot(resource="notebook", revision=revision, facts={}, arguments=arguments)

    def execute(self, action, arguments):
        self.calls.append(action)
        if action == "write":
            self.text = arguments["value"]
        return {"text": self.text}
```

`execute` is the tool itself, and it keeps a list of the calls that reach it so
we can check later what got through. LeanGuard uses `snapshot` and `lock`; we'll
come back to them near the end.

First, let's see the problem. Start Python and use the notebook directly, the
way an unguarded agent would:

```sh
python
```

```pycon
>>> from notebook import Notebook
>>> notebook = Notebook()
>>> notebook.execute("write", {"value": "Sell the car"})
{'text': 'Sell the car'}
```

The note "Buy milk" has been replaced, although nobody read it first or approved
the change. Leave Python with `exit()`.

## Put a guard in front

Start Python again, and this time wrap the notebook in a `GuardHost`:

```pycon
>>> from leanguard import GuardHost
>>> from notebook import Notebook
>>> notebook = Notebook()
>>> host = GuardHost("example", "journal.sqlite", notebook, principal="alice", session="chat-1")
```

Nothing is printed, but a file called `journal.sqlite` has appeared in your
directory. LeanGuard records its decisions there.

`"example"` picks the built-in policy. `alice` is the person the agent works for,
and `chat-1` names this conversation.

## Try to overwrite the note

From now on, every call goes through `host.execute` instead of the notebook.
Ask for the same overwrite as before:

```pycon
>>> result = host.execute("write", {"value": "Sell the car"})
>>> result["allow"]
False
>>> result["reasons"]
['example.confirm', 'example.read_first']
```

The write is refused. `reasons` names the two rules that blocked it, one asking
for the user's approval and one asking for the note to be read first. Now check
what reached the notebook:

```pycon
>>> notebook.calls
[]
```

The list is empty, because LeanGuard refused the write before calling the tool.

## Read first

Let's satisfy one of the two rules:

```pycon
>>> result = host.execute("read", {})
>>> result["allow"], result["outcome"], result["result"]
(True, 'success', {'text': 'Buy milk'})
```

The read is allowed and returns the notebook's content. Now try the write
again:

```pycon
>>> result = host.execute("write", {"value": "Sell the car"})
>>> result["allow"], result["reasons"]
(False, ['example.confirm'])
```

It is still refused, but `example.read_first` is no longer among the reasons
because LeanGuard has recorded the read.

## Ask for approval

The remaining rule asks for the user's approval. To get it, we first prepare a
proposal describing the exact call:

```pycon
>>> proposal = host.prepare("write", {"value": "Sell the car"})
>>> proposal.details["action"], proposal.details["arguments"]
('write', {'value': 'Sell the car'})
```

In a real application you would show `proposal.details` to the user on a screen
the agent can't control. Here we'll play the user ourselves and say yes:

```pycon
>>> host.confirm(proposal.id, True)
```

Now make the write, passing the proposal along:

```pycon
>>> result = host.execute("write", {"value": "Sell the car"}, proposal_id=proposal.id)
>>> result["allow"], result["outcome"], result["result"]
(True, 'success', {'text': 'Sell the car'})
>>> notebook.calls
['read', 'write']
```

This time the write is allowed. The notebook has received two calls, the read
and the approved write; the two refused writes never reached it.

## Try to use the approval again

Now try the same write with the same proposal a second time:

```pycon
>>> result = host.execute("write", {"value": "Sell the car"}, proposal_id=proposal.id)
>>> result["allow"], result["reasons"]
(False, ['stale_or_mismatched_confirmation'])
```

LeanGuard refuses it. The user approved a change to the notebook as it was
when the proposal was made, and the notebook has changed since then, so the
approval no longer applies.

## Let the note change under an approval

The same check applies if something else changes the notebook between the
proposal and the user's answer. Prepare a new proposal:

```pycon
>>> proposal = host.prepare("write", {"value": "Sell the house"})
```

Before the user answers, someone else edits the note:

```pycon
>>> notebook.text = "Someone else was here"
```

Now the user says yes:

```pycon
>>> host.confirm(proposal.id, True)
Traceback (most recent call last):
  ...
ValueError: state changed; present a new proposal
```

LeanGuard won't record the approval, because the notebook is no longer the one
the proposal described. This is what `snapshot` is for. The `revision` it
returns is a hash of the note, and a proposal is only valid while the revision
stays the same.

Close the host and leave Python:

```pycon
>>> host.close()
>>> exit()
```

## Restart and check the memory

LeanGuard's decisions are stored in `journal.sqlite`. Start Python once more and
open the same journal:

```pycon
>>> from leanguard import GuardHost
>>> from notebook import Notebook
>>> notebook = Notebook()
>>> host = GuardHost("example", "journal.sqlite", notebook, principal="alice", session="chat-1")
>>> result = host.execute("write", {"value": "Sell the car"})
>>> result["allow"], result["reasons"]
(False, ['example.confirm'])
```

Although this is a new Python process, the only reason given is
`example.confirm`. LeanGuard replayed the journal when it opened it, so it knows
the note was already read in this conversation, and that the earlier approval
has been used.

```pycon
>>> host.close()
>>> exit()
```

To go through the lesson again, delete the journal with `rm journal.sqlite*`
and start again from "Put a guard in front".

## What we built

We started with a notebook that any caller could overwrite and put LeanGuard in
front of it. Writes were refused until the note had been read and the user had
approved that exact change, and an approval stopped working once the notebook
changed. The refused calls never reached the notebook, and the journal kept
LeanGuard's record intact across a restart.

The rules came from the built-in `example` policy, which is compiled from Lean.
In [Tutorial 2](02-your-own-policy.md) we'll write a policy of our own for the
notebook and prove a property of it.
