/*
 * Workbench mode — the dashboard, connected to the local server.
 *
 * Loaded only when the page is served from Workbench (ADR-036). Two jobs:
 *
 *   1. Fetch records as JSON. The browser no longer parses records at all;
 *      `parseLooseYaml` in dashboard.js was a hand-rolled YAML subset that
 *      silently dropped nested maps and multi-line strings, and the templates
 *      it had to read already nest. The server parses now, and there is one
 *      parser in the system.
 *
 *   2. Turn the read-only view into a control plane: approve, advance status,
 *      add to the roster. Every action POSTs to the server, which calls the
 *      engine. No write logic lives in this file — a refusal here would be a
 *      second opinion about what is allowed, and one of them would be wrong.
 */

const WORKBENCH = {
  active: false,
  projectId: null,
  // dashboard.js groups records under its own collection names.
  collectionFor: {
    task: "tasks", ticket: "tickets", run: "runs", review_record: "reviews",
    release: "releases", founder_inbox_item: "inbox", approval: "approvals",
    learning_candidate: "learning", context_pack: "contextPacks",
    interaction: "interactions",
  },
};

async function workbenchFetch(path, options) {
  const response = await fetch(path, options);
  let payload = {};
  try { payload = await response.json(); } catch (error) { payload = {}; }
  if (!response.ok) {
    // A refusal is an outcome, not a crash. Show the reason the engine gave.
    const reason = payload.error || `${response.status} ${response.statusText}`;
    throw new Error(reason);
  }
  return payload;
}

function toDashboardShape(byType) {
  const records = emptyRecords();
  for (const [objectType, items] of Object.entries(byType)) {
    const collection = WORKBENCH.collectionFor[objectType];
    if (collection) records[collection] = items;
  }
  return records;
}

async function workbenchLoad() {
  const payload = await workbenchFetch("/api/records");
  WORKBENCH.projectId = payload.project_id;
  state.records = toDashboardShape(payload.records);
  state.loadedLabel = `${payload.project_id} (live)`;
  render(state.records);
  workbenchDecorate();
}

function workbenchNotice(message, kind) {
  const bar = document.getElementById("workbenchNotice");
  if (!bar) return;
  bar.textContent = message;
  bar.className = `workbench-notice ${kind}`;
  bar.hidden = false;
  if (kind === "ok") setTimeout(() => { bar.hidden = true; }, 4000);
}

async function workbenchAct(path, body, description) {
  try {
    await workbenchFetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    workbenchNotice(`${description} — done`, "ok");
    await workbenchLoad();
  } catch (error) {
    // Refusals are shown verbatim. The engine already explains itself.
    workbenchNotice(`Refused: ${error.message}`, "refused");
  }
}

/* Action affordances, added after each render. */
function workbenchDecorate() {
  const panel = document.getElementById("detailPanel");
  if (!panel || !state.selected?.id) return;
  const record = state.indexes.byId.get(state.selected.id);
  if (!record) return;

  const actions = document.createElement("div");
  actions.className = "workbench-actions";

  if (record.object_type === "approval" && record.status === "requested") {
    actions.appendChild(actionButton("Approve", () => workbenchAct(
      "/api/approve", { id: record.id }, `Approved ${record.id}`)));
  }

  if (record.object_type === "ticket" || record.object_type === "task") {
    for (const next of nextStatuses(record)) {
      actions.appendChild(actionButton(`→ ${next}`, () => workbenchAct(
        "/api/status", { id: record.id, status: next }, `${record.id} → ${next}`)));
    }
  }

  if (actions.children.length) {
    const heading = document.createElement("div");
    heading.className = "workbench-actions-label";
    heading.textContent = "Actions";
    panel.append(heading, actions);
  }
}

function nextStatuses(record) {
  const flows = {
    ticket: { inbox: ["ready"], ready: ["assigned"], assigned: ["in_progress"],
              in_progress: ["external_review", "blocked"],
              external_review: ["revision", "release_ready"],
              revision: ["in_progress"], release_ready: ["shipped"] },
    task: { inbox: ["discovery"], discovery: ["ready"], ready: ["assigned"],
            assigned: ["in_progress"], in_progress: ["review", "blocked"],
            review: ["release_ready"], release_ready: ["shipped"] },
  };
  return flows[record.object_type]?.[record.status] || [];
}

function actionButton(label, handler) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "workbench-action";
  button.textContent = label;
  button.addEventListener("click", handler);
  return button;
}

/* Take over from the folder-picker path when served by Workbench. */
async function workbenchInit() {
  try {
    await workbenchFetch("/api/records");
  } catch (error) {
    return; // Not served by Workbench: the file:// folder picker stays in charge.
  }
  WORKBENCH.active = true;
  document.body.classList.add("workbench-mode");

  const loadButton = document.getElementById("loadFolderButton");
  if (loadButton) {
    loadButton.textContent = "Reload";
    loadButton.replaceWith(loadButton.cloneNode(true));
    document.getElementById("loadFolderButton").addEventListener("click", workbenchLoad);
  }
  const refreshButton = document.getElementById("refreshButton");
  if (refreshButton) {
    refreshButton.disabled = false;
    refreshButton.replaceWith(refreshButton.cloneNode(true));
    document.getElementById("refreshButton").addEventListener("click", workbenchLoad);
  }
  document.addEventListener("click", () => setTimeout(workbenchDecorate, 0));
  await workbenchLoad();
}

document.addEventListener("DOMContentLoaded", workbenchInit);
