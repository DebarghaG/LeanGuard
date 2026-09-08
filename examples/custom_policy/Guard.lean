import LeanGuard.Schema
import LeanGuard.VerifiedPolicy
import LeanGuard.Reservations

namespace DocumentGuard
open LeanGuard

def approval := require "documents.approval" ["write"] confirmed "exact one-use user approval"
def budget := require "documents.budget" ["write"] (quota 10 10000 3600) "hourly dispatch budget"

def pack : PolicyPack := withSchemas {
  name := "documents"
  rules := [permit "documents.tools" ["read", "write"], approval, budget,
    require "documents.single" ["read", "write"] singleFlight "unresolved dispatch exclusion"]
} [("read", .object [] []), ("write", .object ["value"] [("value", .string)])]

/-- Write admission requires prior approval evidence, no previous use of that
approval, and the reserved dispatch must fit both hourly budget bounds. -/
def Safe (c : Context) : Prop := c.request.action = "write" →
  (∃ i ∈ List.range (projectAtHead .conversation c.history).tail.length,
    Holds (atomValue c) confirmedEvent ((projectAtHead .conversation c.history).tail.drop i)) ∧
  (¬ Holds (atomValue c) (.once none usedConfirmation)
    (projectAtHead .conversation c.history).tail) ∧
  countEvents (reserve true c.request c.history) (quotaMatches c.request 3600) ≤ 10 ∧
  sumEvents (reserve true c.request c.history) (quotaMatches c.request 3600) ≤ 10000

theorem safe (c : Context) (allowed : (decidePolicy pack c).allow = true) : Safe c := by
  intro writing
  have confirmation := authorized_requirement pack.rules (atomValue c)
    c.request.action c.history approval (by simp [pack, withSchemas])
    (by simp [Rule.applies, approval, require, writing]) rfl (decision_sound pack c allowed)
  have limits := authorized_requirement pack.rules (atomValue c)
    c.request.action c.history budget (by simp [pack, withSchemas])
    (by simp [Rule.applies, budget, require, writing]) rfl (decision_sound pack c allowed)
  have accepted : evaluate (atomValue c) confirmed c.history = true :=
    (evaluate_correct _ _ _).mpr confirmation
  have bounded : evaluate (atomValue c) (quota 10 10000 3600) c.history = true :=
    (evaluate_correct _ _ _).mpr limits
  exact ⟨confirmation_has_witness c accepted, confirmation_not_consumed c accepted,
    quota_reservation_bound c 10 10000 3600 bounded⟩

def verified : VerifiedPolicy := {
  pack := pack
  property := "DocumentGuard.safe"
  Safe := Safe
  sound := safe
}

end DocumentGuard
