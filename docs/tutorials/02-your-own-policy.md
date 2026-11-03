# Tutorial 2: Your own policy, with a proof

In this tutorial we will write a LeanGuard policy for the notebook from
[Tutorial 1](01-first-guarded-tool.md). The policy says that a note must be read
before it is replaced and that a note is at most 40 characters long. We'll build
it and run the notebook with it, then prove in Lean that it never allows a
longer note, and audit that proof.

You'll need to have finished Tutorial 1. We'll write some Lean, but you don't
need to know Lean beforehand, since every line is given here.

## Set up a Lean project

We'll keep working in `~/notes-tutorial`, next to `notebook.py` from Tutorial 1.
Activate LeanGuard's Python environment as before, then make a directory for the
policy:

```sh
cd ~/notes-tutorial
source ~/LeanGuard/.venv/bin/activate
mkdir notes-policy
cd notes-policy
```

A policy is its own Lean project, which uses LeanGuard as a library. Lean projects
are described by a file called `lakefile.toml`. Create it with this content:

```toml
name = "NotesPolicy"
defaultTargets = ["notes-guard"]

[[require]]
name = "LeanGuard"
path = "../../LeanGuard"

[[lean_lib]]
name = "Notes"
roots = ["Notes", "NotesMain"]

[[lean_exe]]
name = "notes-guard"
root = "NotesMain"
```

The `path` line points from `~/notes-tutorial/notes-policy` to your LeanGuard
checkout. If your checkout isn't at `~/LeanGuard`, change that line to match.

The project must use the same Lean version as LeanGuard, and it can reuse the
libraries that the setup script already downloaded and compiled. Run:

```sh
cp ~/LeanGuard/lean-toolchain .
mkdir .lake
ln -s ~/LeanGuard/.lake/packages .lake/packages
```

The last two commands let the project reuse those libraries, which would
otherwise take several gigabytes of downloads and hours of compiling.

## Write the policy

Create `Notes.lean`:

```lean
import LeanGuard.Schema
import LeanGuard.Policy
import LeanGuard.VerifiedPolicy

namespace Notes
open LeanGuard

def shortNote : Formula Check := check "short_note" fun c ↦ do
  let note ← Data.str c.arguments "value"
  return note.length ≤ 40

def short := require "notes.short" ["write"] shortNote "a note fits in 40 characters"

def pack : PolicyPack := withSchemas {
  name := "notes"
  rules := [
    permit "notes.tools" ["read", "write"],
    require "notes.read_first" ["write"] (observed ["read"]) "read the note before replacing it",
    short
  ]
} [("read", .object [] []), ("write", .object ["value"] [("value", .string)])]

end Notes
```

The `permit` rule lets the agent use the `read` and `write` tools; LeanGuard
refuses any call that no rule permits. Each `require` rule adds a condition that
every `write` must meet. The first uses `observed`, which LeanGuard provides, and
the second uses `shortNote`, defined just above, which reads the `value` argument
and checks its length. The list at the bottom describes the arguments each tool
accepts.

Now create `NotesMain.lean`, which turns the policy into a program:

```lean
import Notes
import LeanGuard.Server

def main : IO Unit := LeanGuard.serve Notes.pack
```

## Build it

```sh
lake build
```

The first build prints some setup messages and then a list of build steps. After
a few seconds it should end with a line like this (the job count may differ):

```text
Build completed successfully (1760 jobs).
```

Your policy is now a program at `.lake/build/bin/notes-guard`.

## Put it in front of the notebook

Go back up to the tutorial directory and start Python:

```sh
cd ~/notes-tutorial
python
```

This time we'll tell `GuardHost` to use our program instead of the built-in
policy. We'll also give it a new journal, `notes-journal.sqlite`, since the one
from Tutorial 1 belongs to the built-in policy.

```pycon
>>> from pathlib import Path
>>> from leanguard import GuardHost
>>> from notebook import Notebook
>>> engine = Path("notes-policy/.lake/build/bin/notes-guard")
>>> notebook = Notebook()
>>> host = GuardHost("notes", "notes-journal.sqlite", notebook, principal="alice", session="chat-1", binary=engine)
```

`"notes"` is the `name` we gave the pack. Read the note, then try to replace it
with a long one:

```pycon
>>> host.execute("read", {})["allow"]
True
>>> result = host.execute("write", {"value": "Buy milk, eggs, flour, butter, sugar, and a birthday candle"})
>>> result["allow"], result["reasons"]
(False, ['notes.short'])
```

The write is refused by our own rule, `notes.short`. Now try a shorter note:

```pycon
>>> result = host.execute("write", {"value": "Buy milk and eggs"})
>>> result["allow"], result["outcome"], result["result"]
(True, 'success', {'text': 'Buy milk and eggs'})
```

This write didn't need the user's approval. The built-in policy in Tutorial 1
asked for one, but ours has no approval rule.

Next, try a write with the wrong argument name:

```pycon
>>> result = host.execute("write", {"text": "Buy milk"})
>>> result["allow"], result["reasons"]
(False, ['notes.short', 'schema.write'])
>>> result["errors"]
['notes.short/short_note: value: property not found: value', 'schema.write/argument_schema: arguments do not match native schema']
```

Two rules refuse it. `schema.write` comes from the argument list at the bottom
of our pack. `notes.short` couldn't find a `value` to measure, and a check that
fails with an error counts as a refusal.

Close the host and leave Python:

```pycon
>>> host.close()
>>> exit()
```

## Prove the policy keeps its promise

So far we have seen the policy refuse one long note. Next we'll prove that it
refuses all of them.

Open `Notes.lean` again. Just before the final `end Notes`, add:

```lean
/-- Every write LeanGuard allows carries a note of at most 40 characters. -/
def Safe (c : Context) : Prop :=
  c.request.action = "write" → ∃ note, Data.str c.arguments "value" = .ok note ∧ note.length ≤ 40

theorem safe (c : Context) (allowed : (decidePolicy pack c).allow = true) : Safe c := by
  intro writing
  have holds := authorized_requirement pack.rules (atomValue c) c.request.action c.history
    short (by simp [pack, withSchemas]) (by simp [Rule.applies, short, require, writing]) rfl
    (decision_sound pack c allowed)
  simp only [short, require, shortNote, check, Holds, atomValue] at holds
  cases value : Data.str c.arguments "value" with
  | error e => simp [value, Except.toOption] at holds
  | ok note => exact ⟨note, rfl, by simpa [value, Except.toOption] using holds⟩

def verified : VerifiedPolicy := {
  pack := pack
  property := "Notes.safe"
  Safe := Safe
  sound := safe
}
```

`Safe` states the property in Lean: if the call is a write, its `value` is a
string of at most 40 characters. The theorem `safe` says that the property holds
for every call our pack allows. The proof looks up the `notes.short` rule, which
every allowed write must pass, and unfolds what passing it means; you don't need
to follow it line by line. `verified` puts the pack, the property and the proof
together.

Change `NotesMain.lean` so that it serves the verified bundle:

```lean
import Notes
import LeanGuard.Server

def main : IO Unit := LeanGuard.serveVerified Notes.verified
```

Then go back into `notes-policy` and build:

```sh
cd notes-policy
lake build
```

The output again ends with `Build completed successfully`, which means Lean has
checked the proof.

## Watch the proof catch a mistake

Let's see what happens when the policy and the property disagree. In
`Notes.lean`, change the limit in `shortNote` from 40 to 50, and leave `Safe` as
it is:

```lean
  return note.length ≤ 50
```

Build again:

```sh
lake build
```

This time the build fails. Among the output you'll find:

```text
error: Notes.lean:35:36: Type mismatch: After simplification, term
  holds
 has type
  note.length ≤ 50
but is expected to have type
  note.length ≤ 40
```

Lean is reporting that the rule only guarantees 50 characters, while `Safe`
asks for 40, so the proof no longer goes through. Put the limit back to 40 and
run `lake build` again to see it succeed.

## Audit the proof

A successful build doesn't by itself mean every proof is finished. Lean's
`sorry` keyword stands in for a missing proof and only produces a warning, so
before using a policy we run an audit that looks for it. Create
`NotesAudit.lean` in `notes-policy`:

```lean
import NotesMain
import LeanGuard.Audit

run_cmd do
  LeanGuard.Audit.check #[``Notes.verified, ``Notes.safe, ``main] #[`Notes, `LeanGuard]

#print axioms Notes.safe
```

Run it:

```sh
lake env lean NotesAudit.lean
```

The output should look like this:

```text
LeanGuard axiom audit passed for 926 declarations
'Notes.safe' depends on axioms: [propext, Classical.choice, Quot.sound]
```

The number of declarations may differ. The three axioms on the second line are
standard in Lean, and they are the only ones the audit accepts.

To see the audit fail, replace the proof of `safe` in `Notes.lean`, everything
after `:= by`, with `sorry`:

```lean
theorem safe (c : Context) (allowed : (decidePolicy pack c).allow = true) : Safe c := by
  sorry
```

Run `lake build`. It succeeds, with only a warning that the declaration uses
`sorry`. Run the audit again:

```sh
lake env lean NotesAudit.lean
```

```text
NotesAudit.lean:4:0: error: Notes.safe depends on nonstandard axioms: [sorryAx]
'Notes.safe' depends on axioms: [propext, sorryAx, Classical.choice, Quot.sound]
```

The audit reports `sorryAx`, the axiom behind `sorry`, and fails. Put the real
proof back, run `lake build`, and run the audit again to see it pass.

## Use the proved policy

Go back to the tutorial directory and start Python:

```sh
cd ~/notes-tutorial
python
```

Open the notebook with the journal from earlier in this tutorial:

```pycon
>>> from pathlib import Path
>>> from leanguard import GuardHost
>>> from notebook import Notebook
>>> engine = Path("notes-policy/.lake/build/bin/notes-guard")
>>> host = GuardHost("notes", "notes-journal.sqlite", Notebook(), principal="alice", session="chat-1", binary=engine)
Traceback (most recent call last):
  ...
RuntimeError: journal identity or compiled policy version mismatch
```

The journal records a hash of the program that made its decisions, and we've
rebuilt the program since then, so LeanGuard refuses to open it. Leave Python,
delete the journal, and start again:

```pycon
>>> exit()
```

```sh
rm notes-journal.sqlite*
python
```

```pycon
>>> from pathlib import Path
>>> from leanguard import GuardHost
>>> from notebook import Notebook
>>> engine = Path("notes-policy/.lake/build/bin/notes-guard")
>>> host = GuardHost("notes", "notes-journal.sqlite", Notebook(), principal="alice", session="chat-1", binary=engine)
>>> host.engine.manifest["properties"]
['Notes.safe']
```

The engine's manifest now lists the property we proved. Its decisions are the
same as before:

```pycon
>>> host.execute("read", {})["allow"]
True
>>> host.execute("write", {"value": "Buy milk, eggs, flour, butter, sugar, and a birthday candle"})["reasons"]
['notes.short']
>>> host.close()
>>> exit()
```

## What we built

We wrote a policy for the notebook with a check of our own, compiled it, and saw
it refuse a long note and a write with the wrong argument. We then stated the
property we wanted in Lean, proved it, saw the build fail when the rule no
longer matched the property, and audited the proof. The notebook now runs on
the proved policy, and its manifest names the property.

To learn more about what we used here, the
[policy authoring guide](../native-dsl.md) describes every kind of rule and
condition, and its section on
[proof contracts](../native-dsl.md#proof-contracts-and-downstream-audits)
explains `VerifiedPolicy` and the audit in depth. The
[custom policy example](../../examples/custom_policy/Guard.lean) proves a
larger property about approvals and budgets.

In [Tutorial 3](03-rules-that-depend-on-time.md) we'll add rules to this policy
that depend on time.
