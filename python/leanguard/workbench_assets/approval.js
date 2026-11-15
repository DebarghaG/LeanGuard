"use strict";
const $ = (id) => document.getElementById(id);
let busy = false;
function el(tag, text, className) {
  const element = document.createElement(tag);
  if (text !== undefined) element.textContent = text;
  if (className) element.className = className;
  return element;
}
function error(value) {
  $("error").hidden = false;
  $("error").textContent = value.message;
}
function render(state) {
  $("identity").replaceChildren();
  for (const [label, value] of [
    ["Principal", state.principal],
    ["Conversation", state.session],
    ["Policy", state.domain],
    ["Executable SHA-256", state.engine_sha256],
  ])
    $("identity").append(el("dt", label), el("dd", value));
  $("proposals").replaceChildren();
  if (!state.proposals.length)
    $("proposals").append(
      el("p", "No proposals have been submitted by the trusted application."),
    );
  for (const proposal of state.proposals) {
    const card = el("article", undefined, "panel");
    card.append(
      el("h2", proposal.action),
      el(
        "p",
        `Status: ${proposal.status}${proposal.outcome ? ` · outcome ${proposal.outcome}` : ""}`,
        "badge",
      ),
      el("h3", "Exact proposal"),
      el("pre", proposal.details_text),
    );
    const choices = el("div", undefined, "button-row");
    const answer = async (accepted) => {
      if (busy) return;
      busy = true;
      $("error").hidden = true;
      document.querySelectorAll("button").forEach((b) => (b.disabled = true));
      try {
        const response = await fetch("/api/answer", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-LeanGuard-UI": "1",
          },
          body: JSON.stringify({
            proposal: proposal.id,
            binding: proposal.binding,
            accepted,
          }),
        });
        const result = await response.json();
        if (!response.ok) throw new Error(result.error);
        render(result);
        $("notice").textContent = accepted
          ? "Consent recorded. No tool was executed."
          : "Rejection or revocation recorded. No tool was executed.";
      } catch (e) {
        error(e);
      } finally {
        busy = false;
        $("refresh").disabled = false;
      }
    };
    for (const [label, accepted] of proposal.status === "pending"
      ? [
          ["Approve this exact call", true],
          ["Reject", false],
        ]
      : proposal.status === "accepted"
        ? [["Revoke approval", false]]
        : []) {
      const b = el("button", label, accepted ? "primary" : "danger");
      b.onclick = () => answer(accepted);
      choices.append(b);
    }
    card.append(choices);
    $("proposals").append(card);
  }
}
async function refresh() {
  if (busy) return;
  try {
    const r = await fetch("/api/state");
    const value = await r.json();
    if (!r.ok) throw new Error(value.error);
    render(value);
  } catch (e) {
    error(e);
  }
}
$("refresh").onclick = refresh;
(async () => {
  try {
    const token = location.hash.slice(1);
    history.replaceState(null, "", location.pathname);
    if (token) {
      const r = await fetch("/session", {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!r.ok) throw new Error("Invalid operator link");
    }
    await refresh();
  } catch (e) {
    error(e);
  }
})();
