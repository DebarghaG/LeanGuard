import LeanGuard.Query
import LeanGuard.TemporalProofs

namespace LeanGuard

/-- Query membership is exactly eventual satisfaction of its LeanLTL witness predicate. -/
theorem query_leanLTL_membership (q : WindowQuery) (c : Context) (e : Event) :
    e ∈ q.events c ↔
      (historyTrace c.history ⊨ (q.witnessLeanLTL c.request e).finally) := by
  rw [query_membership, historyTrace_finally]
  simp only [WindowQuery.witnessLeanLTL, LeanLTL.TraceSet.and_eq_inf,
    LeanLTL.TraceSet.sat_and_iff, LeanLTL.TraceSet.of, historyTrace_toFun,
    List.drop_zero, pastWindow_sat, List.head?_drop]
  constructor
  · rintro ⟨mem, matched⟩
    obtain ⟨i, hi⟩ := List.mem_iff_getElem?.mp mem
    have bound := (List.getElem?_eq_some_iff.mp hi).1
    have facts : historyKey q.scope e = historyKey q.scope c.request ∧
        e.action = q.action ∧ e.kind = q.basis.kind ∧
        e.time ≤ c.request.time ∧ c.request.time - e.time ≤ q.seconds := by
      simpa [WindowQuery.matches, and_assoc] using matched
    refine ⟨i, Nat.le_of_lt bound, ⟨hi, facts.1, facts.2.1, facts.2.2.1⟩, ?_⟩
    apply (inWindow_correct _ _ _).mpr
    exact ⟨c.request, e, rfl, by simpa using hi, facts.2.2.2.1,
      by simpa using facts.2.2.2.2⟩
  · rintro ⟨i, _, ⟨hi, scope, action, kind⟩, window⟩
    have hw := (inWindow_correct _ _ _).mp window
    have age : e.time ≤ c.request.time ∧ c.request.time - e.time ≤ q.seconds := by
      simpa [InPastWindow, hi] using hw
    exact ⟨List.mem_iff_getElem?.mpr ⟨i, hi⟩,
      by simp [WindowQuery.matches, scope, action, kind, age.1, age.2]⟩

end LeanGuard
