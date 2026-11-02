import LeanGuard.MultiAgent
import LeanLTL.Logics.LTLf
import LeanLTL.Logics.LTL

/-! Forward-time task contracts, separate from reverse-history admission guards.
These use LeanLTL's operators directly on chronological task-state traces.
Observed snapshots may skip intermediate states. They do not invent remote progress. -/
namespace LeanGuard.MultiAgent.TaskContracts
open LeanLTL

def phaseIs (phase : TaskPhase) : TraceSet TaskPhase := TraceSet.of (· = phase)

def step : TraceSet TaskPhase := TraceSet.forall fun phase ↦
  (phaseIs phase).imp (TraceSet.of fun next ↦ taskTransition phase next = true).wnext

def lifecycle : TraceSet TaskPhase := step.globally
def completed : TraceSet TaskPhase := phaseIs .completed
def resolved : TraceSet TaskPhase := TraceSet.of fun phase ↦ phase.terminal = true ∨
  phase = .inputRequired ∨ phase = .authRequired
def eventuallyCompleted : TraceSet TaskPhase := completed.finally
def eventuallyResolved : TraceSet TaskPhase := resolved.finally

/-- Weak next handles a finite trace's last state without inventing a successor.
The induction theorem is LeanLTL's, on finite or infinite chronological traces. -/
theorem terminal_persists (t : Trace TaskPhase) (phase : TaskPhase)
    (done : phase.terminal = true) (initial : t ⊨ phaseIs phase)
    (safe : t ⊨ lifecycle) : t ⊨ (phaseIs phase).globally := by
  have propagate : TraceSet.sem_imp step ((phaseIs phase).imp (phaseIs phase).wnext) := by
    intro suffix transition current next
    exact terminal_absorbing phase _ done (transition phase current next)
  exact TraceSet.globally_induction t initial (TraceSet.globally_mono propagate t safe)

theorem completion_implies_resolution : TraceSet.sem_imp eventuallyCompleted eventuallyResolved := by
  apply TraceSet.finally_mono
  intro t h
  have same : t.toFun 0 = .completed := h
  exact Or.inl (by rw [same]; rfl)

def phases : List TaskPhase := [.submitted, .working, .inputRequired, .authRequired,
  .completed, .canceled, .rejected, .failed]

/-- The same contract in upstream standard finite-trace LTL syntax. -/
def stepSyntax : LTLf.Formula TaskPhase := phases.foldr (fun phase rest ↦
  ((LTLf.Formula.var (· = phase)).imp
    (LTLf.Formula.var fun next ↦ taskTransition phase next = true).wnext).and rest) .true

def lifecycleSyntax : LTLf.Formula TaskPhase := stepSyntax.globally

theorem step_syntax_meaning : LTLf.toLeanLTL stepSyntax = step := by
  apply TraceSet.ext
  intro t
  simp only [stepSyntax, phases, List.foldr_cons, List.foldr_nil,
    LTLf.toLeanLTL_and, LTLf.toLeanLTL_imp, LTLf.toLeanLTL_wnext,
    LTLf.toLeanLTL_true, TraceSet.and, TraceSet.imp, TraceSet.map₂, TraceSet.true,
    TraceSet.const, step, TraceSet.forall, phaseIs]
  constructor
  · rintro ⟨a, b, c, d, e, f, g, h, _⟩ phase
    cases phase <;> assumption
  · intro h
    exact ⟨h _, h _, h _, h _, h _, h _, h _, h _, trivial⟩

/-- Use LeanLTL's proved finite-LTL embedding, not a second finite-LTL semantics. -/
theorem finite_lifecycle_correct (t : LTLf.Trace TaskPhase) :
    LTLf.sat t lifecycleSyntax ↔ t.trace ⊨ lifecycle := by
  rw [LTLf.equisat, lifecycleSyntax, LTLf.toLeanLTL_globally, step_syntax_meaning]
  rfl

theorem step_unshift (head : TaskPhase) (tail : Trace TaskPhase) :
    (Trace.unshift head tail ⊨ step) ↔ taskTransition head (tail.toFun 0) = true := by
  change (∀ phase, (Trace.unshift head tail ⊨ phaseIs phase) →
    (Trace.unshift head tail ⊨ (TraceSet.of fun next ↦ taskTransition phase next = true).wnext)) ↔ _
  simp [phaseIs, TraceSet.of, TraceSet.wshift_eq_wshift, TraceSet.unshift_sat_wnext_iff]

theorem step_singleton (phase : TaskPhase) : Trace.singleton phase ⊨ step := by
  intro current _
  simp [TraceSet.wshift_eq_wshift, TraceSet.singleton_sat_wshift]

theorem lifecycle_singleton (phase : TaskPhase) : Trace.singleton phase ⊨ lifecycle := by
  rw [lifecycle, TraceSet.globally_eq_globally, TraceSet.globally_eq_and_globally]
  exact ⟨step_singleton phase, by simp [TraceSet.singleton_sat_wshift]⟩

theorem lifecycle_unshift (head : TaskPhase) (tail : Trace TaskPhase) :
    (Trace.unshift head tail ⊨ lifecycle) ↔
      taskTransition head (tail.toFun 0) = true ∧ (tail ⊨ lifecycle) := by
  rw [lifecycle, TraceSet.globally_eq_globally, TraceSet.unshift_sat_globally_iff, step_unshift]

/-- Exhaustive triples can be checked constructively via this proved equivalence. -/
theorem lifecycle_triple (a b c : TaskPhase) :
    (Trace.unshift a (Trace.unshift b (Trace.singleton c)) ⊨ lifecycle) ↔
      taskTransition a b = true ∧ taskTransition b c = true := by
  simp only [lifecycle_unshift, Trace.toFun_unshift_zero, Trace.singleton_toFun_zero_eq,
    lifecycle_singleton, and_true]

instance tripleDecidable (a b c : TaskPhase) :
    Decidable (Trace.unshift a (Trace.unshift b (Trace.singleton c)) ⊨ lifecycle) :=
  decidable_of_iff _ (lifecycle_triple a b c).symm

/-- A nonterminating remote worker satisfies lifecycle safety while violating
eventual completion. This is a checked counterexample to an unconditional liveness claim. -/
def foreverWorking : Trace TaskPhase where
  toFun? _ := some .working
  length := ⊤
  nempty := by simp
  defined := by simp

theorem foreverWorking_safe : foreverWorking ⊨ lifecycle := by
  simp only [lifecycle, TraceSet.globally_eq_globally, TraceSet.sat_globally_iff,
    TraceSet.sat_wshift_iff]
  intro i hi phase current next
  have same : TaskPhase.working = phase := current
  cases same
  rfl

theorem foreverWorking_not_completed : ¬ (foreverWorking ⊨ eventuallyCompleted) := by
  simp only [eventuallyCompleted, TraceSet.finally_eq_finally,
    TraceSet.sat_finally_iff, TraceSet.sat_sshift_iff]
  rintro ⟨i, hi, complete⟩
  have impossible : TaskPhase.working = .completed := complete
  contradiction

def completionSyntax : LTL.Formula TaskPhase := (LTL.Formula.var (· = .completed)).eventually

theorem infinite_completion_correct (t : LTL.Trace TaskPhase) :
    LTL.sat t completionSyntax ↔ t.trace ⊨ eventuallyCompleted := by
  exact LTL.equisat completionSyntax t

end LeanGuard.MultiAgent.TaskContracts
