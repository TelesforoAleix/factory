# The Factory V0 Operating Objects

Status: v0 design draft

This document defines the first operating objects for The Factory. These are not dashboard components yet. They are the file-backed state objects that future templates, CLI helpers, agents, and a local dashboard can read and write.

The guiding split is:

- Markdown holds specs, product truth, architecture, docs, PRDs, decisions, and narrative summaries.
- YAML, JSON, or Markdown with structured frontmatter holds operational state: tasks, tickets, runs, inbox items, approvals, context packs, reviews, releases, and learning candidates.

## Shared Conventions

### Work Hierarchy

```text
Project -> Goal -> Feature -> Task -> Ticket
```

- A ticket is the smallest assignable unit.
- Every ticket belongs to exactly one task.
- A task can contain many tickets.
- Bugs, chores, and follow-ups are tickets under an existing task, or under a new task when no existing task fits.

### ID Prefixes

Suggested v0 prefixes:

| Object | Prefix | Example |
|---|---|---|
| Task | `TASK` | `TASK-2026-0001` |
| Ticket | `TICKET` | `TICKET-2026-0001` |
| Run / Session | `RUN` | `RUN-2026-0001` |
| Founder Inbox Item | `INBOX` | `INBOX-2026-0001` |
| Approval | `APPROVAL` | `APPROVAL-2026-0001` |
| Context Pack | `CP` | `CP-2026-0001` |
| Review Record | `REVIEW` | `REVIEW-2026-0001` |
| Release Checklist | `RELEASE` | `RELEASE-2026-0001` |
| Learning Candidate | `LEARN` | `LEARN-2026-0001` |

IDs should be stable and human-readable. The exact generator can come later.

### Common Fields

Most objects should share these fields:

- `id`
- `title`
- `status`
- `owner_role`
- `project_id`
- `created_at`
- `updated_at`
- `related_docs`
- `related_objects`

Use timestamps in ISO 8601 format when possible.

### Status Rule

Status values should be explicit and boring. The dashboard can become pretty later; the files should stay easy for agents and humans to inspect.

### Storage Rule

V0 should prefer one file per object. This keeps git diffs, agent handoffs, and manual recovery simple.

Recommended future structure:

```text
ops/
  tasks/
  tickets/
  runs/
  interactions/
  inbox/
  approvals/
  context-packs/
  reviews/
  releases/
  learning/
  dashboard-state/
  archive/
```

## Object Overview

| Object | Primary Owner | Recommended Storage | Example Future File |
|---|---|---|---|
| Task | Product / Feature Owner | YAML | `ops/tasks/TASK-2026-0001.yaml` |
| Ticket | Product / Feature Owner until assigned; Execution Agent while active | YAML | `ops/tickets/TICKET-2026-0001.yaml` |
| Run / Session | Executive Orchestrator or assigned agent | JSON for run state, optional JSONL events | `ops/runs/RUN-2026-0001.json` |
| Interaction / Communication Card | Source role, then target role or Founder Interface | YAML | `ops/interactions/INTERACTION-2026-0001.yaml` |
| Founder Inbox Item | Founder Interface | YAML | `ops/inbox/INBOX-2026-0001.yaml` |
| Approval | Release Agent, Reviewer, or Founder Interface depending level | YAML | `ops/approvals/APPROVAL-2026-0001.yaml` |
| Context Pack | Architect / Context Architect | Markdown with YAML frontmatter | `ops/context-packs/CP-2026-0001.md` |
| Review Record | Review / QA Agent or specialist reviewer | YAML for v0 state, optional linked Markdown for long findings | `ops/reviews/REVIEW-2026-0001.yaml` |
| Release Checklist | Release Agent | Markdown with YAML frontmatter | `ops/releases/RELEASE-2026-0001.md` |
| Learning Candidate | Knowledge / Documentation Agent, then Optimization Department | YAML with optional Markdown note | `ops/learning/LEARN-2026-0001.yaml` |

## 1. Task

### Purpose

A task is a larger unit of work inside a feature. It groups one or more tickets that together deliver a coherent slice of product or system value.

Tasks preserve intent above individual execution tickets. They help The Factory batch coherent tickets into review, release, and documentation updates.

### Owner

Primary owner: Product / Feature Owner.

Supporting owners: Executive Orchestrator, Architect / Context Architect, Release Agent.

### Lifecycle / Statuses

```text
inbox -> discovery -> planned -> active -> blocked -> release_ready -> shipped -> archived
cancelled
```

Meaning:

- `inbox`: captured but not shaped.
- `discovery`: product intent, dependencies, and acceptance criteria are being clarified.
- `planned`: tickets are created or ready to create.
- `active`: at least one child ticket is active.
- `blocked`: cannot proceed because a dependency, approval, or founder decision is unresolved.
- `release_ready`: all required tickets are ready for release evaluation.
- `shipped`: release agent has committed, merged, or otherwise completed the task-level release.
- `archived`: task is closed and retained for history.
- `cancelled`: task was intentionally stopped.

### Required Fields

- `id`
- `title`
- `status`
- `owner_role`
- `project_id`
- `goal_id`
- `feature_id`
- `summary`
- `intent`
- `acceptance_criteria`
- `ticket_ids`
- `required_reviewers`
- `release_strategy`
- `created_at`
- `updated_at`

### Optional Fields

- `priority`
- `risk_level`
- `dependencies`
- `constraints`
- `non_goals`
- `related_docs`
- `decision_refs`
- `inbox_item_ids`
- `approval_ids`
- `release_id`
- `archive_notes`

### Parent / Child Relations

- Parent: exactly one feature.
- Children: one or more tickets.
- Related: context packs, approvals, reviews, release checklist, learning candidates.

### Source Inspiration

- Paperclip: task ownership, control-plane visibility, dashboard grouping.
- gstack: Plan -> Build -> Review -> Test -> Release loop.
- ECC: department routing and ownership boundaries.

### Storage Format Recommendation

YAML. Tasks are structured operational state and should be easy for agents and a dashboard to parse.

### Dashboard Appearance

Task detail page or board group with:

- status
- feature and goal links
- child ticket progress
- blockers
- required reviewers
- release readiness
- latest activity

### What Can Block It

- blocked child ticket
- founder inbox item
- missing approval
- unresolved architecture/product decision
- failed review or test
- dependency on another task

### Writeback

- Project docs: update roadmap, PRD, architecture notes, changelog, or decision log when task scope changes product truth.
- Central brain: write back only if the task produces reusable Factory knowledge, agent improvements, or cross-project patterns.

### Example Future File

`ops/tasks/TASK-2026-0001.yaml`

## 2. Ticket

### Purpose

A ticket is the smallest assignable unit of work. It is what an execution agent normally receives.

Tickets make isolated sessions possible because they define one concrete objective, acceptance criteria, constraints, context pack, required reviewers, and expected output.

### Owner

Primary owner before assignment: Product / Feature Owner or Executive Orchestrator.

Primary owner during implementation: assigned Execution Agent.

Primary owner after handoff: Review / QA Agent, then Release Agent.

### Lifecycle / Statuses

```text
inbox -> discovery -> ready -> assigned -> in_progress -> self_review -> external_review -> testing -> revision -> release_ready -> shipped -> archived
blocked
cancelled
```

Meaning matches the operating model. `blocked` can interrupt any active state.

### Required Fields

- `id`
- `title`
- `status`
- `project_id`
- `goal_id`
- `feature_id`
- `task_id`
- `owner_role`
- `assigned_agent`
- `objective`
- `acceptance_criteria`
- `scope`
- `out_of_scope`
- `required_context_pack_id`
- `required_reviewers`
- `expected_outputs`
- `approval_level`
- `created_at`
- `updated_at`

### Optional Fields

- `priority`
- `risk_level`
- `dependencies`
- `blocking_object_ids`
- `founder_inbox_item_ids`
- `approval_ids`
- `run_ids`
- `review_ids`
- `test_evidence`
- `changed_files`
- `release_id`
- `notes`

### Parent / Child Relations

- Parent: exactly one task.
- Children: no work-object children in v0. A ticket can create follow-up tickets, but they still belong to a task.
- Related: one or more runs, context packs, reviews, approvals, inbox items, release checklist, learning candidates.

### Source Inspiration

- Paperclip: assignable work items, ownership, communication through state.
- gstack: ticket moves through build, review, QA, release, reflect.
- Claude Playbook: compact scope and review discipline.

### Storage Format Recommendation

YAML. Ticket state should be parseable, diffable, and directly usable by agents and future dashboard code.

### Dashboard Appearance

Ticket card with:

- title, status, and owner
- task/feature parent
- next required action
- blockers
- required reviewers
- current run or latest run
- release readiness badge

Opening the card should show acceptance criteria, context pack, run history, review results, approvals, and handoff notes.

### What Can Block It

- founder inbox item
- missing approval
- missing or stale context pack
- dependency ticket not shipped
- failed self-review, external review, or testing
- scope ambiguity
- security/privacy/architecture risk

### Writeback

- Project docs: update relevant specs, PRDs, decisions, architecture docs, changelog, and task state when ticket output changes product truth.
- Central brain: create a learning candidate when the ticket reveals reusable agent, skill, workflow, architecture, or product pattern learning.

### Example Future File

`ops/tickets/TICKET-2026-0001.yaml`

## 3. Run / Session

### Purpose

A run records one agent session or execution attempt against a ticket, review, release, or learning task.

It is The Factory's local equivalent of a heartbeat/run ledger: who worked, on what context, with what result, and what should happen next.

### Owner

Primary owner: the agent or orchestrator that starts the run.

Supporting owner: Executive Orchestrator for coordination and Knowledge / Documentation Agent for archival summaries.

### Lifecycle / Statuses

```text
queued -> active -> waiting -> completed -> failed -> cancelled -> archived
```

Meaning:

- `queued`: run is prepared but not started.
- `active`: agent session is in progress.
- `waiting`: run needs input, tool result, review, or external action.
- `completed`: run produced a handoff result.
- `failed`: run ended without usable output.
- `cancelled`: intentionally stopped.
- `archived`: durable summary retained and raw details moved or linked.

### Required Fields

- `id`
- `status`
- `project_id`
- `run_type`
- `owner_role`
- `agent_id`
- `started_at`
- `updated_at`
- `related_ticket_id`
- `context_pack_id`
- `objective`
- `input_refs`
- `output_summary`
- `result_status`
- `next_action`

### Optional Fields

- `ended_at`
- `related_task_id`
- `related_review_id`
- `related_release_id`
- `tool_events_ref`
- `transcript_ref`
- `changed_files`
- `test_commands`
- `test_results`
- `blocker_ids`
- `created_inbox_item_ids`
- `created_learning_candidate_ids`
- `cost_or_budget_notes`

### Parent / Child Relations

- Parent: usually one ticket, review, release checklist, or learning candidate.
- Children: optional generated inbox items, approvals, reviews, or learning candidates.
- Related: context pack and transcript/session summary.

### Source Inspiration

- Paperclip: heartbeats, activity feed, run/session ledger.
- Hermes: searchable session history and reflection.
- gstack: each workflow stage leaves evidence.

### Storage Format Recommendation

JSON for current run state. Optional JSONL for event streams when the bridge/dashboard needs append-only events.

Keep long narrative summaries in a linked Markdown session note when useful.

### Dashboard Appearance

Run row or activity card with:

- status
- agent and role
- linked ticket/review/release
- started time and duration
- latest heartbeat or result
- blockers
- next action

### What Can Block It

- missing context pack
- waiting for founder answer
- tool failure
- dependency on another run
- approval gate
- ambiguous or invalid ticket scope

### Writeback

- Project docs: usually no direct writeback unless the run produced a decision, implementation result, or documentation update.
- Central brain: summarize only reusable lessons, agent failures, or improvement candidates. Do not flood the brain with routine run state.

### Example Future File

`ops/runs/RUN-2026-0001.json`

## 4. Interaction / Communication Card

### Purpose

An interaction records a structured communication between Factory roles, or between a role and the founder interface, when the message should be visible in the dashboard but does not yet require a full founder inbox item or approval gate.

Interactions are the file-backed equivalent of Paperclip-style issue comments, handoff notes, agent questions, status updates, and confirmation requests.

### Owner

Primary owner: the role that creates the interaction.

Supporting owner: Executive Orchestrator or Founder Interface when the interaction changes routing, blocks work, or needs the owner's attention.

### Lifecycle / Statuses

```text
open -> presented -> answered -> routed -> closed -> archived
superseded
cancelled
```

Meaning:

- `open`: created and visible, not yet handled.
- `presented`: surfaced to the intended recipient or dashboard view.
- `answered`: recipient gave an answer or response.
- `routed`: answer or result has been written back to the related object.
- `closed`: no further action needed.
- `archived`: retained for history.
- `superseded`: replaced by a newer interaction, inbox item, approval, or ticket.
- `cancelled`: no longer relevant.

### Interaction Types

- `status_update`: role reports current state or handoff note.
- `handoff`: one role passes work to another role.
- `ask_user_questions`: structured question for the owner or Founder Interface.
- `request_confirmation`: asks for approval to proceed with a bounded action.
- `suggest_tasks`: proposes follow-up tasks or tickets.
- `raise_blocker`: records a blocker that needs routing.
- `decision_answer`: records an answer routed back from founder/interface work.

### Required Fields

- `id`
- `title`
- `type`
- `status`
- `project_id`
- `related_ticket_id`
- `from_role`
- `to_role`
- `summary`
- `created_at`
- `updated_at`

### Optional Fields

- `related_task_id`
- `message`
- `options`
- `recommendation`
- `blocks_object_ids`
- `source_object_ids`
- `outcome`
- `priority`
- `answered_by`
- `answered_at`
- `routed_to`
- `supersedes_interaction_id`

### Parent / Child Relations

- Parent: usually one ticket; can also relate to a task or release.
- Children: may create inbox items, approvals, reviews, releases, learning candidates, or follow-up tickets.
- Related: source run, review, release, inbox, or approval that caused the interaction.

### Source Inspiration

- Paperclip: issue interactions, task suggestions, user questions, and confirmation requests.
- The Factory manual workflow: handoff, blocker, review, and release evidence.
- Founder Interface: structured questions and decision routing.

### Storage Format Recommendation

YAML. Interaction cards should be easy to parse, filter, and show in the dashboard.

### Dashboard Appearance

Communication card with:

- interaction type
- status
- from role -> to role
- related ticket/task
- concise summary
- options and recommendation when present
- blocker or source object links

### What Can Block It

- unanswered question
- missing routing target
- missing context from the source role
- escalation into founder inbox or approval gate

### Writeback

- Project ops: route answer/outcome back to related tickets, tasks, approvals, or reviews.
- Project docs: write durable decisions into design docs or decision notes when they change project truth.
- Central brain: only promote reusable communication patterns after repeated evidence.

### Example Future File

`ops/interactions/INTERACTION-2026-0001.yaml`

## 5. Founder Inbox Item

### Purpose

A founder inbox item is a decision, question, or escalation that the owner should answer through the founder interface/personal assistant.

It blocks related work when the system cannot responsibly continue without founder judgment.

### Owner

Primary owner: Founder Interface.

Supporting owners: Executive Orchestrator and the agent that raised the item.

### Lifecycle / Statuses

```text
open -> presented -> answered -> routed -> closed -> archived
blocked_by_followup
cancelled
```

Meaning:

- `open`: created but not yet presented to the owner.
- `presented`: surfaced through dashboard or personal assistant.
- `answered`: the owner provided an answer.
- `routed`: answer has been written back to the relevant ticket/task/docs.
- `closed`: no further action needed.
- `archived`: retained for history.
- `blocked_by_followup`: answer needs clarification.
- `cancelled`: no longer relevant.

### Required Fields

- `id`
- `title`
- `status`
- `project_id`
- `owner_role`
- `raised_by_agent`
- `related_ticket_id`
- `decision_needed`
- `context_summary`
- `options`
- `recommendation`
- `why_recommended`
- `impact_if_unanswered`
- `blocks_object_ids`
- `created_at`
- `updated_at`

### Optional Fields

- `related_task_id`
- `related_feature_id`
- `priority`
- `deadline`
- `pros_cons`
- `answer`
- `answered_at`
- `answered_by`
- `routed_to`
- `followup_questions`
- `related_approval_id`
- `decision_doc_ref`

### Parent / Child Relations

- Parent: usually one ticket; can also relate to a task, feature, or project decision.
- Children: optional approval, follow-up ticket, decision note, or learning candidate.
- Blocks: one or more tickets or tasks.

### Source Inspiration

- Paperclip: inbox, approvals, agent-to-founder visibility.
- The Factory discovery: the owner answers through a personal assistant, then work unblocks.
- gstack: decision checkpoints before drift.

### Storage Format Recommendation

YAML. Inbox items need structured options, recommendations, blocking refs, and answer fields.

### Dashboard Appearance

Inbox card with:

- decision title
- linked ticket/task
- urgency and blocker count
- concise context
- up to three options
- recommendation and why
- answer status

### What Can Block It

- unanswered founder question
- unclear answer requiring follow-up
- missing context from the raising agent
- conflicting product or architecture decision

### Writeback

- Project docs: write final decisions into decision logs, PRDs, specs, architecture docs, or ticket/task state.
- Central brain: write back only if the answer changes reusable Factory rules, the owner's durable preferences, or cross-project product principles.

### Example Future File

`ops/inbox/INBOX-2026-0001.yaml`

## 6. Approval

### Purpose

An approval records permission to proceed through a gate: reviewer approval, release approval, founder approval, architecture approval, security/privacy approval, or external-service approval.

Approvals make authority explicit and auditable.

### Owner

Primary owner depends on approval level:

- Level 0: no approval object needed unless audit is useful.
- Level 1: reviewer or release agent.
- Level 2: Founder Interface records the owner's approval.
- Level 3: blocked until explicit product or architecture decision is resolved.

### Lifecycle / Statuses

```text
requested -> pending -> approved -> rejected -> superseded -> archived
expired
```

### Required Fields

- `id`
- `title`
- `status`
- `project_id`
- `approval_type`
- `approval_level`
- `requested_by`
- `approver_role`
- `related_object_ids`
- `request_summary`
- `decision`
- `created_at`
- `updated_at`

### Optional Fields

- `approved_by`
- `approved_at`
- `rejected_reason`
- `conditions`
- `expires_at`
- `evidence_refs`
- `founder_inbox_item_id`
- `supersedes_approval_id`
- `risk_notes`

### Parent / Child Relations

- Parent: one or more tickets, tasks, releases, inbox items, or docs.
- Children: may create revision tickets or decision docs.
- Related: review records and release checklists.

### Source Inspiration

- Paperclip: approval cards and founder-facing control plane.
- Cybersecurity Skills: explicit authorization and risk review.
- Claude Playbook: placement discipline for hooks, permissions, and high-risk changes.

### Storage Format Recommendation

YAML. Approval state should be easy to query and show in a dashboard.

### Dashboard Appearance

Approval card or gate badge with:

- approval type and level
- requesting object
- approver
- status
- conditions
- evidence
- expiration if any

### What Can Block It

- missing founder answer
- missing reviewer evidence
- security/privacy concern
- unclear authority
- expired approval
- conflicting decision

### Writeback

- Project docs: decision logs, architecture docs, security/privacy notes, release notes, or ticket state when approval changes what can happen.
- Central brain: reusable approval policies, default thresholds, or security/privacy rules can promote back to Factory docs or `agents/` after validation.

### Example Future File

`ops/approvals/APPROVAL-2026-0001.yaml`

## 7. Context Pack

### Purpose

A context pack is the bounded packet of information given to an execution, review, release, or specialist agent.

It lets agents work in isolated sessions without pulling the entire project or brain into context.

### Owner

Primary owner: Architect / Context Architect.

Supporting owners: Product / Feature Owner, Executive Orchestrator, Review / QA Agent.

### Lifecycle / Statuses

```text
draft -> ready -> assigned -> consumed -> stale -> archived
superseded
```

### Required Fields

- `id`
- `title`
- `status`
- `project_id`
- `pack_type`
- `target_role`
- `related_ticket_id`
- `objective`
- `acceptance_criteria`
- `required_inputs`
- `relevant_files`
- `relevant_docs`
- `constraints`
- `prior_decisions`
- `expected_output`
- `reporting_format`
- `created_at`
- `updated_at`

### Optional Fields

- `related_task_id`
- `related_review_id`
- `specialist_concerns`
- `excluded_context`
- `retrieval_notes`
- `token_budget_notes`
- `source_confidence`
- `staleness_check`
- `supersedes_context_pack_id`

### Parent / Child Relations

- Parent: usually one ticket, review, release, or learning candidate.
- Children: runs that consume the pack.
- Related: source docs, specs, decision records, reviews.

### Source Inspiration

- Prompt Master: prompt/context wrapper structure.
- ECC: agent/skill/rule architecture and context boundaries.
- Paperclip: work packets for visible agent coordination.
- Hermes: separation between session memory, skills, and durable knowledge.

### Storage Format Recommendation

Markdown with YAML frontmatter.

The frontmatter holds machine-readable metadata. The body holds the actual agent-facing packet.

### Dashboard Appearance

Context panel with:

- target role
- linked ticket/review
- readiness/staleness
- included docs/files
- constraints
- expected output
- copy/start-run action later

### What Can Block It

- missing acceptance criteria
- stale product or architecture docs
- missing file references
- unresolved founder decision
- unclear target role
- context too broad or too thin

### Writeback

- Project docs: context packs should not become product truth, but stale or missing context can trigger documentation updates.
- Central brain: reusable context-pack patterns can become templates in Factory docs or `agents/` skills after validation.

### Example Future File

`ops/context-packs/CP-2026-0001.md`

## 8. Review Record

### Purpose

A review record captures fresh-context review, specialist review, or QA assessment against the original intent and acceptance criteria.

Review is separate from testing. Review asks whether the work matches intent and quality expectations; testing asks whether it works.

### Owner

Primary owner: Review / QA Agent.

Specialist owner when relevant: Security, Privacy/GDPR, UX/UI, Data, Architecture, Context, Performance, or Marketing/Copy reviewer.

### Lifecycle / Statuses

```text
requested -> in_progress -> passed -> changes_requested -> failed -> superseded -> archived
```

### Required Fields

- `id`
- `title`
- `status`
- `project_id`
- `review_type`
- `reviewer_role`
- `related_ticket_id`
- `context_pack_id`
- `original_intent`
- `acceptance_criteria_checked`
- `implementation_summary`
- `findings`
- `decision`
- `created_at`
- `updated_at`

### Optional Fields

- `related_task_id`
- `specialist_area`
- `risk_level`
- `changed_files_reviewed`
- `test_evidence_refs`
- `required_revisions`
- `followup_ticket_ids`
- `approval_ids`
- `reviewer_confidence`
- `notes`

### Parent / Child Relations

- Parent: one ticket, release checklist, or task.
- Children: revision tickets, approvals, or learning candidates.
- Related: context pack, run, release checklist.

### Source Inspiration

- gstack: dedicated review and QA skills.
- Cybersecurity Skills: specialist review anatomy and verification discipline.
- Claude Playbook: compact review workflow and placement discipline.

### Storage Format Recommendation

YAML for the first v0 state template. Review decisions and metadata should be parseable by agents and a future dashboard. If findings become narrative-heavy, link a Markdown note or revisit Markdown with YAML frontmatter later.

### Dashboard Appearance

Review panel or badge with:

- reviewer role and type
- pass/fail/changes requested
- severity of findings
- required revisions
- linked evidence
- specialist flags

### What Can Block It

- missing implementation summary
- missing context pack
- incomplete changed-file list
- missing test evidence for risk level
- specialist reviewer unavailable
- unresolved acceptance criteria

### Writeback

- Project docs: update docs only when review changes decisions, requirements, architecture, or known risks.
- Central brain: reusable review failures, checklists, and specialist patterns become learning candidates for `agents/` or Factory docs.

### Example Future File

`ops/reviews/REVIEW-2026-0001.yaml`

## 9. Release Checklist

### Purpose

A release checklist records whether one ticket or a coherent task-level batch is ready to commit, PR, merge, ship, or archive.

The release agent owns this gate because execution agents do not commit directly.

### Owner

Primary owner: Release Agent.

Supporting owners: Review / QA Agent, Executive Orchestrator, Knowledge / Documentation Agent.

### Lifecycle / Statuses

```text
draft -> evaluating -> ready -> released -> rejected -> revision_requested -> archived
```

### Required Fields

- `id`
- `title`
- `status`
- `project_id`
- `release_scope`
- `owner_role`
- `related_task_id`
- `ticket_ids`
- `review_ids`
- `approval_ids`
- `test_evidence`
- `docs_updated`
- `scope_match`
- `release_decision`
- `created_at`
- `updated_at`

### Optional Fields

- `branch_name`
- `commit_message`
- `pr_url`
- `release_notes`
- `changed_files`
- `migration_notes`
- `rollback_notes`
- `blocked_by`
- `batching_reason`
- `post_release_followups`

### Parent / Child Relations

- Parent: one task for a task-level release, or one ticket for a ticket-level release.
- Children: optional follow-up tickets, learning candidates, release notes.
- Related: approvals, reviews, runs, docs.

### Source Inspiration

- gstack: ship/release discipline and review-before-ship workflow.
- Claude Playbook: commit/PR discipline and compact checklists.
- Paperclip: release state as visible control-plane object.

### Storage Format Recommendation

Markdown with YAML frontmatter. The checklist itself is human-readable; the frontmatter drives dashboard status.

### Dashboard Appearance

Release gate card with:

- task/ticket scope
- checklist completion
- reviews and approvals
- test evidence
- docs status
- commit/PR readiness
- release decision

### What Can Block It

- incomplete self-review
- failed or missing external review
- missing tests/checks
- unresolved founder approval
- scope mismatch
- missing documentation update
- dirty or unsafe repository state

### Writeback

- Project docs: changelog, release notes, task/ticket status, roadmap, decision log when needed.
- Central brain: release workflow improvements become learning candidates; canonical release-agent changes require validation before promotion.

### Example Future File

`ops/releases/RELEASE-2026-0001.md`

## 10. Learning Candidate

### Purpose

A learning candidate captures something The Factory might want to remember, improve, or promote into reusable agents, skills, templates, or project docs.

It is not automatically canonical. Hermes inspires capture and reflection; SkillOpt inspires validation before promotion.

### Owner

Primary owner at capture: Knowledge / Documentation Agent.

Primary owner for validation and promotion: Optimization Department.

Department owners can propose candidates for their own agents and skills.

### Lifecycle / Statuses

```text
captured -> triaged -> candidate -> validating -> promoted -> rejected -> archived
parked
```

Meaning:

- `captured`: raw lesson or possible improvement recorded.
- `triaged`: owner decides whether it is project-specific, reusable, or noise.
- `candidate`: concrete improvement proposal exists.
- `validating`: tested against examples, rubric, or representative tasks.
- `promoted`: accepted into project docs, central brain knowledge, or canonical `agents/` assets.
- `rejected`: intentionally not adopted, with reason preserved.
- `parked`: plausible but not worth validation yet.
- `archived`: no further active work.

### Required Fields

- `id`
- `title`
- `status`
- `project_id`
- `owner_role`
- `source_object_ids`
- `learning_type`
- `problem_observed`
- `proposed_change`
- `scope`
- `evidence`
- `promotion_target`
- `created_at`
- `updated_at`

### Optional Fields

- `department`
- `related_agent_or_skill`
- `validation_task_ids`
- `score_before`
- `score_after`
- `rejected_reason`
- `promotion_pr_or_commit`
- `brain_writeback_ref`
- `project_doc_writeback_ref`
- `notes`

### Parent / Child Relations

- Parent: run, ticket, review, release, inbox item, or session.
- Children: validation tasks, proposed skill patches, doc updates, rejected-change memory.
- Related: central brain knowledge notes and `agents/` assets when promoted.

### Source Inspiration

- Hermes: learning intake, background reflection, curation, session search.
- SkillOpt: validation, scoring, promotion, rejected-change memory.
- ECC: continuous learning across departments.

### Storage Format Recommendation

YAML for the project-local candidate. Use linked Markdown when a candidate needs longer reflection or validation notes.

Project-local candidates start in project `ops/learning/`. Reusable, validated improvements can promote into the central brain or `agents/`.

### Dashboard Appearance

Improvement queue item with:

- source ticket/run/review
- learning type
- reusable vs project-specific scope
- validation status
- promotion target
- rejected/promoted reason

### What Can Block It

- weak evidence
- unclear promotion target
- no validation task
- conflict with existing Factory rules
- project-specific lesson mistaken for reusable rule
- rejected prior attempt

### Writeback

- Project docs: project-specific lessons can update local docs, decisions, templates, or operating rules.
- Central brain: reusable validated lessons can update Factory design docs, knowledge notes, or canonical `agents/` skills/agents.
- Rejected changes: preserve reason so the same weak improvement is not proposed repeatedly.

### Example Future File

`ops/learning/LEARN-2026-0001.yaml`

## V0 Template Implications

Initial project-design templates now live in [Ops Templates](../templates/ops/README.md):

- `task.yaml`
- `ticket.yaml`
- `run.json`
- `founder-inbox-item.yaml`
- `approval.yaml`
- `context-pack.md`
- `review-record.yaml`
- `release-checklist.md`
- `learning-candidate.yaml`

Do not build the dashboard from this document yet. Use it first to stabilize the architecture, templates, and manual workflow.

## Open Refinements

- Choose exact ID-generation rules.
- Decide whether run events need JSONL in v0 or whether one JSON state file is enough.
- Decide whether context packs, review records, and release checklists should share a common frontmatter schema.
- Define validation tasks for learning candidates before promoting changes into `agents/`.
- Define how project `ops/` objects are archived after shipping.
