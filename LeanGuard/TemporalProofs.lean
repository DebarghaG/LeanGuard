import LeanGuard.Temporal
import LeanLTL.TraceSet.Basic

/-! Soundness and completeness of native evaluation for the LeanLTL translation. -/

namespace LeanGuard
open LeanLTL

@[simp] theorem historyTrace_length (h : History) :
    (historyTrace h).length = ↑(h.length + 1) := rfl

@[simp] theorem historyTrace_bound (h : History) (i : Nat) :
    (i : ℕ∞) < (historyTrace h).length ↔ i ≤ h.length := by
  exact ENat.natCast_lt_natCast.trans Nat.lt_succ_iff

@[simp] theorem historyTrace_finite (h : History) : (historyTrace h).Finite := by
  simp [Trace.Finite]

@[simp] theorem historyTrace_toFun (h : History) (i : Nat)
    (hi : (i : ℕ∞) < (historyTrace h).length) :
    (historyTrace h).toFun i hi = h.drop i := by
  have bound : i ≤ h.length := by simpa only [historyTrace_bound] using hi
  simp [Trace.toFun, historyTrace, bound]

/-- LeanLTL shift is exactly dropping observations, including at the terminal state. -/
theorem historyTrace_shift (h : History) (i : Nat)
    (hi : (i : ℕ∞) < (historyTrace h).length) :
    (historyTrace h).shift i hi = historyTrace (h.drop i) := by
  have bound : i ≤ h.length := by simpa only [historyTrace_bound] using hi
  apply Trace.ext
  · simp only [Trace.shift, historyTrace_length, List.length_drop]
    rw [← ENat.natCast_sub]
    congr 1
    omega
  · intro n hn hn'
    rw [Trace.toFun_shift, historyTrace_toFun, historyTrace_toFun, List.drop_drop]
    simp [Nat.add_comm]

@[simp] theorem historyTrace_toFun! (h : History) (i : Nat) (hi : i ≤ h.length) :
    (historyTrace h).toFun! i = h.drop i := by
  simp [Trace.toFun!, historyTrace, hi]

theorem inWindow_correct (w : Option Nat) (origin past : History) :
    inWindow w origin past = true ↔ InPastWindow w origin past := by
  cases origin <;> cases past <;> cases w <;> simp [inWindow, InPastWindow]

theorem pastWindow_sat (w : Option Nat) (origin h : History) :
    (historyTrace h ⊨ pastWindow w origin) ↔ inWindow w origin h = true := by
  simp [pastWindow, TraceSet.of, ← inWindow_correct]

theorem inWindow_drop_bound (w : Option Nat) (h : History) (i : Nat)
    (hw : inWindow w h (h.drop i) = true) : i < h.length := by
  by_contra hn
  have : h.drop i = [] := List.drop_eq_nil_iff.mpr (by omega)
  rw [this] at hw
  cases h <;> simp [inWindow] at hw

theorem historyTrace_snext (f : TraceSet History) (h : History) :
    (historyTrace h ⊨ f.snext) ↔ h ≠ [] ∧ (historyTrace h.tail ⊨ f) := by
  change (∃ hi : ((1 : Nat) : ℕ∞) < (historyTrace h).length,
    (historyTrace h).shift 1 hi ⊨ f) ↔ _
  constructor
  · rintro ⟨hi, hf⟩
    rw [historyTrace_shift] at hf
    exact ⟨by cases h <;> simp_all, by simpa using hf⟩
  · rintro ⟨hne, hf⟩
    have hi : ((1 : Nat) : ℕ∞) < (historyTrace h).length := by
      rw [historyTrace_bound]
      cases h <;> simp_all
    exact ⟨hi, by simpa [historyTrace_shift] using hf⟩

theorem historyTrace_finally (f : TraceSet History) (h : History) :
    (historyTrace h ⊨ f.finally) ↔
      ∃ i, i ≤ h.length ∧ (historyTrace (h.drop i) ⊨ f) := by
  simp only [TraceSet.finally_eq_finally, TraceSet.sat_finally_iff,
    TraceSet.sat_sshift_iff, historyTrace_shift, historyTrace_bound]
  simp

theorem historyTrace_until (p q : TraceSet History) (h : History) :
    (historyTrace h ⊨ p.until q) ↔
      ∃ i, i ≤ h.length ∧ (historyTrace (h.drop i) ⊨ q) ∧
        ∀ j, j < i → (historyTrace (h.drop j) ⊨ p) := by
  simp only [TraceSet.until_eq_until, TraceSet.sat_until_iff, TraceSet.sat_wshift_iff,
    TraceSet.sat_sshift_iff, historyTrace_shift, historyTrace_bound]
  constructor
  · rintro ⟨i, hp, hi, hq⟩
    have bound : i ≤ h.length := by simpa only [historyTrace_bound] using hi
    exact ⟨i, bound, hq, fun j hj ↦ hp j hj (by omega)⟩
  · rintro ⟨i, hi, hq, hp⟩
    exact ⟨i, fun j hj _ ↦ hp j hj, by simpa only [historyTrace_bound] using hi, hq⟩

/-- Every native constructor agrees with the completed vendored LeanLTL semantics. -/
theorem holds_iff_leanLTL (atom : α → History → Bool) (p : Formula α) (h : History) :
    Holds atom p h ↔ (historyTrace h ⊨ p.toLeanLTL atom) := by
  induction p generalizing h with
  | atom a => simp [Holds, Formula.toLeanLTL, TraceSet.of]
  | top => rfl
  | bot => rfl
  | neg p ih => exact not_congr (ih h)
  | conj p q ihp ihq => exact and_congr (ihp h) (ihq h)
  | disj p q ihp ihq => exact or_congr (ihp h) (ihq h)
  | previous w p ih =>
    change _ ↔ (historyTrace h ⊨
      ((pastWindow w ((historyTrace h).toFun 0)).and (p.toLeanLTL atom)).snext)
    simp only [historyTrace_toFun, List.drop_zero, historyTrace_snext,
      TraceSet.and_eq_inf, TraceSet.sat_and_iff, pastWindow_sat, Holds, ih]
    constructor
    · intro hp
      exact ⟨by intro he; simp [he, inWindow] at hp, hp⟩
    · exact And.right
  | once w p ih =>
    change _ ↔ (historyTrace h ⊨
      ((pastWindow w ((historyTrace h).toFun 0)).and (p.toLeanLTL atom)).finally)
    simp only [historyTrace_toFun, List.drop_zero, historyTrace_finally,
      TraceSet.and_eq_inf, TraceSet.sat_and_iff, pastWindow_sat, Holds, List.mem_range, ih]
    constructor
    · rintro ⟨i, hi, hw, hp⟩; exact ⟨i, Nat.le_of_lt hi, hw, hp⟩
    · rintro ⟨i, _, hw, hp⟩; exact ⟨i, inWindow_drop_bound w h i hw, hw, hp⟩
  | since w p q ihp ihq =>
    change _ ↔ (historyTrace h ⊨ (p.toLeanLTL atom).until
      ((pastWindow w ((historyTrace h).toFun 0)).and (q.toLeanLTL atom)))
    simp only [historyTrace_toFun, List.drop_zero, historyTrace_until,
      TraceSet.and_eq_inf, TraceSet.sat_and_iff, pastWindow_sat, Holds, List.mem_range,
      ihp, ihq]
    constructor
    · rintro ⟨i, hi, hq, hp⟩; exact ⟨i, Nat.le_of_lt hi, hq, hp⟩
    · rintro ⟨i, _, hq, hp⟩; exact ⟨i, inWindow_drop_bound w h i hq.1, hq, hp⟩
  | within scope p ih =>
    simpa [Holds, Formula.toLeanLTL] using ih (projectAtHead scope h)

/-- Soundness and completeness of the actual Boolean evaluator against LeanLTL. -/
theorem evaluate_leanLTL_correct (atom : α → History → Bool) (p : Formula α)
    (h : History) : evaluate atom p h = true ↔ (historyTrace h ⊨ p.toLeanLTL atom) :=
  (evaluate_correct atom p h).trans (holds_iff_leanLTL atom p h)

/-- Native evaluation is a constructive decision procedure for embedded LeanLTL formulas. -/
instance decidableLeanLTL (atom : α → History → Bool) (p : Formula α) (h : History) :
    Decidable (historyTrace h ⊨ p.toLeanLTL atom) :=
  decidable_of_iff (evaluate atom p h = true) (evaluate_leanLTL_correct atom p h)

theorem evaluate_eq_decide_leanLTL (atom : α → History → Bool) (p : Formula α)
    (h : History) : evaluate atom p h = decide (historyTrace h ⊨ p.toLeanLTL atom) := by
  apply Bool.eq_iff_iff.mpr
  simp only [decide_eq_true_eq, evaluate_leanLTL_correct]

/-- LeanLTL semantic entailments can discharge native policy implications. -/
theorem evaluate_of_leanLTL_imp (atom : α → History → Bool) (p q : Formula α)
    (imp : TraceSet.sem_imp (p.toLeanLTL atom) (q.toLeanLTL atom)) (h : History)
    (hp : evaluate atom p h = true) : evaluate atom q h = true :=
  (evaluate_leanLTL_correct atom q h).mpr
    (imp _ ((evaluate_leanLTL_correct atom p h).mp hp))

/-- Rewrites proved in LeanLTL preserve executable verdicts on every history. -/
theorem evaluate_eq_of_leanLTL_eq (atom : α → History → Bool) (p q : Formula α)
    (eq : p.toLeanLTL atom = q.toLeanLTL atom) (h : History) :
    evaluate atom p h = evaluate atom q h := by
  apply Bool.eq_iff_iff.mpr
  simp only [evaluate_leanLTL_correct, eq]

/-- LeanLTL's eventuality distribution law also holds for anchored metric windows. -/
theorem toLeanLTL_once_disj (atom : α → History → Bool) (w : Option Nat)
    (p q : Formula α) :
    (Formula.once w (.disj p q)).toLeanLTL atom =
      (Formula.disj (.once w p) (.once w q)).toLeanLTL atom := by
  apply LeanLTL.TraceSet.ext
  intro t
  change (t ⊨ ((pastWindow w (t.toFun 0)).and
    ((p.toLeanLTL atom).or (q.toLeanLTL atom))).finally) ↔
      (t ⊨ ((pastWindow w (t.toFun 0)).and (p.toLeanLTL atom)).finally) ∨
      (t ⊨ ((pastWindow w (t.toFun 0)).and (q.toLeanLTL atom)).finally)
  simp only [TraceSet.and_eq_inf, TraceSet.or_eq_sup, inf_sup_left,
    TraceSet.finally_eq_finally, TraceSet.finally_or_distrib, TraceSet.sat_or_iff]

theorem evaluate_once_disj (atom : α → History → Bool) (w : Option Nat)
    (p q : Formula α) (h : History) :
    evaluate atom (.once w (.disj p q)) h =
      evaluate atom (.disj (.once w p) (.once w q)) h :=
  evaluate_eq_of_leanLTL_eq atom _ _ (toLeanLTL_once_disj atom w p q) h

theorem authorize_leanLTL_correct (rules : List (Rule α)) (atom : α → History → Bool)
    (action : String) (h : History) : authorize rules atom action h = true ↔
      (historyTrace h ⊨ authorizationLeanLTL rules atom action) := by
  simp only [authorize, permitted, requirementsMet, forbidden, Bool.and_eq_true,
    List.any_eq_true, List.all_eq_true, Bool.or_eq_true, Bool.not_eq_true',
    beq_iff_eq, Bool.eq_false_iff, evaluate_leanLTL_correct,
    authorizationLeanLTL, TraceSet.and, TraceSet.map₂, TraceSet.exists, TraceSet.const,
    TraceSet.forall, TraceSet.imp, TraceSet.not, TraceSet.map]
  simp only [ne_eq, Bool.and_eq_true, List.any_eq_true, beq_iff_eq,
    evaluate_leanLTL_correct]
  constructor
  · rintro ⟨⟨⟨r, mem, ⟨scope, effect⟩, hp⟩, req⟩, forb⟩
    refine ⟨⟨r, ⟨mem, scope, effect⟩, hp⟩, ?_, ?_⟩
    · rintro r ⟨mem, scope, effect⟩
      exact (req r mem).resolve_left (by simp [scope, effect])
    · rintro r ⟨mem, scope, effect⟩ hp
      exact forb ⟨r, mem, ⟨scope, effect⟩, hp⟩
  · rintro ⟨⟨r, ⟨mem, scope, effect⟩, hp⟩, req, forb⟩
    refine ⟨⟨⟨r, mem, ⟨scope, effect⟩, hp⟩, ?_⟩, ?_⟩
    · intro r mem
      by_cases active : r.applies action = true ∧ r.effect = .require
      · exact Or.inr (req r ⟨mem, active⟩)
      · exact Or.inl active
    · rintro ⟨r, mem, ⟨scope, effect⟩, hp⟩
      exact forb r ⟨mem, scope, effect⟩ hp

theorem authorized_requirement_leanLTL (rules : List (Rule α))
    (atom : α → History → Bool) (action : String) (h : History) (r : Rule α)
    (mem : r ∈ rules) (scope : r.applies action = true) (effect : r.effect = .require)
    (allowed : authorize rules atom action h = true) :
    historyTrace h ⊨ r.condition.toLeanLTL atom :=
  ((authorize_leanLTL_correct rules atom action h).mp allowed).2.1 r ⟨mem, scope, effect⟩

theorem authorized_no_forbid_leanLTL (rules : List (Rule α))
    (atom : α → History → Bool) (action : String) (h : History) (r : Rule α)
    (mem : r ∈ rules) (scope : r.applies action = true) (effect : r.effect = .forbid)
    (allowed : authorize rules atom action h = true) :
    ¬ (historyTrace h ⊨ r.condition.toLeanLTL atom) :=
  ((authorize_leanLTL_correct rules atom action h).mp allowed).2.2 r ⟨mem, scope, effect⟩

theorem authorized_permit_leanLTL (rules : List (Rule α)) (atom : α → History → Bool)
    (action : String) (h : History) (allowed : authorize rules atom action h = true) :
    ∃ r ∈ rules, r.applies action = true ∧ r.effect = .permit ∧
      (historyTrace h ⊨ r.condition.toLeanLTL atom) := by
  obtain ⟨r, ⟨mem, scope, effect⟩, hp⟩ :=
    ((authorize_leanLTL_correct rules atom action h).mp allowed).1
  exact ⟨r, mem, scope, effect, hp⟩

/-- Replaying chronological observations gives exactly their reversed LeanLTL history. -/
theorem replay_leanLTL_correct (m : Monitor) (events : List Event)
    (atom : α → History → Bool) (p : Formula α) :
    evaluate atom p (m.run events).history = true ↔
      (historyTrace (events.reverse ++ m.history) ⊨ p.toLeanLTL atom) := by
  rw [evaluate_leanLTL_correct, replay_history]

end LeanGuard
