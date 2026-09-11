import Guide
import LeanGuard.Experimental.TemporalRepair
import LeanGuard.Audit

/-! Repairs preserve the requested action and trusted evidence. A quantity reduction is
permitted only by the explicit example contract; it is not inferred from a policy denial. -/

namespace DogwoodGuide.Repairs
open Lean LeanGuard LeanGuard.Experimental

def sale (shares : Nat) : Context :=
  let args := Json.mkObj [("stock", .str "MSFT"), ("shares", toJson shares)]
  let request : Event := {
    id := "sale", time := 0, kind := "request", principal := "alice", session := "one",
    action := "SellShares", resource := "gateway", binding := "", inputJson := args.compress
  }
  ⟨request, args, Json.mkObj [], [request]⟩

def smallSale := mkExample "cedar_is_small_threshold" ["SellShares"] (small 100)

theorem uses_actual_guide_pack : resolve "cedar_is_small_threshold" = .ok smallSale := by rfl

theorem reduce_quantity : ∃ shares : Nat, 0 < shares ∧ shares ≤ 100 ∧
    (historyTrace (sale shares).history ⊨ smallSale.toLeanLTL (sale shares)) := by
  guard_repair? [100, 99] using decide +kernel

theorem exact_quantity_cannot_be_repaired : ¬ ∃ shares : Nat, shares = 100 ∧
    (historyTrace (sale shares).history ⊨ smallSale.toLeanLTL (sale shares)) := by
  rintro ⟨shares, rfl, allowed⟩
  have denied : ¬ (historyTrace (sale 100).history ⊨ smallSale.toLeanLTL (sale 100)) := by
    decide +kernel
  exact denied allowed

/-- With no permit rule, changing arguments, history, or even the action cannot admit a call. -/
theorem forbid_only_cannot_be_repaired (name : String) (scope : List String)
    (condition : Formula Check) (c : Context) :
    ¬ (historyTrace c.history ⊨ (forbidExample name scope condition).toLeanLTL c) := by
  rw [← decision_leanLTL_correct]
  simp [forbidExample, decidePolicy, authorize, permitted, forbid]

theorem large_sale_forbid_has_no_repair (c : Context) :
    ¬ (historyTrace c.history ⊨
      (forbidExample "forbid_large_except_amzn" ["SellShares"]
        (.neg (small 100 true) ⋏ .neg (stockIs "AMZN"))).toLeanLTL c) :=
  forbid_only_cannot_be_repaired _ _ _ c

theorem transfer_read_forbid_has_no_repair (c : Context) :
    ¬ (historyTrace c.history ⊨
      (forbidExample "forbid_read_transfers_over_1000" ["Read"]
        (transferSum "success" "output" true 1000)).toLeanLTL c) :=
  forbid_only_cannot_be_repaired _ _ _ c

#print axioms reduce_quantity
#print axioms forbid_only_cannot_be_repaired
run_cmd do
  LeanGuard.Audit.check #[``reduce_quantity, ``forbid_only_cannot_be_repaired]
    #[`DogwoodGuide.Repairs]

end DogwoodGuide.Repairs
