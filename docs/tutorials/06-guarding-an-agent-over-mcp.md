# Tutorial 6: Guarding an agent over MCP

In this tutorial we will serve the notebook over MCP, the protocol AI agents use
to call tools, with the notes policy from
[Tutorial 3](03-rules-that-depend-on-time.md) in front of it. First a short
Python script will play the agent, so we can see each call and its answer.
Then we'll connect Claude Code to the same server and ask it to change the note.

You'll need to have finished Tutorial 3. The last part needs
[Claude Code](https://claude.com/claude-code) installed.

## Write the server

The server needs two things from the notebook that we haven't written yet: a
description of each tool for the agent, and a way to tell which tools change
something. Create `notes_server.py` in `~/notes-tutorial`:

```python
import sys
from pathlib import Path

from leanguard import GuardHost
from leanguard.mcp_server import build_server

from notebook import Notebook

HERE = Path(__file__).resolve().parent


class ServedNotebook(Notebook):
    """The notebook from Tutorial 1, with the descriptions an MCP client needs."""

    def mutating(self, action):
        return action == "write"

    def tool_schemas(self):
        return {
            "read": {"description": "Read the note", "parameters": {"type": "object"}},
            "write": {
                "description": "Replace the note",
                "parameters": {
                    "type": "object",
                    "properties": {"value": {"type": "string"}},
                    "required": ["value"],
                },
            },
        }


def approve(proposal):
    # A real application would show proposal.details to the user and wait for an answer.
    print("Approved:", proposal.details["arguments"], file=sys.stderr)
    return True


with GuardHost(
    "notes",
    HERE / "mcp-journal.sqlite",
    ServedNotebook(),
    principal="alice",
    session="mcp",
    binary=HERE / "notes-policy/.lake/build/bin/notes-guard",
) as host:
    build_server(host, approval=approve).run(transport="stdio")
```

`build_server` turns the host into an MCP server. Whenever the agent asks for a
write, the server prepares a proposal and passes it to `approve`, which plays
the user's part. Ours approves every write and prints it, so that we can see
when it is asked. In a real application this is where the user would see the
proposal and answer. The agent has no way to call `approve` or to answer in the
user's place.

The paths start from `HERE`, the directory the script is in, so the server works
whichever directory it is started from.

## Write a stand-in agent

Create `agent.py` next to it. It starts the server, lists its tools, and makes
four calls:

```python
import asyncio
import sys

from mcp import Client
from mcp.client.stdio import StdioServerParameters

server = StdioServerParameters(command=sys.executable, args=["notes_server.py"])

calls = [
    ("write", {"value": "Sell the car"}),
    ("read", {}),
    ("write", {"value": "Buy milk, eggs, flour, butter, sugar, and a birthday candle"}),
    ("write", {"value": "Buy milk and eggs"}),
]


async def main():
    async with Client(server) as agent:
        tools = await agent.list_tools()
        print("Tools:", [tool.name for tool in tools.tools])
        for action, arguments in calls:
            result = await agent.call_tool(
                "guarded_call", {"action": action, "arguments": arguments}
            )
            answer = result.structured_content
            print(action, arguments, "->", answer.get("result", answer.get("message")))


asyncio.run(main())
```

## Run it

```sh
cd ~/notes-tutorial
source ~/LeanGuard/.venv/bin/activate
python agent.py
```

The output should be:

```text
Tools: ['policy_manifest', 'available_tools', 'guarded_call']
Approved: {'value': 'Sell the car'}
write {'value': 'Sell the car'} -> Tool call denied by policy.
read {} -> {'text': 'Buy milk'}
Approved: {'value': 'Buy milk, eggs, flour, butter, sugar, and a birthday candle'}
write {'value': 'Buy milk, eggs, flour, butter, sugar, and a birthday candle'} -> Tool call denied by policy.
Approved: {'value': 'Buy milk and eggs'}
write {'value': 'Buy milk and eggs'} -> {'text': 'Buy milk and eggs'}
```

The agent sees three tools. It can't call `read` and `write` directly, only
through `guarded_call`, which asks the policy first.

The first write was approved and still refused, because the agent hadn't read
the note. The long note was approved and refused as well. Only the last write,
made after a read and short enough, reached the notebook. An approval is one of
the policy's conditions, and the other rules still apply.

Notice also that the agent isn't told why a call was refused. It only gets
`Tool call denied by policy.`, so it can't use the reasons to find a way around
the rules.

## Find the reasons in the journal

The reasons are in the server's journal. Start Python and replay the journal,
as in [Tutorial 5](05-checking-old-conversations.md):

```pycon
>>> from pathlib import Path
>>> from leanguard import Engine, GuardHost, replay
>>> from notebook import Notebook
>>> engine = Path("notes-policy/.lake/build/bin/notes-guard")
>>> host = GuardHost("notes", "mcp-journal.sqlite", Notebook(), principal="alice", session="mcp", binary=engine)
>>> events = host.events()
>>> host.close()
>>> with Engine("notes", binary=engine) as notes:
...     print([row["decision"]["reasons"] for row in replay(notes, events)])
...
[['notes.read_first'], [], ['notes.short'], []]
>>> exit()
```

There is one list of reasons for each of the four calls. The first write broke
`notes.read_first`, and the long note broke `notes.short`.

The journal outlives the server. If you run `agent.py` again, the hourly limit
from Tutorial 3 still counts the calls from this run. Delete the journal first
to start over:

```sh
rm mcp-journal.sqlite*
```

## Connect Claude Code

Now let's give the same server to a real agent. Register it with Claude Code,
using the Python from LeanGuard's environment:

```sh
claude mcp add notes -- ~/LeanGuard/.venv/bin/python ~/notes-tutorial/notes_server.py
```

Start Claude Code in the tutorial directory:

```sh
claude
```

Ask it:

```text
Use the notes MCP server to replace my note with "Buy milk, eggs, flour, butter, sugar, and a birthday candle".
```

Claude Code will ask your permission before it uses the server's tools. Allow
them. Depending on how it goes about the task, Claude may read the note first or
go straight to the write, and its reply will be worded differently each time.
Whichever it does, the write comes back as `Tool call denied by policy.`, and
Claude tells you that the change wasn't made.

Then ask it for a shorter note:

```text
Now replace it with "Buy milk and eggs".
```

If Claude read the note while handling your first request, this write goes
through and Claude reports the new text. If it didn't, the write is denied
because the note hasn't been read yet. In that case, ask:

```text
Read my note with the notes MCP server, then replace it with "Buy milk and eggs".
```

The read comes first this time, and the write goes through.

Leave Claude Code with `/exit`, and remove the server when you're done:

```sh
claude mcp remove notes
```

## What we built

We served the notebook over MCP with the notes policy in front of it. A script
playing the agent saw that it could only reach the tools through
`guarded_call`, that approved writes were still refused when they broke a rule,
and that a refusal told it nothing about the reason. The reasons stayed in the
journal, where we found them with replay. Finally, we connected Claude Code to
the same server and watched the policy refuse its long note and allow its short
one.

This is the last tutorial. The [main README](../../README.md) shows how to
connect your own backend and lists the other guides.
