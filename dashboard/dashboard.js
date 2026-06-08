const FINAL_TICKET_STATUSES = new Set(["release_ready", "shipped", "archived", "done", "completed", "cancelled"]);
const ACTIVE_TICKET_STATUSES = new Set(["assigned", "in_progress", "self_review", "external_review", "testing", "revision"]);
const STAGE_GROUPS = [
  { label: "Intake", statuses: ["inbox", "discovery", "ready"] },
  { label: "Build", statuses: ["assigned", "in_progress"] },
  { label: "Review", statuses: ["self_review", "external_review", "testing", "revision"] },
  { label: "Blocked", statuses: ["blocked"] },
  { label: "Release", statuses: ["release_ready"] },
  { label: "Closed", statuses: ["shipped", "archived", "done", "completed", "cancelled"] },
];

const ROLE_DEPARTMENTS = new Map([
  ["Executive Orchestrator", "Executive"],
  ["Product / Feature Owner", "Product"],
  ["Engineering Lead", "Engineering"],
  ["Execution Agent", "Engineering"],
  ["Review / QA", "Review / QA"],
  ["Review / QA Agent", "Review / QA"],
  ["Release Agent", "Release"],
  ["Advisory Architect", "Architecture"],
  ["Architecture / Context", "Architecture"],
  ["Knowledge / Documentation Agent", "Knowledge"],
  ["Founder Interface / Personal Assistant", "Founder Interface"],
  ["Security / Privacy / Authority", "Security"],
  ["Optimization", "Optimization"],
  ["Marketing", "Marketing"],
]);

const state = { directoryHandle: null, loadedLabel: "", records: emptyRecords() };
const selectors = {
  loadFolderButton: document.getElementById("loadFolderButton"),
  refreshButton: document.getElementById("refreshButton"),
  folderInput: document.getElementById("folderInput"),
  dataStatus: document.getElementById("dataStatus"),
  loadedPath: document.getElementById("loadedPath"),
};

selectors.loadFolderButton.addEventListener("click", loadProjectFolder);
selectors.refreshButton.addEventListener("click", refreshData);
selectors.folderInput.addEventListener("change", loadFromInputFiles);
render(emptyRecords());

async function loadProjectFolder() {
  if (window.showDirectoryPicker) {
    try {
      const selectedHandle = await window.showDirectoryPicker({ mode: "read" });
      const opsHandle = await resolveOpsHandle(selectedHandle);
      state.directoryHandle = opsHandle;
      state.loadedLabel = selectedHandle.name === "ops" ? "ops" : `${selectedHandle.name}/ops`;
      await refreshData();
      selectors.refreshButton.disabled = false;
      return;
    } catch (error) {
      if (error && error.name === "AbortError") return;
      setStatus(`Could not read folder: ${error.message || error}`);
    }
  }
  selectors.folderInput.click();
}

async function resolveOpsHandle(selectedHandle) {
  if (selectedHandle.name === "ops") return selectedHandle;
  return selectedHandle.getDirectoryHandle("ops");
}

async function refreshData() {
  if (!state.directoryHandle) {
    selectors.folderInput.click();
    return;
  }
  const files = await collectFilesFromHandle(state.directoryHandle);
  state.records = parseFiles(files);
  render(state.records);
  setStatus(`Loaded ${files.length} local ops files.`);
  selectors.loadedPath.textContent = state.loadedLabel;
}

async function loadFromInputFiles(event) {
  const files = Array.from(event.target.files || []);
  if (!files.length) return;
  const loadedFiles = await Promise.all(files.map(async (file) => ({
    path: normalizeOpsPath(file.webkitRelativePath || file.name),
    text: await file.text(),
  })));
  state.directoryHandle = null;
  state.loadedLabel = "selected local files";
  state.records = parseFiles(loadedFiles);
  render(state.records);
  setStatus(`Loaded ${loadedFiles.length} local files.`);
  selectors.loadedPath.textContent = state.loadedLabel;
  selectors.refreshButton.disabled = true;
}

async function collectFilesFromHandle(directoryHandle, prefix = "") {
  const files = [];
  for await (const [name, handle] of directoryHandle.entries()) {
    const path = prefix ? `${prefix}/${name}` : name;
    if (handle.kind === "directory") {
      files.push(...await collectFilesFromHandle(handle, path));
      continue;
    }
    if (!isSupportedFile(path)) continue;
    const file = await handle.getFile();
    files.push({ path: normalizeOpsPath(path), text: await file.text() });
  }
  return files;
}

function isSupportedFile(path) {
  return /\.(json|yaml|yml|md)$/i.test(path) && !path.endsWith("README.md");
}

function normalizeOpsPath(path) {
  const normalized = path.replaceAll("\\", "/");
  const markerIndex = normalized.indexOf("/ops/");
  if (markerIndex >= 0) return normalized.slice(markerIndex + 5);
  if (normalized.startsWith("ops/")) return normalized.slice(4);
  return normalized;
}

function emptyRecords() {
  return { tickets: [], tasks: [], runs: [], reviews: [], releases: [], inbox: [], approvals: [], learning: [], contextPacks: [] };
}

function parseFiles(files) {
  const records = emptyRecords();
  for (const file of files) {
    const [folder] = file.path.split("/");
    const filename = file.path.split("/").at(-1);
    if (!filename || filename === "README.md") continue;
    const record = parseRecord(file.text, filename);
    if (!record) continue;
    record._source = `../ops/${file.path}`;
    record._path = file.path;
    record._filename = filename;
    if (folder === "tickets") records.tickets.push(record);
    if (folder === "tasks") records.tasks.push(record);
    if (folder === "runs") records.runs.push(record);
    if (folder === "reviews") records.reviews.push(record);
    if (folder === "releases") records.releases.push(record);
    if (folder === "inbox") records.inbox.push(record);
    if (folder === "approvals") records.approvals.push(record);
    if (folder === "learning") records.learning.push(record);
    if (folder === "context-packs") records.contextPacks.push(record);
  }
  return records;
}

function parseRecord(text, filename) {
  if (filename.endsWith(".json")) {
    try { return JSON.parse(text); } catch { return null; }
  }
  if (filename.endsWith(".md")) {
    const frontmatter = extractFrontmatter(text);
    return frontmatter ? parseLooseYaml(frontmatter) : { title: filename.replace(/\.md$/, ""), status: "available" };
  }
  return parseLooseYaml(text);
}

function extractFrontmatter(text) {
  const lines = text.split(/\r?\n/);
  if (lines[0]?.trim() !== "---") return "";
  const endIndex = lines.findIndex((line, index) => index > 0 && line.trim() === "---");
  return endIndex < 0 ? "" : lines.slice(1, endIndex).join("\n");
}

function parseLooseYaml(text) {
  const data = {};
  let currentKey = null;
  for (const rawLine of text.split(/\r?\n/)) {
    if (!rawLine.trim() || rawLine.trimStart().startsWith("#")) continue;
    const indent = rawLine.length - rawLine.trimStart().length;
    const line = rawLine.trim();
    if (indent === 0 && line.includes(":") && !line.startsWith("- ")) {
      const separatorIndex = line.indexOf(":");
      const key = line.slice(0, separatorIndex).trim();
      const rawValue = line.slice(separatorIndex + 1).trim();
      if (!rawValue) {
        data[key] = [];
        currentKey = key;
      } else {
        data[key] = parseScalar(rawValue);
        currentKey = null;
      }
      continue;
    }
    if (currentKey && line.startsWith("- ")) data[currentKey].push(parseScalar(line.slice(2).trim()));
  }
  return data;
}

function parseScalar(value) {
  if (!value || value === "null" || value === "~") return null;
  if (value === "[]") return [];
  if (value === "true") return true;
  if (value === "false") return false;
  if ((value.startsWith('"') && value.endsWith('"')) || (value.startsWith("'") && value.endsWith("'"))) return value.slice(1, -1);
  return value;
}

function render(records) {
  const tickets = sortById(records.tickets).reverse();
  const runs = sortById(records.runs).reverse();
  const reviews = sortById(records.reviews).reverse();
  const releases = sortById(records.releases).reverse();
  const inbox = sortById(records.inbox).reverse();
  const approvals = sortById(records.approvals).reverse();
  const learning = sortById(records.learning).reverse();
  const contextPacks = sortById(records.contextPacks).reverse();
  const openTickets = tickets.filter((ticket) => !FINAL_TICKET_STATUSES.has(ticket.status));
  const activeTickets = tickets.filter((ticket) => ACTIVE_TICKET_STATUSES.has(ticket.status));
  const blockedTickets = tickets.filter((ticket) => ticket.status === "blocked" || ensureList(ticket.blocking_object_ids).length);
  const readyReleases = releases.filter((release) => ["ready", "released"].includes(release.status));
  setText("metricTickets", tickets.length);
  setText("metricTicketsDetail", `${openTickets.length} open, ${tickets.filter((ticket) => ticket.status === "release_ready").length} release ready`);
  setText("metricActive", activeTickets.length);
  setText("metricActiveDetail", `${blockedTickets.length} blocked`);
  setText("metricRuns", runs.length);
  setText("metricRunsDetail", runs[0]?.id ? `latest ${runs[0].id}` : "No runs loaded");
  setText("metricReleases", readyReleases.length);
  setText("metricReleasesDetail", `${reviews.length} reviews`);
  renderMissionCards(tickets, runs, reviews, releases, inbox, approvals, learning, contextPacks);
  renderDecisionQueue(inbox, approvals, blockedTickets);
  renderStageBoard(tickets, records);
  renderRoleRoster(tickets, runs);
  renderContextPanel(tickets, contextPacks, reviews);
  renderReleaseLane(releases);
  renderLearningQueue(learning);
  renderRunLedger(runs);
}

function renderMissionCards(tickets, runs, reviews, releases, inbox, approvals, learning, contextPacks) {
  const latestTicket = sortById(tickets).at(-1);
  const latestRun = sortById(runs).at(-1);
  const pendingDecisions = inbox.filter((item) => !["closed", "routed", "archived", "cancelled"].includes(item.status)).length + approvals.filter((item) => !["approved", "rejected", "closed", "archived", "cancelled"].includes(item.status)).length;
  const cards = [
    ["Current project", "FACTORY", "Self-hosted Factory build"],
    ["Latest ticket", latestTicket ? sourceLink(latestTicket, latestTicket.id) : "None", latestTicket?.title || "No ticket loaded"],
    ["Latest run", latestRun ? sourceLink(latestRun, latestRun.id) : "None", latestRun?.owner_role || "No run loaded"],
    ["Decisions", String(pendingDecisions), "Inbox and approvals"],
    ["Evidence", `${reviews.length} reviews`, `${releases.length} release records`],
    ["Context packs", String(contextPacks.length), `${learning.length} learning records`],
  ];
  document.getElementById("missionCards").innerHTML = cards.map(([label, value, detail]) => `<article class="mission-card"><span class="muted">${escapeHtml(label)}</span><strong>${value}</strong><small class="muted">${escapeHtml(detail)}</small></article>`).join("");
}

function renderDecisionQueue(inbox, approvals, blockedTickets) {
  const items = [...inbox.map((item) => ({ ...item, _kind: "Inbox" })), ...approvals.map((item) => ({ ...item, _kind: "Approval" })), ...blockedTickets.map((item) => ({ ...item, _kind: "Blocked" }))].filter((item) => !["closed", "routed", "archived", "cancelled", "approved"].includes(item.status));
  setText("decisionCount", `${items.length} items`);
  document.getElementById("decisionQueue").innerHTML = items.length ? items.map(renderRecordCard).join("") : emptyState("No pending decisions.");
}

function renderStageBoard(tickets, records) {
  document.getElementById("stageBoard").innerHTML = STAGE_GROUPS.map((stage) => {
    const stageTickets = tickets.filter((ticket) => stage.statuses.includes(ticket.status));
    return `<section class="stage-column"><div class="stage-title"><span>${escapeHtml(stage.label)}</span><span>${stageTickets.length}</span></div><div class="ticket-list">${stageTickets.length ? stageTickets.map((ticket) => renderTicketCard(ticket, records)).join("") : emptyState("Empty")}</div></section>`;
  }).join("");
}

function renderTicketCard(ticket, records) {
  const runCount = records.runs.filter((run) => run.related_ticket_id === ticket.id).length;
  const reviewCount = records.reviews.filter((review) => review.related_ticket_id === ticket.id).length;
  return `<article class="ticket-card"><strong>${sourceLink(ticket, ticket.id)}</strong><div>${escapeHtml(ticket.title || "Untitled ticket")}</div><div class="ticket-meta">${chip(ticket.status)}${chip(ticket.owner_role || "unowned")}${runCount ? chip(`${runCount} run${runCount === 1 ? "" : "s"}`) : ""}${reviewCount ? chip(`${reviewCount} review${reviewCount === 1 ? "" : "s"}`) : ""}</div></article>`;
}

function renderRoleRoster(tickets, runs) {
  const roles = new Map();
  for (const role of ROLE_DEPARTMENTS.keys()) roles.set(role, { role, tickets: [], runs: [] });
  for (const ticket of tickets) {
    const role = ticket.owner_role || "Unassigned";
    if (!roles.has(role)) roles.set(role, { role, tickets: [], runs: [] });
    roles.get(role).tickets.push(ticket);
  }
  for (const run of runs) {
    const role = run.owner_role || "Unassigned";
    if (!roles.has(role)) roles.set(role, { role, tickets: [], runs: [] });
    roles.get(role).runs.push(run);
  }
  const roleCards = Array.from(roles.values()).filter((entry) => entry.tickets.length || entry.runs.length || ROLE_DEPARTMENTS.has(entry.role)).sort((a, b) => b.tickets.length - a.tickets.length || a.role.localeCompare(b.role));
  document.getElementById("roleRoster").innerHTML = roleCards.map((entry) => {
    const latestTicket = sortById(entry.tickets).at(-1);
    const activeCount = entry.tickets.filter((ticket) => !FINAL_TICKET_STATUSES.has(ticket.status)).length;
    const status = activeCount ? "active" : entry.runs.length ? "idle" : "available";
    return `<article class="role-card"><strong>${escapeHtml(entry.role)}</strong><div class="muted">${escapeHtml(ROLE_DEPARTMENTS.get(entry.role) || "Project")}</div><div class="record-meta">${chip(status)}${chip(`${entry.tickets.length} ticket${entry.tickets.length === 1 ? "" : "s"}`)}${chip(`${entry.runs.length} run${entry.runs.length === 1 ? "" : "s"}`)}</div><small class="muted">${latestTicket ? escapeHtml(latestTicket.title || latestTicket.id) : "No assigned ticket"}</small></article>`;
  }).join("");
}

function renderContextPanel(tickets, contextPacks, reviews) {
  const latestTicket = sortById(tickets).at(-1);
  const latestContext = contextPacks.find((pack) => pack.id === latestTicket?.required_context_pack_id) || contextPacks[0];
  const freshReviewCount = reviews.filter((review) => review.review_type === "fresh_context").length;
  const items = [
    { title: "Latest context pack", value: latestContext ? sourceLink(latestContext, latestContext.id || latestContext.title) : "None", status: latestContext?.status || "missing" },
    { title: "Context packs", value: String(contextPacks.length), status: "available" },
    { title: "Fresh-context reviews", value: String(freshReviewCount), status: freshReviewCount ? "passed" : "waiting" },
  ];
  document.getElementById("contextPanel").innerHTML = items.map((item) => `<article class="context-item"><strong>${escapeHtml(item.title)}</strong><div>${item.value}</div><div class="record-meta">${chip(item.status)}</div></article>`).join("");
}

function renderReleaseLane(releases) {
  if (!releases.length) {
    document.getElementById("releaseLane").innerHTML = emptyState("No release records.");
    return;
  }
  const rows = sortById(releases).reverse().slice(0, 10).map((release) => `<tr><td>${sourceLink(release, release.id)}</td><td>${escapeHtml(release.title || "Untitled release")}</td><td>${chip(release.status)}</td><td>${escapeHtml(ensureList(release.ticket_ids).join(", "))}</td><td>${escapeHtml(truncate(release.release_notes || release.release_decision || "", 110))}</td></tr>`).join("");
  document.getElementById("releaseLane").innerHTML = table(["Release", "Scope", "Status", "Tickets", "Notes"], rows);
}

function renderLearningQueue(learning) {
  setText("learningCount", `${learning.length} items`);
  document.getElementById("learningQueue").innerHTML = learning.length ? learning.map(renderRecordCard).join("") : emptyState("No learning records.");
}

function renderRunLedger(runs) {
  if (!runs.length) {
    document.getElementById("runLedger").innerHTML = emptyState("No run records.");
    return;
  }
  const rows = sortById(runs).reverse().slice(0, 12).map((run) => `<tr><td>${sourceLink(run, run.id)}</td><td>${escapeHtml(run.related_ticket_id || "")}</td><td>${chip(run.status)}</td><td>${escapeHtml(run.owner_role || "")}</td><td>${escapeHtml(truncate(run.output_summary || "", 130))}</td><td>${escapeHtml(truncate(run.next_action || "", 120))}</td></tr>`).join("");
  document.getElementById("runLedger").innerHTML = table(["Run", "Ticket", "Status", "Owner", "Output", "Next"], rows);
}

function renderRecordCard(record) {
  return `<article class="record-item"><strong>${sourceLink(record, record.id || record._kind || record.title || "Record")}</strong><div>${escapeHtml(record.title || record.objective || record.summary || "")}</div><div class="record-meta">${chip(record._kind || record.object_type || "record")}${chip(record.status || "unknown")}</div></article>`;
}

function table(headers, rows) {
  return `<table><thead><tr>${headers.map((header) => `<th>${escapeHtml(header)}</th>`).join("")}</tr></thead><tbody>${rows}</tbody></table>`;
}

function sourceLink(record, label) {
  if (!record?._source) return escapeHtml(label || "record");
  return `<a href="${escapeHtml(record._source)}">${escapeHtml(label || record.id || record.title || "record")}</a>`;
}

function chip(value) {
  const normalized = String(value || "unknown");
  return `<span class="chip ${statusClass(normalized)}">${escapeHtml(normalized.replaceAll("_", " "))}</span>`;
}

function statusClass(status) {
  if (["release_ready", "ready", "completed", "passed", "promoted", "available", "released"].includes(status)) return "is-good";
  if (["active", "in_progress", "assigned", "self_review", "external_review", "testing", "idle"].includes(status)) return "is-active";
  if (["review", "fresh_context", "self_review"].includes(status)) return "is-review";
  if (["waiting", "revision", "changes_requested", "missing"].includes(status)) return "is-warn";
  if (["blocked", "failed", "cancelled", "rejected"].includes(status)) return "is-bad";
  return "";
}

function emptyState(message) { return `<div class="empty-state">${escapeHtml(message)}</div>`; }
function setText(id, value) { document.getElementById(id).textContent = value; }
function setStatus(message) { selectors.dataStatus.textContent = message; }
function ensureList(value) { return Array.isArray(value) ? value : value === null || value === undefined || value === "" ? [] : [value]; }
function sortById(items) { return [...items].sort((a, b) => String(a.id || a._filename || "").localeCompare(String(b.id || b._filename || ""), undefined, { numeric: true })); }
function truncate(value, limit) {
  const text = String(value || "").replace(/\s+/g, " ").trim();
  return text.length <= limit ? text : `${text.slice(0, limit - 1).trim()}...`;
}
function escapeHtml(value) {
  return String(value || "").replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;").replaceAll("'", "&#039;");
}