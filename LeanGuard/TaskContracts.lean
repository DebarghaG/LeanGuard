import LeanGuard.MultiAgent
import LeanLTL.Logics.LTLf
import LeanLTL.Logics.LTL

/-! Contracts on a remote task's lifecycle, stated in LeanLTL over traces that run forward
in time (admission formulas run backward). A trace is the sequence of phases we observed,
which may skip some. -/
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

/-- Once a trace satisfying the lifecycle reaches a terminal phase, it stays there. Holds for
finite and infinite traces; weak next makes the last state of a finite trace unconstrained. -/
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

/-- The same contract written in LeanLTL's finite-trace `LTLf` syntax. -/
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

/-- The `LTLf` version means the same as the `TraceSet` version, via LeanLTL's `LTLf.equisat`. -/
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

/-- A three-phase trace obeys the lifecycle exactly when both of its steps are allowed.
The tests use this to check every triple by computation. -/
theorem lifecycle_triple (a b c : TaskPhase) :
    (Trace.unshift a (Trace.unshift b (Trace.singleton c)) ⊨ lifecycle) ↔
      taskTransition a b = true ∧ taskTransition b c = true := by
  simp only [lifecycle_unshift, Trace.toFun_unshift_zero, Trace.singleton_toFun_zero_eq,
    lifecycle_singleton, and_true]

instance tripleDecidable (a b c : TaskPhase) :
    Decidable (Trace.unshift a (Trace.unshift b (Trace.singleton c)) ⊨ lifecycle) :=
  decidable_of_iff _ (lifecycle_triple a b c).symm

/-- A worker that stays `working` forever obeys the lifecycle but never completes, so
the lifecycle contract alone cannot promise that a task finishes. -/
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
