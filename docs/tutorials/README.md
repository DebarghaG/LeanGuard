# Tutorials

These lessons are meant to be followed in order, from start to finish, and each
one ends with something that works. Tutorials 2 and 3 extend the work of the one
before. Tutorial 4 only needs Tutorial 1, and Tutorials 5 and 6 need Tutorial 3.

1. [Your first guarded tool](01-first-guarded-tool.md). Put LeanGuard in front of
   a small notebook service and watch it refuse, ask for approval, and remember
   its decisions across a restart. Python only.
2. [Your own policy, with a proof](02-your-own-policy.md). Write a Lean policy
   for the same notebook, run it, and prove what it allows.
3. [Rules that depend on time](03-rules-that-depend-on-time.md). Add an
   approval that expires and an hourly limit, and move the clock to watch them
   take effect.
4. [Delegating to other agents](04-delegating-to-other-agents.md). Give a
   planner a budget, let it delegate to two readers, and revoke a grant.
5. [Checking an old conversation against a new policy](05-checking-old-conversations.md).
   Save a conversation to a file and replay it against the notes policy.
6. [Guarding an agent over MCP](06-guarding-an-agent-over-mcp.md). Serve the
   notebook to an agent over MCP, first a script and then Claude Code.

You need a LeanGuard checkout where `bash scripts/setup.sh` has finished; see
[Try it](../../README.md#try-it) in the main README.
