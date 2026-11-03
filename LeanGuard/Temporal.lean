import LeanGuard.Core
import LeanLTL.TraceSet.Defs

/-!
# LeanLTL semantics of the native temporal language

A history becomes a LeanLTL trace that runs toward the past: each state is the rest of
the newest-first history, so an atom can still look at everything older. The trace ends
in an empty history, so even an empty input has a trace; window predicates never match
that last state. `previous`, `once` and `since` become strong next, finally and until.
A metric operator measures time from the position where it is evaluated, and `within`
re-embeds the projected history. The translation is written without reference to
`evaluate` or `Holds`.
-/

namespace LeanGuard
open LeanLTL

/-- The trace of every suffix of `h`, ending with the empty history. -/
def historyTrace (h : History) : Trace History where
  toFun? i := if i ≤ h.length then some (h.drop i) else none
  length := ↑(h.length + 1)
  nempty := by simp
  defined := by
    intro i
    simp only [ENat.natCast_lt_natCast, Nat.lt_succ_iff]
    split <;> simp_all


/-- The event is not in the future and is at most `window` seconds old (inclusive). -/
def InPastWindow (w : Option Nat) (origin past : History) : Prop :=
  ∃ now older, origin.head? = some now ∧ past.head? = some older ∧
    older.time ≤ now.time ∧ ∀ limit ∈ w, now.time - older.time ≤ limit


/-- A window predicate whose reference time is fixed before the temporal operator shifts. -/
def pastWindow (w : Option Nat) (origin : History) : TraceSet History :=
  TraceSet.of (InPastWindow w origin)

def Formula.toLeanLTL (atom : α → History → Bool) : Formula α → TraceSet History
  | .atom a => TraceSet.of (fun h ↦ atom a h = true)
  | .top => TraceSet.true
  | .bot => TraceSet.false
  | .neg p => (p.toLeanLTL atom).not
  | .conj p q => (p.toLeanLTL atom).and (q.toLeanLTL atom)
  | .disj p q => (p.toLeanLTL atom).or (q.toLeanLTL atom)
  | .previous w p => ⟨fun t ↦
      t ⊨ ((pastWindow w (t.toFun 0)).and (p.toLeanLTL atom)).snext⟩
  | .once w p => ⟨fun t ↦
      t ⊨ ((pastWindow w (t.toFun 0)).and (p.toLeanLTL atom)).finally⟩
  | .since w p q => ⟨fun t ↦
      t ⊨ (p.toLeanLTL atom).until
        ((pastWindow w (t.toFun 0)).and (q.toLeanLTL atom))⟩
  | .within scope p => ⟨fun t ↦
      historyTrace (projectAtHead scope (t.toFun 0)) ⊨ p.toLeanLTL atom⟩


/-- Authorization in LeanLTL: some permit holds, every requirement holds, and no forbid holds. -/
def authorizationLeanLTL (rules : List (Rule α)) (atom : α → History → Bool)
    (action : String) : TraceSet History :=
  (TraceSet.exists fun r : Rule α ↦
    (TraceSet.const (r ∈ rules ∧ r.applies action = true ∧ r.effect = .permit)).and
      (r.condition.toLeanLTL atom)).and
    ((TraceSet.forall fun r : Rule α ↦
      (TraceSet.const (r ∈ rules ∧ r.applies action = true ∧ r.effect = .require)).imp
        (r.condition.toLeanLTL atom)).and
      (TraceSet.forall fun r : Rule α ↦
        (TraceSet.const (r ∈ rules ∧ r.applies action = true ∧ r.effect = .forbid)).imp
          (r.condition.toLeanLTL atom).not))

end LeanGuard
