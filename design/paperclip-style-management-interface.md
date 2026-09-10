# Paperclip-Style Factory Management Interface

Status: planning baseline
Date: 2026-06-08

## Purpose

This note turns the owner's request for a larger Paperclip-like Factory interface into a staged development plan.

The current dashboard is useful for loading local ops data and seeing high-level state. The next version should become an interface for managing and understanding Factory work: tasks, tickets, agents, handoffs, communications, decisions, evidence, and next actions.

The goal is not to copy Paperclip's server product or autonomous-agent-company framing. The goal is to adapt its control-plane structure to the local-first Factory system: Markdown/YAML/JSON ops records, VS Code/Copilot execution, explicit review and release gates, and the owner as founder/decision-maker.

## Source Inputs

- [The Factory Manual Workflow](manual-workflow.md)
- [The Factory Operating Model](operating-model.md)
- [V0 Operating Objects](v0-operating-objects.md)
- [Factory Role Registry](../agents/role-registry.md)
- Specialist read-only passes on Paperclip, Factory process, and dashboard architecture from the 2026-06-08 management-dashboard planning session

## Product Stance

The Factory management interface should be a local control plane over file-backed work, not a hidden autonomous runtime.

- VS Code/Copilot remains the execution harness.
- `ops/` files remain the source of truth.
- The dashboard visualizes and coordinates work.
- Write actions should arrive only through a deliberate CLI/server/webview bridge with validation and approval rules.
- The interface should show who is doing what, why, from which context, with which evidence, and what is blocked or next.

## Control-Plane Object Map

| Paperclip Object | Factory Object | Current State | Next Interface Need |
|---|---|---|---|
| Company | Project/workspace scope | `project_id`, project folder, workboard | Project selector and current company/project header |
| Agent | Role / department specialist | Role registry and department packs | Roster cards with status, current work, handoff target, last activity |
| Goal | Project goal | `goal_id` on tasks/tickets | Goal/feature drill-down and grouping |
| Issue | Task/ticket | `TASK-*`, `TICKET-*` | Task detail, ticket detail, stage board, dependency view |
| Checkout | Active ownership | `owner_role`, `assigned_agent` | Visible current owner and future checkout/claim semantics |
| Heartbeat | Run/session | `RUN-*` JSON | Run timeline, liveness, who did what, output, next action |
| Approval | Approval gate | `approvals/` template exists; few live examples | Approval cards and lifecycle board |
| Interaction | Agent/founder communication | scattered in runs, reviews, inbox | Dedicated interaction/event stream or structured fields |
| Routine | Recurring maintenance | deferred | Later scheduled maintenance, never v0 hidden automation |
| Plugin | Extension module | deferred | Later explicit capability modules, visible in audit trail |

## Interface Systems

### 1. Mission Control

One-screen health view.

Should show:

- active project/workspace
- task and ticket counts by stage
- blocked tickets and pending decision count
- active or next recommended role
- recent run and release readiness
- stale or missing next-action warnings

### 2. Work Hierarchy Browser

Navigate Project -> Goal -> Feature -> Task -> Ticket.

For each task:

- associated tickets
- ticket progress by stage
- blockers and dependencies
- required reviewers
- release readiness
- next critical ticket

For each ticket:

- stage, owner, assigned agent, priority, risk
- acceptance criteria and scope
- context pack
- related runs
- related self/fresh reviews
- release checklist
- approvals and founder inbox items
- next owner/action
- files touched and test evidence

### 3. Agent Roster And Org View

The roster should not imply autonomous background workers. It should make role responsibility legible.

Each role card should show:

- department
- current ticket/task if any
- status: available, active, waiting, reviewing, blocked, release-ready
- last run/update
- allowed authority boundary
- escalation owner or next handoff role

### 4. Agent Communication And Handoff View

In the current Factory, communication is file-backed state rather than chat.

The interface should render communication as a timeline assembled from:

- ticket assignment fields
- run output summaries
- run `next_action`
- review decisions and required revisions
- release decisions
- founder inbox items
- approval records
- learning candidates

The dedicated interaction object is now part of the Factory ops contract for structured communication:

```yaml
template_version: "0.1"
object_type: interaction
id: INTERACTION-YYYY-0001
type: ask_user_questions # suggest_tasks | request_confirmation | raise_blocker | handoff | status_update
status: open
project_id: PROJECT
related_task_id: TASK-YYYY-0001
related_ticket_id: TICKET-YYYY-0001
from_role: "Execution Agent"
to_role: "Review / QA"
summary: "Ready for fresh review."
options: []
recommendation: ""
blocks_object_ids: []
created_at: "YYYY-MM-DDT00:00:00Z"
updated_at: "YYYY-MM-DDT00:00:00Z"
```

This gives the dashboard a communication feed without needing real-time chat. Founder inbox and approval objects remain the right place for decisions that block work or require explicit authorization; interactions are lighter cards for handoff, status, questions, confirmations, and task suggestions.

### 5. Decision And Approval Board

Paperclip's most useful UI lesson is to make important pauses explicit.

Decision cards should show:

- question or decision needed
- options
- recommendation
- impact if unanswered
- related ticket/task
- approver or founder owner
- unblock action

V1 remains read-only. V2/V3 can write answers through a controlled bridge.

### 6. Run And Evidence Ledger

Every ticket should answer: who did what?

Run detail should show:

- run owner role and agent
- objective
- input refs
- output summary
- changed files
- test commands and results
- blocker IDs
- created inbox or learning IDs
- next action

Reviews and release checklists should appear in the same evidence chain.

### 7. Context Panel

For a selected task or ticket, show:

- active context pack
- relevant project docs
- source notes in scope
- constraints and stop conditions
- required reviewers
- accepted decisions
- stale/missing context warning

## Data Model Gaps

The current files are enough for the management overview, but not enough for a full Paperclip-like interface.

Needed additions or stronger conventions:

- `next_owner_role` on tickets, or computed from status.
- `status_reason_code`, `waiting_on_object_id`, and `unblock_action` for blocked/waiting work.
- `handoff_notes_to_next_agent` and `incoming_agent_notes` on runs.
- `session_note_ref` or `transcript_ref` on runs when durable context exists.
- More concrete `approval` examples with approver role, lifecycle, options, and decision.
- More concrete `inbox` examples with question, options, recommendation, answer, and unblocked objects.
- Optional `interactions/` folder for structured communication cards.
- Optional `events/` or run event JSONL later if tool-call/liveness traces matter.

Do not migrate all existing ops records to one format yet. The dashboard can continue reading JSON, YAML, and Markdown frontmatter. Convert only if repeated dashboard or validation friction justifies it.

## Read-Only Versus Writable Boundary

### Read-Only Now

- folder loading
- indexing and filtering
- task/ticket drill-down
- related-object graph
- run/review/release timelines
- decision cards from existing files
- role roster and workload
- context panel
- local UI state in browser storage

### Requires CLI, Local Server, Or VS Code Webview Later

- creating tickets/tasks/inbox items from the dashboard
- updating ticket stage/status
- assigning or checking out a ticket
- answering founder inbox items
- approving/rejecting approvals
- creating review/release records
- file watching and live auto-refresh
- running validation commands
- git staging/commit/push flows

### Safety Rules

- No hidden scheduled agents.
- No credentials in dashboard v1.
- No automatic commits.
- No broad filesystem write path.
- Show source file for every rendered object.
- Any future write path must validate the object and leave an audit trail.

## Staged Development Plan

### Phase 1: Paperclip-Like Read-Only Drill-Down

Goal: make the current dashboard useful as an interface, not only a board.

Tickets:

- `DASH-001`: Build in-memory relationship index across tasks, tickets, runs, reviews, releases, inbox, approvals, learning, and context packs.
- `DASH-002`: Add task detail view with child tickets, progress by stage, blockers, required reviewers, and release readiness.
- `DASH-003`: Add ticket detail view with tabs for overview, context, runs, reviews, approvals/inbox, release, files/tests, and next action.
- `DASH-004`: Add run/review/release timeline for selected ticket so the owner can see who did what.
- `DASH-005`: Add search and filters by status, owner role, department, priority, risk, and blocker state.

Definition of done:

- Click a task and see all associated tickets.
- Click a ticket and see related runs, reviews, release, and context pack.
- Dashboard computes next owner/action from status and existing objects where possible.
- No write actions.

### Phase 2: Communication And Decision Cards

Goal: surface agent communication and decisions as first-class UI.

Tickets:

- `DASH-101`: Define `interaction` object template and folder convention.
- `DASH-102`: Render agent communication timeline from current runs/reviews/releases/inbox plus optional interactions.
- `DASH-103`: Render decision cards from founder inbox and approval objects with options, recommendation, and unblock impact.
- `DASH-104`: Add handoff card rendering from run next-action and future handoff fields.

Definition of done:

- Agent/founder questions are visible as cards, not buried in prose.
- Ticket detail shows assignment, handoff, review, revision, and release communications.
- Still read-only.

### Phase 3: Data Contract Tightening

Goal: make ops records reliably support the interface.

Tickets:

- `DASH-201`: Add schema guidance for `next_owner_role`, `status_reason_code`, `waiting_on_object_id`, and `unblock_action`.
- `DASH-202`: Add concrete approval and founder inbox examples to templates and live docs.
- `DASH-203`: Add optional handoff fields to run template.
- `DASH-204`: Add dashboard validation report for missing relations and malformed IDs.

Definition of done:

- New tickets/runs/reviews provide enough structure for dashboard detail views.
- Missing links and stale records are visible.

### Phase 4: CLI Bridge For Safe Writes

Goal: reduce manual file editing without giving the browser direct unchecked write power.

Tickets:

- `DASH-301`: Create local `factory` helper for create-ticket, update-status, create-inbox, and create-run.
- `DASH-302`: Create context-pack generator from ticket scope and related docs.
- `DASH-303`: Create validation command for ops link integrity and required fields.
- `DASH-304`: Add dashboard export/prompt handoff that feeds the CLI or VS Code workflow.

Definition of done:

- the owner can start a role/ticket from dashboard context without hand-assembling all files.
- Writes are explicit, validated, and inspectable in git.

### Phase 5: Writable Control Plane

Goal: make the dashboard operational after authority rules are clear.

Tickets:

- `DASH-401`: Add local sidecar or VS Code webview write bridge.
- `DASH-402`: Implement safe ticket checkout/assignment.
- `DASH-403`: Implement decision/approval answer workflow.
- `DASH-404`: Implement review/release creation workflow.
- `DASH-405`: Add audit trail and rollback/previous-hash metadata for mutations.

Definition of done:

- Dashboard can update safe ops fields through a trusted local bridge.
- Every write has validation, source, actor, timestamp, and git visibility.

### Phase 6: Project Workspace Rollout

Goal: use the interface on a real Factory-managed project.

Tickets:

- `DASH-501`: Apply dashboard to first future Factory-managed workspace, likely [project].
- `DASH-502`: Capture first-use friction as learning candidates.
- `DASH-503`: Tighten project-local ops templates based on real work.
- `DASH-504`: Decide whether the dashboard remains brain-local, becomes template-local, or both.

Definition of done:

- The dashboard helps the owner understand a real project session, not only Factory self-build history.

## Recommended Next Ticket

Start with `DASH-001`: relationship index and ticket/task drill-down design in the current browser dashboard.

This is the highest-leverage next step because it supports everything the owner asked for: task -> tickets, ticket -> who did what, stage, next owner/action, and agent communication timeline. It also stays read-only, so it does not force the CLI/server authority decision yet.
