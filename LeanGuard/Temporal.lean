import LeanGuard.Core
import LeanLTL.TraceSet.Defs

/-!
# LeanLTL semantics of the native temporal language

Time runs toward the past: a state is the remaining newest-first history, so atoms
retain access to their full suffix. A final empty-history state makes the embedding
total, including for empty inputs. Window predicates exclude that terminal state.
`previous`, `once`, and `since` use LeanLTL's strong next, finally, and until.
Metric operators freeze their own origin; scope operators re-embed projected history.
The translation does not call either `evaluate` or `Holds`.
-/

namespace LeanGuard
open LeanLTL

/-- The finite trace of all suffixes, including the terminal empty history. -/
def historyTrace (h : History) : Trace History where
  toFun? i := if i ≤ h.length then some (h.drop i) else none
  length := ↑(h.length + 1)
  nempty := by simp
  defined := by
    intro i
    simp only [ENat.natCast_lt_natCast, Nat.lt_succ_iff]
    split <;> simp_all


/-- Independent metric specification: inclusive age bounds, with future events excluded. -/
def InPastWindow (w : Option Nat) (origin past : History) : Prop :=
  ∃ now older, origin.head? = some now ∧ past.head? = some older ∧
    older.time ≤ now.time ∧ ∀ limit ∈ w, now.time - older.time ≤ limit


/-- A state predicate with an origin frozen outside LeanLTL's temporal operator. -/
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


/-- Deny-overrides authorization, expressed using LeanLTL connectives and quantifiers. -/
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
