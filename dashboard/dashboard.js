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

const state = { directoryHandle: null, loadedLabel: "", records: emptyRecords(), indexes: buildIndexes(emptyRecords()), selected: null };
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
document.addEventListener("click", inspectClickedRecord);
render(emptyRecords());

function inspectClickedRecord(event) {
  const trigger = event.target.closest("[data-inspect-type][data-inspect-id]");
  if (!trigger) return;
  event.preventDefault();
  state.selected = { type: trigger.dataset.inspectType, id: trigger.dataset.inspectId };
  renderSelectedDetail(state.records, state.indexes);
}

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
  return { tickets: [], tasks: [], runs: [], reviews: [], releases: [], inbox: [], approvals: [], learning: [], contextPacks: [], interactions: [] };
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
    if (folder === "interactions") records.interactions.push(record);
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

function buildIndexes(records) {
  const indexes = {
    byId: new Map(),
    ticketsByTask: new Map(),
    runsByTicket: new Map(),
    reviewsByTicket: new Map(),
    releasesByTicket: new Map(),
    inboxByObject: new Map(),
    approvalsByObject: new Map(),
    learningByObject: new Map(),
    contextPacksById: new Map(),
    eventsByObject: new Map(),
    communicationEvents: [],
  };

  for (const collection of Object.values(records)) {
    for (const record of collection) {
      if (record.id) indexes.byId.set(record.id, record);
    }
  }

  for (const ticket of records.tickets) addIndexed(indexes.ticketsByTask, ticket.task_id, ticket);
  for (const run of records.runs) addIndexed(indexes.runsByTicket, run.related_ticket_id, run);
  for (const review of records.reviews) addIndexed(indexes.reviewsByTicket, review.related_ticket_id, review);
  for (const contextPack of records.contextPacks) {
    if (contextPack.id) indexes.contextPacksById.set(contextPack.id, contextPack);
  }

  for (const release of records.releases) {
    for (const ticketId of ensureList(release.ticket_ids)) addIndexed(indexes.releasesByTicket, ticketId, release);
  }

  for (const item of records.inbox) {
    for (const objectId of relatedObjectIds(item)) addIndexed(indexes.inboxByObject, objectId, item);
  }

  for (const approval of records.approvals) {
    for (const objectId of relatedObjectIds(approval)) addIndexed(indexes.approvalsByObject, objectId, approval);
  }

  for (const learning of records.learning) {
    for (const objectId of relatedObjectIds(learning)) addIndexed(indexes.learningByObject, objectId, learning);
  }

  indexes.communicationEvents = buildCommunicationEvents(records);
  for (const event of indexes.communicationEvents) {
    for (const objectId of event.relatedIds) addIndexed(indexes.eventsByObject, objectId, event);
  }

  return indexes;
}

function relatedObjectIds(record) {
  return [
    ...ensureList(record.related_objects),
    ...ensureList(record.related_object_ids),
    ...ensureList(record.source_object_ids),
    ...ensureList(record.blocks_object_ids),
    ...ensureList(record.blocking_object_ids),
    record.related_ticket_id,
    record.related_task_id,
  ].filter(Boolean);
}

function addIndexed(map, key, value) {
  if (!key) return;
  if (!map.has(key)) map.set(key, []);
  map.get(key).push(value);
}

function buildCommunicationEvents(records) {
  const events = [];

  for (const run of records.runs) {
    events.push({
      id: run.id,
      kind: "Run",
      status: run.status,
      actor: run.owner_role || run.agent_id || "Agent",
      target: run.related_ticket_id || run.related_task_id || "Factory",
      summary: run.output_summary || run.objective || run.next_action || "Run recorded.",
      next: run.next_action || "",
      source: run._source,
      relatedIds: [run.id, run.related_ticket_id, run.related_task_id, run.related_release_id, run.context_pack_id].filter(Boolean),
      sortValue: eventSortValue(run),
    });
  }

  for (const review of records.reviews) {
    events.push({
      id: review.id,
      kind: review.review_type === "self_review" ? "Self Review" : "Fresh Review",
      status: review.decision || review.status,
      actor: review.reviewer_role || "Reviewer",
      target: review.related_ticket_id || review.related_task_id || "Factory",
      summary: review.implementation_summary || review.title || "Review recorded.",
      next: ensureList(review.required_revisions).join("; "),
      source: review._source,
      relatedIds: [review.id, review.related_ticket_id, review.related_task_id, review.context_pack_id].filter(Boolean),
      sortValue: eventSortValue(review),
    });
  }

  for (const release of records.releases) {
    const ticketIds = ensureList(release.ticket_ids);
    events.push({
      id: release.id,
      kind: "Release",
      status: release.status || release.release_decision,
      actor: release.owner_role || "Release Agent",
      target: ticketIds.join(", ") || release.related_task_id || "Factory",
      summary: release.release_notes || release.title || "Release checklist recorded.",
      next: ensureList(release.post_release_followups).join("; "),
      source: release._source,
      relatedIds: [release.id, release.related_task_id, ...ticketIds, ...ensureList(release.review_ids)].filter(Boolean),
      sortValue: eventSortValue(release),
    });
  }

  for (const item of records.inbox) events.push(recordToCommunicationEvent(item, "Founder Inbox", item.owner_role || "Founder Interface"));
  for (const approval of records.approvals) events.push(recordToCommunicationEvent(approval, "Approval", approval.approver_role || approval.owner_role || "Approver"));
  for (const learning of records.learning) events.push(recordToCommunicationEvent(learning, "Learning", learning.owner_role || learning.department || "Optimization"));
  for (const interaction of records.interactions) events.push(recordToCommunicationEvent(interaction, interaction.type || "Interaction", interaction.from_role || interaction.owner_role || "Agent"));

  return events.sort((a, b) => b.sortValue.localeCompare(a.sortValue, undefined, { numeric: true }));
}

function recordToCommunicationEvent(record, kind, actor) {
  return {
    id: record.id,
    kind,
    status: record.status || "unknown",
    actor,
    target: record.related_ticket_id || record.related_task_id || ensureList(record.blocks_object_ids)[0] || ensureList(record.source_object_ids)[0] || "Factory",
    summary: record.summary || record.title || record.question_text || record.problem_observed || record.proposed_change || "Record created.",
    next: record.recommendation || record.unblock_action || record.notes || "",
    source: record._source,
    relatedIds: [record.id, ...relatedObjectIds(record)].filter(Boolean),
    sortValue: eventSortValue(record),
  };
}

function eventSortValue(record) {
  return String(record.updated_at || record.ended_at || record.created_at || record.started_at || record.id || "");
}

function render(records) {
  state.indexes = buildIndexes(records);
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
  renderStageBoard(tickets, state.indexes);
  renderTaskExplorer(records.tasks, state.indexes);
  renderSelectedDetail(records, state.indexes);
  renderRoleRoster(tickets, runs);
  renderContextPanel(tickets, contextPacks, reviews);
  renderReleaseLane(releases);
  renderLearningQueue(learning);
  renderCommunicationFeed(state.indexes.communicationEvents);
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

function renderStageBoard(tickets, indexes) {
  document.getElementById("stageBoard").innerHTML = STAGE_GROUPS.map((stage) => {
    const stageTickets = tickets.filter((ticket) => stage.statuses.includes(ticket.status));
    return `<section class="stage-column"><div class="stage-title"><span>${escapeHtml(stage.label)}</span><span>${stageTickets.length}</span></div><div class="ticket-list">${stageTickets.length ? stageTickets.map((ticket) => renderTicketCard(ticket, indexes)).join("") : emptyState("Empty")}</div></section>`;
  }).join("");
}

function renderTicketCard(ticket, indexes) {
  const runCount = ensureList(indexes.runsByTicket.get(ticket.id)).length;
  const reviewCount = ensureList(indexes.reviewsByTicket.get(ticket.id)).length;
  const next = computeNextStep(ticket, indexes);
  return `<article class="ticket-card"><strong>${inspectButton(ticket, ticket.id)}</strong><div>${escapeHtml(ticket.title || "Untitled ticket")}</div><div class="ticket-meta">${chip(ticket.status)}${chip(ticket.owner_role || "unowned")}${runCount ? chip(`${runCount} run${runCount === 1 ? "" : "s"}`) : ""}${reviewCount ? chip(`${reviewCount} review${reviewCount === 1 ? "" : "s"}`) : ""}</div><small class="muted">Next: ${escapeHtml(next.owner)} - ${escapeHtml(truncate(next.action, 72))}</small></article>`;
}

function renderTaskExplorer(tasks, indexes) {
  const sortedTasks = sortById(tasks).reverse();
  document.getElementById("taskExplorer").innerHTML = sortedTasks.length ? sortedTasks.map((task) => renderTaskCard(task, indexes)).join("") : emptyState("No tasks loaded.");
}

function renderTaskCard(task, indexes) {
  const tickets = ensureList(indexes.ticketsByTask.get(task.id));
  const doneCount = tickets.filter((ticket) => FINAL_TICKET_STATUSES.has(ticket.status)).length;
  const blockedCount = tickets.filter((ticket) => ticket.status === "blocked" || ensureList(ticket.blocking_object_ids).length).length;
  const nextTicket = nextTicketForTask(tickets, indexes);
  return `
    <article class="task-card">
      <strong>${inspectButton(task, task.id)}</strong>
      <div>${escapeHtml(task.title || "Untitled task")}</div>
      <div class="record-meta">
        ${chip(task.status || "unknown")}
        ${chip(`${doneCount}/${tickets.length} done`)}
        ${blockedCount ? chip(`${blockedCount} blocked`) : ""}
      </div>
      <small class="muted">Next: ${nextTicket ? escapeHtml(nextTicket.title || nextTicket.id) : "No child ticket loaded"}</small>
    </article>
  `;
}

function renderSelectedDetail(records, indexes) {
  const selectedRecord = selectedRecordFor(records, indexes);
  if (!selectedRecord) {
    document.getElementById("detailPanel").innerHTML = emptyState("Load ops data and select a task or ticket.");
    document.getElementById("detailPanelNote").textContent = "No selection";
    return;
  }

  document.getElementById("detailPanelNote").textContent = selectedRecord.id || selectedRecord.title || "Selected";
  if (selectedRecord.object_type === "task") {
    document.getElementById("detailPanel").innerHTML = renderTaskDetail(selectedRecord, indexes);
    return;
  }
  if (selectedRecord.object_type === "ticket") {
    document.getElementById("detailPanel").innerHTML = renderTicketDetail(selectedRecord, indexes);
    return;
  }
  document.getElementById("detailPanel").innerHTML = renderGenericDetail(selectedRecord);
}

function selectedRecordFor(records, indexes) {
  if (state.selected?.id && indexes.byId.has(state.selected.id)) return indexes.byId.get(state.selected.id);
  const defaultTask = sortById(records.tasks).at(-1);
  const defaultTicket = sortById(records.tickets).at(-1);
  const selectedRecord = defaultTask || defaultTicket || null;
  state.selected = selectedRecord ? { type: selectedRecord.object_type, id: selectedRecord.id } : null;
  return selectedRecord;
}

function renderTaskDetail(task, indexes) {
  const tickets = sortById(ensureList(indexes.ticketsByTask.get(task.id))).reverse();
  const statusSummary = summarizeStatuses(tickets);
  const nextTicket = nextTicketForTask(tickets, indexes);
  return `
    <div class="detail-section">
      <h3>${sourceLink(task, task.id)}</h3>
      <p>${escapeHtml(task.summary || task.intent || "")}</p>
      <div class="detail-meta">${chip(task.status || "unknown")}${chip(task.owner_role || "unowned")}${chip(`${tickets.length} ticket${tickets.length === 1 ? "" : "s"}`)}</div>
    </div>
    <div class="detail-grid">
      <article class="detail-card"><strong>Progress</strong><div>${escapeHtml(statusSummary || "No child tickets loaded")}</div></article>
      <article class="detail-card"><strong>Next Critical Ticket</strong><div>${nextTicket ? inspectButton(nextTicket, nextTicket.id) : "None"}</div><small class="muted">${escapeHtml(nextTicket?.title || "")}</small></article>
    </div>
    <div class="detail-section">
      <h3>Associated Tickets</h3>
      <div class="detail-stack">${tickets.length ? tickets.map((ticket) => renderTicketCard(ticket, indexes)).join("") : emptyState("No tickets linked to this task.")}</div>
    </div>
  `;
}

function renderTicketDetail(ticket, indexes) {
  const runs = sortById(ensureList(indexes.runsByTicket.get(ticket.id))).reverse();
  const reviews = sortById(ensureList(indexes.reviewsByTicket.get(ticket.id))).reverse();
  const releases = sortById(ensureList(indexes.releasesByTicket.get(ticket.id))).reverse();
  const contextPack = indexes.contextPacksById.get(ticket.required_context_pack_id);
  const inboxItems = ensureList(indexes.inboxByObject.get(ticket.id));
  const approvals = ensureList(indexes.approvalsByObject.get(ticket.id));
  const learning = ensureList(indexes.learningByObject.get(ticket.id));
  const next = computeNextStep(ticket, indexes);

  return `
    <div class="detail-section">
      <h3>${sourceLink(ticket, ticket.id)}</h3>
      <p>${escapeHtml(ticket.objective || ticket.title || "")}</p>
      <div class="detail-meta">${chip(ticket.status || "unknown")}${chip(ticket.owner_role || "unowned")}${chip(ticket.priority || "normal")}${chip(ticket.risk_level || "risk unknown")}</div>
    </div>
    <div class="detail-grid">
      <article class="detail-card"><strong>Parent Task</strong><div>${recordReference(ticket.task_id, indexes)}</div></article>
      <article class="detail-card"><strong>Next Owner / Action</strong><div>${escapeHtml(next.owner)}</div><small class="muted">${escapeHtml(next.action)}</small></article>
      <article class="detail-card"><strong>Context Pack</strong><div>${contextPack ? sourceLink(contextPack, contextPack.id) : escapeHtml(ticket.required_context_pack_id || "Missing")}</div></article>
      <article class="detail-card"><strong>Evidence</strong><div>${runs.length} runs, ${reviews.length} reviews, ${releases.length} releases</div></article>
    </div>
    <div class="detail-section"><h3>Acceptance Criteria</h3>${renderList(ticket.acceptance_criteria, "No acceptance criteria loaded.")}</div>
    <div class="detail-section"><h3>Communication Timeline</h3>${renderCommunicationFeedList(ensureList(indexes.eventsByObject.get(ticket.id)), "No communication events linked.")}</div>
    <div class="detail-section"><h3>Runs: Who Did What</h3>${runs.length ? table(["Run", "Owner", "Status", "Output", "Next"], runs.map(renderRunRow).join("")) : emptyState("No runs linked.")}</div>
    <div class="detail-section"><h3>Reviews</h3>${reviews.length ? table(["Review", "Type", "Decision", "Summary"], reviews.map(renderReviewRow).join("")) : emptyState("No reviews linked.")}</div>
    <div class="detail-section"><h3>Release</h3>${releases.length ? table(["Release", "Status", "Decision", "Notes"], releases.map(renderReleaseRow).join("")) : emptyState("No release checklist linked.")}</div>
    <div class="detail-section"><h3>Decisions, Approvals, Learning</h3><div class="detail-stack">${renderRelatedCards([...inboxItems, ...approvals, ...learning])}</div></div>
    <div class="detail-section"><h3>Files And Tests</h3><div class="detail-grid"><article class="detail-card"><strong>Changed Files</strong>${renderList(ticket.changed_files, "No changed files listed.")}</article><article class="detail-card"><strong>Test Evidence</strong>${renderList(ticket.test_evidence, "No test evidence listed.")}</article></div></div>
  `;
}

function renderGenericDetail(record) {
  return `<div class="detail-section"><h3>${sourceLink(record, record.id || record.title || "Record")}</h3><pre>${escapeHtml(JSON.stringify(record, null, 2))}</pre></div>`;
}

function renderRunRow(run) {
  return `<tr><td>${sourceLink(run, run.id)}</td><td>${escapeHtml(run.owner_role || "")}</td><td>${chip(run.status)}</td><td>${escapeHtml(truncate(run.output_summary || "", 120))}</td><td>${escapeHtml(truncate(run.next_action || "", 110))}</td></tr>`;
}

function renderReviewRow(review) {
  return `<tr><td>${sourceLink(review, review.id)}</td><td>${escapeHtml(review.review_type || "")}</td><td>${chip(review.decision || review.status)}</td><td>${escapeHtml(truncate(review.implementation_summary || review.title || "", 120))}</td></tr>`;
}

function renderReleaseRow(release) {
  return `<tr><td>${sourceLink(release, release.id)}</td><td>${chip(release.status)}</td><td>${escapeHtml(release.release_decision || "")}</td><td>${escapeHtml(truncate(release.release_notes || "", 120))}</td></tr>`;
}

function renderRelatedCards(records) {
  return records.length ? records.map(renderRecordCard).join("") : emptyState("No decisions, approvals, or learning records linked.");
}

function renderCommunicationFeed(events) {
  const latestEvents = ensureList(events).slice(0, 14);
  document.getElementById("communicationFeed").innerHTML = renderCommunicationFeedList(latestEvents, "No communication events loaded.");
  document.getElementById("communicationFeedNote").textContent = `${latestEvents.length} recent events`;
}

function renderCommunicationFeedList(events, emptyMessage) {
  const values = sortCommunicationEvents(ensureList(events));
  if (!values.length) return emptyState(emptyMessage);
  return values.map(renderCommunicationCard).join("");
}

function sortCommunicationEvents(events) {
  return [...events].sort((a, b) => String(b.sortValue || b.id || "").localeCompare(String(a.sortValue || a.id || ""), undefined, { numeric: true }));
}

function renderCommunicationCard(event) {
  return `
    <article class="communication-card">
      <div>
        <div class="communication-kind">${escapeHtml(event.kind || "Event")}</div>
        <div class="record-meta">${chip(event.status || "unknown")}</div>
      </div>
      <div>
        <div>${event.source ? `<a href="${escapeHtml(event.source)}">${escapeHtml(event.id || "event")}</a>` : escapeHtml(event.id || "event")}</div>
        <div class="communication-target">${escapeHtml(event.actor || "Agent")} -> ${escapeHtml(event.target || "Factory")}</div>
        <div class="communication-summary">${escapeHtml(truncate(event.summary || "", 170))}</div>
        ${event.next ? `<small class="muted">Next: ${escapeHtml(truncate(event.next, 140))}</small>` : ""}
      </div>
    </article>
  `;
}

function renderList(items, emptyMessage) {
  const values = ensureList(items);
  if (!values.length) return emptyState(emptyMessage);
  return `<ul class="detail-list">${values.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>`;
}

function recordReference(id, indexes) {
  if (!id) return "None";
  const record = indexes.byId.get(id);
  return record ? inspectButton(record, id) : escapeHtml(id);
}

function inspectButton(record, label) {
  if (!record?.id) return escapeHtml(label || "record");
  return `<button class="link-button" type="button" data-inspect-type="${escapeHtml(record.object_type || "record")}" data-inspect-id="${escapeHtml(record.id)}">${escapeHtml(label || record.id)}</button>`;
}

function nextTicketForTask(tickets, indexes) {
  return tickets.find((ticket) => !FINAL_TICKET_STATUSES.has(ticket.status) && ticket.status !== "blocked") || tickets.find((ticket) => ticket.status === "blocked") || tickets[0] || null;
}

function summarizeStatuses(tickets) {
  const counts = new Map();
  for (const ticket of tickets) counts.set(ticket.status || "unknown", (counts.get(ticket.status || "unknown") || 0) + 1);
  return Array.from(counts.entries()).map(([status, count]) => `${count} ${status.replaceAll("_", " ")}`).join(", ");
}

function computeNextStep(ticket, indexes) {
  const latestRun = sortById(ensureList(indexes.runsByTicket.get(ticket.id))).at(-1);
  const action = latestRun?.next_action || statusDefaultAction(ticket.status);
  if (ticket.status === "blocked" || ensureList(ticket.blocking_object_ids).length) return { owner: "Founder Interface / Orchestrator", action: action || "Resolve blocker before continuing." };
  if (["inbox", "discovery", "ready"].includes(ticket.status)) return { owner: "Product / Feature Owner", action };
  if (["assigned", "in_progress", "self_review"].includes(ticket.status)) return { owner: ticket.owner_role || "Execution Agent", action };
  if (["external_review", "testing"].includes(ticket.status)) return { owner: "Review / QA", action };
  if (ticket.status === "revision") return { owner: "Execution Agent", action };
  if (ticket.status === "release_ready") return { owner: "Release Agent / Next planning owner", action };
  return { owner: ticket.owner_role || "Executive Orchestrator", action };
}

function statusDefaultAction(status) {
  if (status === "release_ready") return "Use release evidence or choose the next project slice.";
  if (status === "revision") return "Apply required revisions, then request review again.";
  if (status === "external_review") return "Complete fresh-context review.";
  if (status === "testing") return "Complete validation and record test evidence.";
  if (status === "blocked") return "Resolve the linked blocker or founder decision.";
  return "Continue through the Factory workflow.";
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