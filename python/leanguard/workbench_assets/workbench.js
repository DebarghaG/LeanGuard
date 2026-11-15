"use strict";
const $ = (id) => document.getElementById(id);
let state,
  draft,
  corpus,
  dirty = false,
  expertEditing = false,
  busy = false,
  scenarioDirty = false;
let selectedCase = 0;
const names = {
  author: "Write policy",
  inspect: "Inspect compiled rules",
  scenarios: "Try scenarios",
  review: "Review artifact",
};

function el(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = String(text);
  if (className) node.className = className;
  return node;
}
function field(label, value, change, options = {}) {
  const wrapper = el("label", label);
  let input;
  if (options.choices) {
    input = el("select");
    for (const [key, text] of options.choices) {
      const option = el("option", text);
      option.value = key;
      input.append(option);
    }
  } else input = el(options.multiline ? "textarea" : "input");
  if (options.number) {
    input.type = "number";
    input.min = "0";
    input.step = "1";
  }
  if (options.multiline) input.rows = 2;
  input.value = value ?? "";
  input.addEventListener("change", () =>
    change(
      options.number
        ? input.value === ""
          ? null
          : input.valueAsNumber
        : input.value,
    ),
  );
  wrapper.append(input);
  return wrapper;
}
function button(label, action, className = "small") {
  const node = el("button", label, className);
  node.type = "button";
  node.onclick = action;
  return node;
}
function detail(title, text) {
  const node = el("details");
  node.append(el("summary", title), el("pre", text));
  return node;
}
function showError(error) {
  $("error").hidden = false;
  $("error").textContent = error.message ?? String(error);
}
function changed() {
  dirty = true;
  $("document-json").value = JSON.stringify(draft, null, 2);
  $("save-state").textContent = "Unsaved changes. Save before compiling.";
  $("stage").textContent = "Unsaved draft";
  updateActions();
}
function view(name) {
  for (const [key, title] of Object.entries(names)) {
    $(key).hidden = key !== name;
    const nav = document.querySelector(`[data-view="${key}"]`);
    nav.classList.toggle("active", key === name);
    if (key === name) nav.setAttribute("aria-current", "page");
    else nav.removeAttribute("aria-current");
  }
  $("page-title").textContent = names[name];
  $("main").focus();
}
function updateActions() {
  $("compile").disabled = busy || dirty || !state?.document;
  $("run-scenarios").disabled = busy || dirty || !state?.compiled;
  $("apply-corpus").disabled = busy || dirty || !state?.compiled;
  $("create-bundle").disabled =
    busy || dirty || !state?.compiled || !state?.results || scenarioDirty;
  document
    .querySelectorAll("#bundle-details button")
    .forEach((b) => (b.disabled = busy || dirty || scenarioDirty));
}
async function request(path, body, message) {
  if (busy) return;
  busy = true;
  $("main").setAttribute("aria-busy", "true");
  $("error").hidden = true;
  $("notice").hidden = false;
  $("notice").textContent = message;
  const disabled = new Map(
    [...document.querySelectorAll("button")].map((b) => [b, b.disabled]),
  );
  disabled.forEach((_, b) => (b.disabled = true));
  try {
    const response = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-LeanGuard-UI": "1" },
      body: JSON.stringify(body),
    });
    const result = await response.json();
    if (!response.ok)
      throw new Error(result.error ?? "Operator request failed");
    state = result;
    dirty = expertEditing = scenarioDirty = false;
    render();
    $("notice").textContent =
      path === "/api/compile"
        ? "Native compilation and axiom audit completed. Inspect the rules and try scenarios."
        : "Saved. Review the updated state below.";
  } catch (error) {
    $("notice").hidden = true;
    showError(error);
  } finally {
    busy = false;
    $("main").removeAttribute("aria-busy");
    disabled.forEach((value, b) => {
      if (b.isConnected) b.disabled = value;
    });
    updateActions();
  }
}
function save() {
  return request(
    "/api/draft",
    { revision: state.revision, document_text: $("document-json").value },
    "Validating and saving the draft…",
  );
}

function toolEditor(tool, index) {
  const card = el("article", undefined, "card");
  const top = el("div", undefined, "section-head");
  top.append(
    field("Tool name", tool.name, (value) => {
      tool.name = value;
      changed();
    }),
    button(
      "Remove tool",
      () => {
        draft.tools.splice(index, 1);
        changed();
        renderEditor();
      },
      "small danger",
    ),
  );
  card.append(
    top,
    el(
      "p",
      "Native object schemas allow extra arguments. Every required field below is checked before dispatch.",
      "hint",
    ),
  );
  const schema = tool.schema;
  if (
    schema.type === "object" &&
    Object.values(schema.properties).every(
      (p) =>
        ["string", "integer", "number", "boolean", "null"].includes(p.type) &&
        Object.keys(p).length === 1,
    )
  ) {
    for (const [key, spec] of Object.entries(schema.properties)) {
      const row = el("div", undefined, "property-row");
      row.append(
        field("Argument name", key, (value) => {
          if (!value || (value !== key && value in schema.properties)) {
            showError(new Error("Use a unique argument name"));
            return;
          }
          delete schema.properties[key];
          schema.properties[value] = spec;
          schema.required = schema.required.map((name) =>
            name === key ? value : name,
          );
          changed();
          renderEditor();
        }),
        field(
          "Type",
          spec.type,
          (value) => {
            spec.type = value;
            changed();
          },
          {
            choices: ["string", "integer", "number", "boolean", "null"].map(
              (x) => [x, x],
            ),
          },
        ),
      );
      const required = el("label", undefined, "check");
      const check = el("input");
      check.type = "checkbox";
      check.checked = schema.required.includes(key);
      check.onchange = () => {
        schema.required = check.checked
          ? [...schema.required, key]
          : schema.required.filter((x) => x !== key);
        changed();
      };
      required.append(check, document.createTextNode("Required"));
      row.append(
        required,
        button("Remove argument", () => {
          delete schema.properties[key];
          schema.required = schema.required.filter((x) => x !== key);
          changed();
          renderEditor();
        }),
      );
      card.append(row);
    }
    card.append(
      button("Add argument", () => {
        let name = "argument";
        while (name in schema.properties) name += "_";
        schema.properties[name] = { type: "string" };
        changed();
        renderEditor();
      }),
    );
  } else
    card.append(
      el(
        "p",
        "This schema uses nested or enumerated types. Preserve it here; edit the structured document in Expert view.",
        "hint",
      ),
    );
  card.append(detail("Exact schema", JSON.stringify(schema, null, 2)));
  return card;
}
const kinds = [
  ["always", "Always true"],
  ["approval", "Exact human approval"],
  ["observation", "A successful earlier observation"],
  ["quota", "Dispatch count and amount limit"],
  ["single_flight", "No unresolved earlier dispatch"],
  ["never_dispatched", "No earlier dispatch of these actions"],
  ["never", "Always false"],
];
function actionChecks(label, selected, update) {
  const group = el("fieldset");
  group.append(el("legend", label));
  const checks = el("div", undefined, "checks");
  for (const tool of draft.tools) {
    const wrapper = el("label", undefined, "check"),
      input = el("input");
    input.type = "checkbox";
    input.checked = selected.includes(tool.name);
    input.onchange = () =>
      update(
        input.checked
          ? [...selected, tool.name]
          : selected.filter((x) => x !== tool.name),
      );
    wrapper.append(input, document.createTextNode(tool.name));
    checks.append(wrapper);
  }
  group.append(checks);
  return group;
}
function ruleEditor(rule, index) {
  const card = el("article", undefined, "card");
  const top = el("div", undefined, "rule-top");
  top.append(
    el("strong", `Rule ${index + 1} · ${rule.id}`, "rule-title"),
    button(
      "Remove rule",
      () => {
        draft.rules.splice(index, 1);
        changed();
        renderEditor();
      },
      "small danger",
    ),
  );
  card.append(top);
  const row = el("div", undefined, "two-col");
  row.append(
    field("Stable rule ID", rule.id, (value) => {
      rule.id = value;
      changed();
    }),
    field(
      "Effect",
      rule.effect,
      (value) => {
        rule.effect = value;
        changed();
      },
      {
        choices: [
          ["permit", "Permit when this condition holds"],
          ["require", "Require this condition"],
          ["forbid", "Forbid when this condition holds"],
        ],
      },
    ),
  );
  card.append(row);
  card.append(
    actionChecks("Applies to these actions", rule.actions, (value) => {
      rule.actions = value;
      changed();
      renderEditor();
    }),
  );
  const advanced = !kinds.some(([key]) => key === rule.condition.kind);
  card.append(
    field(
      "Condition",
      advanced ? "advanced" : rule.condition.kind,
      (kind) => {
        const defaults = {
          approval: { seconds: 300 },
          observation: { actions: [draft.tools[0]?.name ?? "tool"] },
          never_dispatched: { actions: [draft.tools[0]?.name ?? "tool"] },
          quota: { calls: 10, amount: 10000, window_seconds: 3600 },
        };
        if (kind !== "advanced") {
          rule.condition = { kind, ...defaults[kind] };
          changed();
          renderEditor();
        }
      },
      {
        choices: advanced
          ? [...kinds, ["advanced", "Nested logic · edit in Expert view"]]
          : kinds,
      },
    ),
  );
  const c = rule.condition,
    box = el("div", undefined, "condition");
  if (c.kind === "approval") {
    box.append(
      field(
        "Maximum approval age, in seconds (blank = unbounded)",
        c.seconds,
        (value) => {
          c.seconds = value;
          changed();
        },
        { number: true },
      ),
      el(
        "p",
        "Approval must match the exact call and agent authority. Revoked or already-used approval cannot authorize a new dispatch.",
        "hint",
      ),
    );
  } else if (c.kind === "quota") {
    const limits = el("div", undefined, "three-col");
    for (const [key, label] of [
      ["calls", "Maximum dispatch count"],
      ["amount", "Maximum amount units"],
      ["window_seconds", "Window in seconds"],
    ])
      limits.append(
        field(
          label,
          c[key],
          (value) => {
            c[key] = value;
            changed();
          },
          { number: true },
        ),
      );
    box.append(
      limits,
      el(
        "p",
        "Counts all of this principal's dispatches, including failed and unknown outcomes. The limit is enforced only on the actions checked above. The current call's amount is included.",
        "hint",
      ),
    );
  } else if (["observation", "never_dispatched"].includes(c.kind)) {
    box.append(
      actionChecks("Evidence actions", c.actions, (value) => {
        c.actions = value;
        changed();
        renderEditor();
      }),
      el(
        "p",
        c.kind === "observation"
          ? "Requires a successful earlier action on the same resource, in the same conversation and workflow. This template has no time limit."
          : "No matching resource dispatch by this principal may appear in the available history.",
        "hint",
      ),
    );
  } else
    box.append(
      el(
        "p",
        advanced
          ? "Nested Boolean conditions are preserved. Use the structured document to edit them."
          : c.kind === "single_flight"
            ? "An unknown outcome remains unresolved. Reconcile it before another call in the same conversation or resource."
            : `This condition is ${c.kind === "always" ? "true" : "false"}; the rule's effect still determines how it participates.`,
        "hint",
      ),
    );
  card.append(
    box,
    field(
      "Source clause · why this rule exists",
      rule.source,
      (value) => {
        rule.source = value;
        changed();
      },
      { multiline: true },
    ),
  );
  return card;
}
function renderEditor() {
  $("readonly").hidden = !!draft;
  $("editor").hidden = !draft;
  if (!draft) return;
  $("pack-name").value = draft.name;
  $("units").value = draft.units;
  $("tools").replaceChildren(...draft.tools.map(toolEditor));
  $("rules").replaceChildren(...draft.rules.map(ruleEditor));
  $("document-json").value = JSON.stringify(draft, null, 2);
  $("lean-source").textContent = state.lean ?? "Save a valid draft first.";
  $("save-state").textContent = dirty
    ? "Unsaved changes. Save before compiling."
    : "Saved draft. Compilation checks this document with Lean.";
  document
    .querySelectorAll(
      "#tools input,#tools select,#tools button,#rules input,#rules select,#rules textarea,#rules button,#pack-name,#units,#add-tool,#add-rule",
    )
    .forEach((n) => (n.disabled = expertEditing));
}

function atomDescription(node) {
  const d = node.description;
  if (node.opaque || !d) return null;
  const descriptions = {
    matching_confirmation:
      "Exact approval for this action, resource, binding, conversation and agent authority.",
    matching_revocation: "Revocation of this binding in this conversation.",
    confirmation_consumed:
      "A dispatch in this conversation already used this binding.",
    successful_resource_observation: `Successful ${(d.actions ?? []).join(", ")} on this resource in this conversation and workflow.`,
    resource_dispatch: `A dispatch of ${(d.actions ?? []).join(", ")} on this resource by this principal.`,
    dispatch_quota: `At request time: fewer than ${d.calls} prior dispatches; prior units plus this call ≤ ${d.amount}, within ${d.window_seconds} seconds, for this principal.`,
    single_inflight_call:
      "No unresolved dispatch in this conversation or resource. Unknown outcomes remain unresolved.",
    argument_schema: `Arguments match the declared native schema (maximum depth ${d.max_depth}).`,
  };
  return descriptions[d.kind] ?? null;
}
function formula(node) {
  const item = el("li");
  if (node.op === "atom") {
    const description = atomDescription(node);
    item.append(
      el(
        "span",
        description ??
          `Opaque native predicate: ${node.name}. Read-only; a name does not define its meaning.`,
        description ? "" : "opaque",
      ),
    );
    if (!description)
      item.append(detail("Exact declared node", JSON.stringify(node, null, 2)));
    return item;
  }
  const window =
    node.window_seconds === null
      ? "unbounded time"
      : `${node.window_seconds} seconds, inclusive`;
  const label = {
    true: "Always true",
    false: "Always false",
    not: "Not",
    and: "All conditions",
    or: "Any condition",
    previous: `Previous position · ${window}`,
    once: `Some current or past position · ${window}`,
    since: `Since a witness · ${window}; left condition holds at every intervening position`,
    within: `Use only the ${node.scope} history`,
  }[node.op];
  item.append(
    el("strong", label ?? `Unknown operator: ${node.op}. Read-only.`),
  );
  const children = el("ul");
  for (const key of ["left", "right", "child"])
    if (node[key]) children.append(formula(node[key]));
  if (children.childNodes.length) item.append(children);
  return item;
}
function renderInspection() {
  const tree = state.inspection;
  $("artifact-info").replaceChildren();
  $("coverage").replaceChildren();
  $("inspection-rules").replaceChildren();
  $("claims").replaceChildren();
  if (!tree) {
    $("artifact-info").append(
      el("dt", "Status"),
      el("dd", "Compile a draft or open a native pack with --inspect."),
    );
    return;
  }
  for (const [label, value] of [
    ["Pack", tree.domain],
    ["Executable SHA-256", tree.engine_sha256],
    ["Inspection version", tree.version],
    [
      "Source state",
      state.compiled || !state.document
        ? "Compiled artifact"
        : "Earlier artifact; the current draft has changed",
    ],
  ])
    $("artifact-info").append(el("dt", label), el("dd", value));
  $("coverage").append(el("h3", "Tool coverage"));
  const table = el("table"),
    head = el("tr");
  for (const label of ["Action", "Permits", "Requirements", "Forbids"])
    head.append(el("th", label));
  const thead = el("thead");
  thead.append(head);
  table.append(thead);
  const body = el("tbody");
  for (const action of Object.keys(tree.schemas)) {
    const row = el("tr");
    row.append(el("td", action));
    for (const effect of ["permit", "require", "forbid"])
      row.append(
        el(
          "td",
          tree.rules.filter(
            (r) => r.actions.includes(action) && r.effect === effect,
          ).length,
        ),
      );
    body.append(row);
  }
  table.append(body);
  $("coverage").append(
    table,
    el(
      "p",
      "Counts show rule coverage. They are not an allow decision for a particular call.",
      "hint",
    ),
  );
  for (const rule of tree.rules) {
    const card = el("article", undefined, "card"),
      title = el("div", undefined, "result-title");
    title.append(
      el("span", rule.effect.toUpperCase(), "badge"),
      el("h3", rule.id),
    );
    const list = el("ul", undefined, "condition");
    list.append(formula(rule.condition));
    card.append(
      title,
      el("p", `Actions: ${rule.actions.join(", ")}`),
      el("p", rule.source, "muted"),
      list,
    );
    $("inspection-rules").append(card);
  }
  const properties = tree.properties ?? {};
  $("claims").append(
    el("h3", "Claims and assumptions"),
    el(
      "p",
      `Engine declarations: ${(properties.engine ?? []).join(", ") || "See compiled source"}.`,
    ),
    el(
      "p",
      `Pack declarations: ${(properties.pack ?? []).join(", ") || "No pack-specific property is declared"}.`,
    ),
  );
  const assumptions = el("ul");
  for (const text of tree.deployment_assumptions ?? [])
    assumptions.append(el("li", text));
  $("claims").append(assumptions);
}

function unsafeNumbers(value) {
  if (typeof value === "number")
    return (
      !Number.isFinite(value) ||
      (Number.isInteger(value) && !Number.isSafeInteger(value))
    );
  return (
    value &&
    typeof value === "object" &&
    Object.values(value).some(unsafeNumbers)
  );
}
function corpusChanged() {
  scenarioDirty = true;
  updateActions();
  $("scenario-json").value = JSON.stringify(corpus, null, 2);
  $("scenario-results").replaceChildren(
    el(
      "p",
      "Scenario edits have not been evaluated. Run the native engine.",
      "hint",
    ),
  );
  $("create-bundle").disabled = true;
}
function renderCase() {
  const area = $("case-editor");
  area.replaceChildren();
  if (!corpus?.cases?.length || unsafeNumbers(corpus)) {
    area.append(
      el(
        "p",
        "Use the exact JSON editor for scenarios with large numeric values or unsupported structure. The server preserves the original digits.",
        "hint",
      ),
    );
    return;
  }
  const scenario = corpus.cases[selectedCase] ?? corpus.cases[0],
    request = scenario.request;
  if (!request || !Array.isArray(scenario.history)) return;
  const row = el("div", undefined, "three-col");
  for (const [key, label] of [
    ["action", "Proposed action"],
    ["resource", "Resource"],
    ["principal", "Principal"],
    ["session", "Conversation"],
    ["time", "Request time · integer seconds"],
    ["amount", "Current amount units"],
  ])
    row.append(
      field(
        label,
        request[key],
        (value) => {
          request[key] = value;
          corpusChanged();
        },
        { number: ["time", "amount"].includes(key) },
      ),
    );
  area.append(
    row,
    field("Exact arguments · JSON", JSON.stringify(request.input), (value) => {
      try {
        const parsed = JSON.parse(value);
        if (unsafeNumbers(parsed))
          throw new Error(
            "Use the exact scenario JSON editor for large integers",
          );
        request.input = parsed;
        corpusChanged();
      } catch (error) {
        showError(error);
      }
    }),
  );
  area.append(el("h4", "Earlier events · oldest first"));
  const timeline = el("ol", undefined, "timeline");
  scenario.history.forEach((event, index) => {
    const item = el("li"),
      fields = el("div", undefined, "event-row");
    for (const [key, label] of [
      ["time", "Time"],
      ["kind", "Event kind"],
      ["action", "Action"],
      ["resource", "Resource"],
    ])
      fields.append(
        field(
          label,
          event[key],
          (value) => {
            event[key] = value;
            corpusChanged();
          },
          key === "kind"
            ? {
                choices: [
                  "confirmed",
                  "revoked",
                  "dispatch",
                  "success",
                  "failure",
                  "unknown",
                  "reconciled",
                ].map((x) => [x, x]),
              }
            : { number: key === "time" },
        ),
      );
    fields.append(
      button("Remove event", () => {
        scenario.history.splice(index, 1);
        corpusChanged();
        renderCase();
      }),
    );
    item.append(
      fields,
      detail("Exact event, identity and facts", JSON.stringify(event, null, 2)),
    );
    timeline.append(item);
  });
  area.append(timeline);
  const add = el("div", undefined, "button-row");
  add.append(
    button("Add matching approval", () => {
      scenario.history.push({
        ...deepcopy(request),
        id: `approval-${scenario.history.length}`,
        time: request.time - 1,
        kind: "confirmed",
        input: {},
        facts: {},
        amount: 0,
      });
      scenario.history.sort((a, b) => a.time - b.time);
      corpusChanged();
      renderCase();
    }),
    button("Add successful read", () => {
      const id = `read-${scenario.history.length}`;
      for (const [kind, delta] of [
        ["dispatch", 2],
        ["success", 1],
      ])
        scenario.history.push({
          ...deepcopy(request),
          id,
          kind,
          action: "read",
          binding: "",
          amount: 0,
          input: {},
          facts: {},
          time: request.time - delta,
        });
      scenario.history.sort((a, b) => a.time - b.time);
      corpusChanged();
      renderCase();
    }),
  );
  area.append(
    add,
    el(
      "p",
      "An outcome must use its dispatch ID. Request and event identities are visible in Exact event; edit arbitrary facts or identity fields in the advanced JSON editor.",
      "hint",
    ),
  );
}
function deepcopy(value) {
  return JSON.parse(JSON.stringify(value));
}
function renderScenarios() {
  corpus = JSON.parse(state.corpus_text);
  $("scenario-json").value = state.corpus_text;
  $("case-select").replaceChildren(
    ...corpus.cases.map((c, i) => {
      const option = el("option", c.id);
      option.value = i;
      return option;
    }),
  );
  selectedCase = Math.min(selectedCase, corpus.cases.length - 1);
  $("case-select").value = selectedCase;
  renderCase();
  $("scenario-results").replaceChildren();
  for (const result of state.results?.cases ?? []) {
    const card = el("article", undefined, "card"),
      title = el("div", undefined, "result-title");
    title.append(
      el("h3", result.id),
      el(
        "span",
        result.assessment.replaceAll("_", " "),
        `badge ${result.assessment === "allowed" ? "" : result.assessment === "denied" ? "deny" : "warn"}`,
      ),
    );
    card.append(title);
    if (result.decision.reasons.length)
      card.append(
        el("p", `Native reasons: ${result.decision.reasons.join(", ")}`),
      );
    if (result.decision.errors.length || result.missing_evidence.length)
      card.append(
        el(
          "p",
          [...result.decision.errors, ...result.missing_evidence].join("; "),
          "error",
        ),
      );
    const list = el("ul");
    for (const [id, truth] of Object.entries(result.rules))
      list.append(
        el(
          "li",
          `${id}: ${truth ? "condition holds" : "condition does not hold"}`,
        ),
      );
    card.append(
      list,
      detail("Exact native audit result", JSON.stringify(result, null, 2)),
      el(
        "p",
        "Rule evaluations and supplied evidence help explain this case. They are not a complete causal witness trace.",
        "hint",
      ),
    );
    $("scenario-results").append(card);
  }
  $("comparison").hidden = !state.comparison;
  if (state.comparison) {
    $("comparison").replaceChildren(
      el("h3", "Changes from the previous compilation"),
      el("p", state.comparison.claim),
    );
    for (const change of state.comparison.changes)
      $("comparison").append(
        el("p", `${change.id}: ${change.before} → ${change.after}`),
      );
    if (!state.comparison.changes.length)
      $("comparison").append(
        el("p", "No assessment changes in this scenario sample."),
      );
    for (const change of state.comparison.structural_changes)
      $("comparison").append(
        detail(
          change.path,
          JSON.stringify(
            { before: change.before, after: change.after },
            null,
            2,
          ),
        ),
      );
  }
}
function renderReview() {
  $("bundle-details").hidden = !state.bundle;
  if (!state.bundle) return;
  const area = $("bundle-details");
  area.replaceChildren(el("h3", "Exact bundle awaiting your decision"));
  const facts = el("dl", undefined, "facts");
  for (const [key, value] of [
    ["Bundle SHA-256", state.bundle.bundle_sha256],
    ["Executable SHA-256", state.bundle.manifest.engine_sha256],
    [
      "Private scenario data",
      state.bundle.manifest.scenario_data_included ? "Included" : "Omitted",
    ],
  ])
    facts.append(el("dt", key), el("dd", value));
  area.append(facts);
  const choices = el("div", undefined, "button-row");
  for (const [decision, label, style] of [
    ["accept", "Accept this exact bundle", "primary"],
    ["reject", "Reject this bundle", "danger"],
  ])
    choices.append(
      button(
        label,
        () =>
          request(
            "/api/review",
            {
              revision: state.revision,
              bundle_sha256: state.bundle.bundle_sha256,
              decision,
            },
            "Binding your review to the exact bundle…",
          ),
        style,
      ),
    );
  area.append(choices);
  if (state.review)
    area.append(
      el(
        "p",
        `Review ${state.review.decision === "accept" ? "accepted" : "rejected"} by local operator ${state.review.reviewer.name}.`,
        "notice",
      ),
    );
  const download = el("a", "Download local review package");
  download.href = "/export/review.zip";
  const downloadRow = el("p");
  downloadRow.append(download);
  area.append(downloadRow);
}
function render() {
  draft = state.document ? deepcopy(state.document) : null;
  $("stage").textContent = state.stage;
  renderEditor();
  renderInspection();
  renderScenarios();
  renderReview();
  updateActions();
}
document
  .querySelectorAll("[data-view]")
  .forEach((b) => (b.onclick = () => view(b.dataset.view)));
$("save").onclick = save;
$("apply-json").onclick = save;
$("pack-name").onchange = (e) => {
  draft.name = e.target.value;
  changed();
};
$("units").onchange = (e) => {
  draft.units = e.target.value;
  changed();
};
$("document-json").oninput = () => {
  dirty = true;
  expertEditing = true;
  $("save-state").textContent =
    "Apply the JSON draft to return to guided editing.";
  document
    .querySelectorAll(
      "#tools input,#tools select,#tools button,#rules input,#rules select,#rules textarea,#rules button,#pack-name,#units,#add-tool,#add-rule",
    )
    .forEach((n) => (n.disabled = true));
  updateActions();
};
$("add-rule").onclick = () => {
  let id = `rule${draft.rules.length + 1}`;
  while (draft.rules.some((r) => r.id === id)) id += "_";
  draft.rules.push({
    id,
    effect: "require",
    actions: [draft.tools[0]?.name ?? "tool"],
    condition: { kind: "approval", seconds: 300 },
    source: "Describe the requirement and its source.",
  });
  changed();
  renderEditor();
};
$("add-tool").onclick = () => {
  let name = `tool${draft.tools.length + 1}`;
  while (draft.tools.some((t) => t.name === name)) name += "_";
  draft.tools.push({
    name,
    schema: { type: "object", properties: {}, required: [] },
  });
  changed();
  renderEditor();
};
$("compile").onclick = () =>
  request(
    "/api/compile",
    { revision: state.revision },
    "Compiling with Lean and running the axiom audit. This can take a few minutes…",
  );
$("start-template").onclick = () =>
  request(
    "/api/new",
    { revision: state.revision },
    "Starting a separate structured policy draft…",
  );
$("case-select").onchange = (e) => {
  selectedCase = Number(e.target.value);
  renderCase();
};
const run = () =>
  request(
    "/api/scenarios",
    { revision: state.revision, corpus_text: $("scenario-json").value },
    "Evaluating the scenarios with the native engine. No tools are dispatched…",
  );
$("run-scenarios").onclick = run;
$("apply-corpus").onclick = run;
$("scenario-json").oninput = () => {
  scenarioDirty = true;
  updateActions();
};
$("create-bundle").onclick = () =>
  request(
    "/api/bundle",
    {
      revision: state.revision,
      corpus_sha256: state.results.corpus_sha256,
      corpus_text: $("scenario-json").value,
      include_scenario_data: $("include-data").checked,
    },
    "Checking provenance and creating the local review bundle…",
  );
(async () => {
  try {
    const token = location.hash.slice(1);
    history.replaceState(null, "", location.pathname);
    if (token) {
      const response = await fetch("/session", {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!response.ok) throw new Error("Invalid operator link");
    }
    const response = await fetch("/api/state");
    const result = await response.json();
    if (!response.ok) throw new Error(result.error);
    state = result;
    render();
    if (!state.document) view("inspect");
  } catch (error) {
    showError(error);
    $("stage").textContent = "Authentication required";
    document.querySelectorAll("button").forEach((b) => (b.disabled = true));
  }
})();
