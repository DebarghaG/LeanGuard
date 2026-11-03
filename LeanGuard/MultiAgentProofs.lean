import LeanGuard.MultiAgent
import LeanGuard.PolicyProofs

namespace LeanGuard.MultiAgent

theorem response_binding_immutable (s next : State) (request : String)
    (established target : ResponseTarget) (bound : s.response request = some established)
    (accepted : s.bindResponse request target = .ok next) : target = established := by
  by_cases same : established = target
  · exact same.symm
  · simp [State.bindResponse, bound, same] at accepted

/-- The LeanLTL meaning of the multi-agent decision: the policy with its error gate,
the grant formulas, and a successful ledger check. -/
def admissionLeanLTL (pack : PolicyPack) (c : Context)
    (authority : Except String (List Grant)) : LeanLTL.TraceSet History :=
  (pack.toLeanLTL c).and (match authority with
    | .error _ => LeanLTL.TraceSet.false
    | .ok chain => (historyPack c.request.action chain).toLeanLTL c)

theorem decision_leanLTL_correct (pack : PolicyPack) (c : Context)
    (authority : Except String (List Grant)) :
    (decideAdmission pack c authority).allow = true ↔
      (historyTrace c.history ⊨ admissionLeanLTL pack c authority) := by
  cases authority <;>
    simp [decideAdmission, restrict, admissionLeanLTL, LeanLTL.TraceSet.and,
      LeanLTL.TraceSet.map₂, LeanLTL.TraceSet.false, LeanLTL.TraceSet.const,
      LeanGuard.decision_leanLTL_correct]

theorem admission_preserves_policy (pack : PolicyPack) (c : Context)
    (authority : Except String (List Grant)) (h : (decideAdmission pack c authority).allow = true) :
    historyTrace c.history ⊨ pack.toLeanLTL c :=
  ((decision_leanLTL_correct pack c authority).mp h).1

theorem authorityHistory_member (chain : List Grant) (g : Grant) (mem : g ∈ chain)
    (c : Context) (h : evaluate (atomValue c) (authorityHistory chain) c.history = true) :
    evaluate (atomValue c) (activeGrant g) c.history = true := by
  induction chain with
  | nil => simp at mem
  | cons first rest ih =>
    simp only [authorityHistory, List.foldr_cons, evaluate, Bool.and_eq_true] at h
    rcases List.mem_cons.mp mem with eq | mem
    · simpa [eq] using h.1
    · exact ih mem h.2

/-- If a call is admitted, each ancestor grant was issued earlier and revoked at no later
position. Events from other workflows are projected away and can't affect this. -/
theorem activeGrant_witness (g : Grant) (c : Context)
    (h : evaluate (atomValue c) (activeGrant g) c.history = true) :
    ∃ i ∈ List.range (projectAtHead .workflow c.history).tail.length,
      Holds (atomValue c) (grantEvent g) ((projectAtHead .workflow c.history).tail.drop i) ∧
      ∀ j ∈ List.range i,
        ¬ Holds (atomValue c) (revokeEvent g) ((projectAtHead .workflow c.history).tail.drop j) := by
  have holds := (evaluate_correct _ _ _).mp h
  obtain ⟨i, mem, witness, unrevoked⟩ := holds.2
  exact ⟨i, mem, witness.2, unrevoked⟩

theorem admission_ancestor_witness (pack : PolicyPack) (c : Context) (chain : List Grant)
    (g : Grant) (mem : g ∈ chain) (h : (decideAdmission pack c (.ok chain)).allow = true) :
    evaluate (atomValue c) (activeGrant g) c.history = true := by
  have temporal := ((decision_leanLTL_correct pack c (.ok chain)).mp h).2
  have accepted := (LeanGuard.decision_leanLTL_correct _ _).mpr temporal
  have requirement := authorized_requirement (historyPack c.request.action chain).rules
    (atomValue c) c.request.action c.history
    (require "agents.lifecycle" [c.request.action] (authorityHistory chain)
      "prior, unrevoked ancestor grants")
    (by simp [historyPack]) (by simp [Rule.applies, require]) rfl
    (decision_sound _ _ accepted)
  exact authorityHistory_member chain g mem c ((evaluate_correct _ _ _).mpr requirement)

end LeanGuard.MultiAgent
