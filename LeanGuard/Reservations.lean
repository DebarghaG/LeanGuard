import LeanGuard.Policy

namespace LeanGuard

theorem confirmedWithin_preserves (c : Context) (seconds : Nat)
    (h : evaluate (atomValue c) (confirmedWithin seconds) c.history = true) :
    evaluate (atomValue c) confirmed c.history = true := by
  have holds := (evaluate_correct (atomValue c) (confirmedWithin seconds) c.history).mp h
  exact (evaluate_correct (atomValue c) confirmed c.history).mpr holds.1

theorem confirmedWithin_recent_witness (c : Context) (seconds : Nat)
    (h : evaluate (atomValue c) (confirmedWithin seconds) c.history = true) :
    ∃ i ∈ List.range (projectAtHead .conversation c.history).length,
      inWindow (some seconds) (projectAtHead .conversation c.history)
        ((projectAtHead .conversation c.history).drop i) = true ∧
      Holds (atomValue c) confirmedEvent ((projectAtHead .conversation c.history).drop i) := by
  exact ((evaluate_correct _ _ _).mp h).2

/-- An accepted confirmation has no matching dispatch in its scoped prior history. -/
theorem confirmation_not_consumed (c : Context)
    (accepted : evaluate (atomValue c) confirmed c.history = true) :
    ¬ Holds (atomValue c) (.once none usedConfirmation)
      (projectAtHead .conversation c.history).tail := by
  have holds := (evaluate_correct (atomValue c) confirmed c.history).mp accepted
  exact holds.2.2

/-- Confirmation cannot be satisfied without a real matching prior witness. -/
theorem confirmation_has_witness (c : Context)
    (accepted : evaluate (atomValue c) confirmed c.history = true) :
    ∃ i ∈ List.range (projectAtHead .conversation c.history).tail.length,
      Holds (atomValue c) confirmedEvent
        ((projectAtHead .conversation c.history).tail.drop i) := by
  have holds := (evaluate_correct (atomValue c) confirmed c.history).mp accepted
  obtain ⟨i, mem, witness, _⟩ := holds.2.1
  exact ⟨i, mem, witness.2⟩

theorem sumEvents_fold (h : History) (initial : Nat) :
    h.foldl (fun n e ↦ n + e.amount) initial =
      initial + h.foldl (fun n e ↦ n + e.amount) 0 := by
  induction h generalizing initial with
  | nil => simp
  | cons e h ih =>
    simp only [List.foldl_cons, Nat.zero_add]
    rw [ih (initial + e.amount), ih e.amount]
    omega

theorem countEvents_cons (e : Event) (h : History) (p : Event → Bool) (hp : p e = true) :
    countEvents (e :: h) p = countEvents h p + 1 := by
  simp [countEvents, hp]

theorem sumEvents_cons (e : Event) (h : History) (p : Event → Bool) (hp : p e = true) :
    sumEvents (e :: h) p = sumEvents h p + e.amount := by
  simp only [sumEvents, List.filter_cons, hp, ↓reduceIte, List.foldl_cons, Nat.zero_add]
  rw [sumEvents_fold]
  omega

/-- Reserving an admitted call preserves both the count and amount bounds, including
the new dispatch. Unknown outcomes retain their reservation; they do not refund quota. -/
theorem quota_reservation_bound (c : Context) (calls amount window : Nat)
    (allowed : evaluate (atomValue c) (quota calls amount window) c.history = true) :
    countEvents (reserve true c.request c.history) (quotaMatches c.request window) ≤ calls ∧
    sumEvents (reserve true c.request c.history) (quotaMatches c.request window) ≤ amount := by
  have limits : countEvents c.history (quotaMatches c.request window) < calls ∧
      sumEvents c.history (quotaMatches c.request window) + c.request.amount ≤ amount := by
    simpa [evaluate, atomValue, quota, check, Except.toOption] using allowed
  have matching : quotaMatches c.request window { c.request with kind := "dispatch" } = true := by
    simp [quotaMatches, samePrincipal]
  simp only [reserve, ↓reduceIte]
  rw [countEvents_cons _ _ _ matching, sumEvents_cons _ _ _ matching]
  exact ⟨by omega, limits.2⟩

end LeanGuard
