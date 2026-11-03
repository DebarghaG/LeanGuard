# Suggesting repairs with Lean

When LeanGuard denies a call, an agent often wants to know whether a slightly
different call would go through, for example with a smaller amount or a different
payload. `guard_repair?` answers that question for a list of candidate edits you supply. It
picks the first candidate it can prove both allowed by the policy and acceptable to
the user, and prints the Lean proof so it can be reused.

This is an experimental tool for writing proofs. It never dispatches anything: a
repaired call still has to go through the normal LeanGuard host and pass admission
there.

Run the [examples](Examples.lean) from the repository root:

```sh
lake build LeanGuard.Experimental.Repair
lake env lean examples/repair/Examples.lean
```

## Define the permitted change

You write the repair as an existential goal that says two things: which edits the
user would accept, and that the policy allows the edited call. In this example the
user is fine with any smaller positive spend. The account has already spent 60 of a
100-unit budget, and the agent proposed 70:

```lean
theorem budget_repair : ∃ amount : Nat, 0 < amount ∧ amount ≤ 70 ∧
    (decidePolicy budget (amountContext amount)).allow = true := by
  guard_repair? [70, 50, 0, 40]
```

70 and 50 blow the budget and 0 isn't positive, so the tactic picks 40 and suggests
`exact ⟨40, by guard_solve⟩`. `amountContext` (defined in
[Examples.lean](Examples.lean)) changes only the proposed amount and its encoding;
trusted facts and past events stay as they were.

List candidates in order of preference, since the first one proved wins, and supply
at most 32 of them. If the user needs an exact amount,
write `amount = 70` into the goal instead of allowing a reduction.

The default discharger, `guard_solve`, starts with the cheap options. It looks for a
hypothesis that already proves the goal, then evaluates closed obligations with
`decide`, and hands anything symbolic to grind's engine. It splits explicit
conjunctions so that an edit restriction can be solved with arithmetic while a
concrete policy check is computed. If the split fails, it retries the whole
conjunction so that rules can match terms on both sides. Within a symbolic
obligation, equality reasoning, theorem instantiation, arithmetic, order and case
splitting all share one engine state.

To use a different discharger, add `using` (and import whatever tactics it needs):

```lean
theorem remaining_budget (spent cap proposed : Nat)
    (available : spent ≤ cap) (oversized : cap ≤ spent + proposed) :
    ∃ amount : Nat, amount ≤ proposed ∧ spent + amount = cap := by
  guard_repair? [proposed, cap - spent] using omega
```

## Register policy knowledge

Unfolding a policy for every symbolic candidate is slow. If you prove once what your
policy means in simpler terms, the solver can use that instead. Register a proved
characterization with `@[guard_rule =]`, or a forward implication with
`@[guard_rule →]`. These go into grind's own theorem database, with its pattern
inference and scoping, and `attribute [local guard_rule ...]` keeps a rule local to a
section. `guard_solve` uses this database plus grind's small `lia` arithmetic theorem
set. It does not load the global `@[grind]` set.

The [grind examples](Grind.lean) prove a characterization of a native spending policy
once, then repair symbolic amounts while keeping the full allow predicate in the goal.
They also cover equality propagation, locally scoped rules, the bridge between the
runtime decision and LeanLTL, explicit hints, rollback after failure, and proof replay.

For a one-off lemma, pass it with grind's parameter syntax:

```lean
guard_solve (splits := 0) [policy_characterization]
guard_repair? (splits := 0) [proposed, cap - spent] with [policy_characterization]
```

`policy_characterization` stands in for a theorem you've proved; there's no built-in
declaration by that name. Directional hints such as `→ my_lemma` and local proof
terms go through grind's parameter elaborator. With a custom `using` discharger, put
hints and configuration inside that discharger.

The search limits default to 4 splits, 3 E-matching rounds per split phase,
generation 6 (local theorems included) and 256 instances per branch. Override them
with the usual grind configuration fields; Lean's heartbeat and recursion limits
apply as normal. An uncaught resource exception aborts the whole search, while grind
can also report resource exhaustion as an ordinary failed obligation with
diagnostics.

Every accepted proof is checked against its goal. Proof-trace admission and
`useSorry` are always off, and a proof is rejected if it leaves unresolved
metavariables, reports an error, or depends on `sorry` anywhere, including through
the types and values of local declarations it uses.

When a candidate fails, its failed obligation or discharger error is kept. Turn on
`set_option trace.guard.repair true` to see failed attempts even when a later
candidate succeeds.

[How the repair experiment uses grind](../../docs/grind.md) covers the engine's
architecture, exactly which parts are reused, version differences, and where
extension stops. Run the grind regression cases with:

```sh
lake build LeanGuard.Experimental.TemporalRepair
lake env lean examples/repair/Grind.lean
lake env lean examples/repair/Adversarial.lean
```

## Explain a denial

`#guard_explain pack context` prints the decision along with the descriptions and
check names of the rules that blocked it. An agent can use that to see what's
missing, such as a read it should do first or a confirmation it needs. The
descriptions are the policy author's guidance, so whatever the agent does next
still has to pass admission against a fresh snapshot.

Give the agent structured candidate arguments alongside the explanation. If it
rewrites those arguments, validate the new call and check admission again.

Repair can only change the call. Trusted identity, facts, approval evidence and
history stay fixed, and a missing observation or approval has to come from the
host's trusted flows. The proof covers only the intent restrictions written in the
goal.

## Use LeanLTL policy goals

You can also state compliance as LeanLTL satisfaction by importing
`LeanGuard.Experimental.TemporalRepair`:

```lean
import LeanGuard.Experimental.TemporalRepair
open LeanGuard LeanGuard.Experimental

example (pack : PolicyPack) (context : α → Context) (allowedEdit : α → Prop)
    (candidate : α) (intent : allowedEdit candidate)
    (safe : historyTrace (context candidate).history ⊨ pack.toLeanLTL (context candidate)) :
    ∃ edit, allowedEdit edit ∧
      (historyTrace (context edit).history ⊨ pack.toLeanLTL (context edit)) := by
  guard_repair? [candidate] using exact ⟨intent, safe⟩
```

`pack.toLeanLTL` includes the validation-error gate, so the repairs it accepts are
exactly the ones the native allow decision accepts. Prefer it to a single temporal
condition, which would leave out the policy's other requirements.

A repair proof is about the history you gave it. Later events can revoke an approval
or use up a budget, so check admission again before acting on an old proof. The [LeanLTL guide](../../docs/leanltl.md) explains the semantics.

The [temporal examples](TemporalStress.lean) cover ordering, windows, scope,
revocation and proof reuse:

```sh
lake build LeanGuard.Experimental.TemporalRepair
lake env lean examples/repair/TemporalStress.lean
```

The [Dogwood examples](../dogwood/README.md#repair-experiments) include a quantity
repair and proofs that some repair contracts cannot be met at all.
