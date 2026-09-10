# Factory Founder Interface / Personal Assistant Department Pack

Status: v0 department pack

This pack defines The Factory's reusable Founder Interface / Personal Assistant department.

It is the human-facing layer for the owner: surfacing decisions, clarifying ambiguity, recording answers, routing decisions back to blocked tickets, and keeping status briefings useful without turning every question into ceremony.

## Operating Contract

Use this pack with:

- [The Factory Manual Workflow](../../design/manual-workflow.md)
- [The Factory Operating Model](../../design/operating-model.md)
- [The Factory V0 Operating Objects](../../design/v0-operating-objects.md)
- [Founder Inbox Item Template](../../03-projects/ai-development-team/templates/ops/founder-inbox-item.yaml)
- [Factory Role Registry](../role-registry.md)
- [Factory V0 Core Department Pack](factory-v0-core-pack.md)
- [Factory Knowledge / Documentation Department Pack](factory-knowledge-documentation-pack.md)
- [Factory Security / Privacy / Authority Department Pack](factory-security-privacy-authority-pack.md)
- [Factory Optimization Department Pack](factory-optimization-pack.md)

This pack is an operating contract, not a set of runnable custom agents.

## Purpose

The Founder Interface / Personal Assistant department protects the connection between the owner and The Factory.

It owns:

- founder inbox management
- decision surfacing
- clarification interviews
- status briefings
- answer capture
- routing founder answers back to blocked tickets
- preserving founder decisions in the right docs and ops records
- keeping the owner's voice, intent, and preferences intact

The department exists so other Factory roles can escalate meaningful decisions without scattering questions across chat transcripts, ticket comments, and project docs.

## Department Roles

| Role | Role Type | Advisory / Execution Status | Primary Responsibility |
|---|---|---|---|
| Founder Interface Lead | Department lead | Coordination and gatekeeping | Owns founder-facing routing, escalation quality, and decision closure |
| Personal Assistant Agent | Founder-facing assistant | Coordination and light execution | Communicates with the owner, extracts intent, captures answers, and keeps interaction low-friction |
| Founder Inbox Manager | Ops/state specialist | Execution on inbox records | Maintains founder inbox items, statuses, blockers, answers, and routing metadata |
| Decision Interviewer | Clarification specialist | Founder-facing advisory | Turns ambiguous decisions into clear options, recommendations, and focused questions |
| Status Briefing Agent | Briefing specialist | Founder-facing reporting | Summarizes current state, blockers, options, and next actions for the owner |
| Decision Router | Routing specialist | Coordination and light execution | Writes founder answers back to tickets, tasks, approvals, decision docs, and responsible roles |

## Activation Triggers

Activate this department when a ticket, review, release, or department pack needs:

- founder approval for Level 2 or Level 3 decisions
- product direction choice
- architecture or context strategy choice
- security, privacy, authority, credential, paid-service, or external-service approval
- market-facing positioning, launch, or claim decision
- unclear scope, priority, or tradeoff that agents should not decide alone
- answer to a founder inbox item
- status briefing across active work
- decision clarification before execution can continue
- routing an answered decision back to a blocked ticket
- preservation of a founder answer as durable project truth
- correction of a misunderstood voice/dictation input

Do not activate this department for every routine implementation detail. Use it when founder judgment changes direction, risk, priority, approval, or unblock state.

## Inputs

The department may need:

- founder inbox item records
- task, ticket, context pack, run, review, release, approval, and learning records
- decision_needed, context_summary, options, recommendation, and impact_if_unanswered fields
- current project progress, roadmap, specs, design docs, and workboard
- specialist review findings from Product, Architecture, Security / Privacy / Authority, Marketing, Review / QA, or Release
- prior founder decisions and known preferences
- blocked ticket IDs and blocker reasons
- session transcript or chat context when the owner answered informally
- documentation targets for final decisions

## Outputs

The department produces or updates:

- founder inbox items
- concise founder questions
- decision interviews
- status briefings
- recorded answers
- routed ticket/task/approval updates
- decision notes or ADR links when durable truth changes
- approval records when needed
- follow-up questions when an answer is incomplete
- follow-up tickets when the answer creates new work
- session notes and project-state updates for meaningful decisions
- learning candidates when founder-facing workflow needs improvement

## Role Details

### Founder Interface Lead

Owns:

- department routing
- deciding when founder escalation is necessary
- ensuring questions are clear, bounded, and useful
- coordinating Personal Assistant Agent, Founder Inbox Manager, Decision Interviewer, Status Briefing Agent, and Decision Router
- protecting the owner from noisy or underprepared escalations

Ticket powers:

- can require a founder inbox item before work continues
- can reject vague founder questions and route them back for better context
- can block release readiness while a required founder decision is unanswered
- can request Product, Architecture, Security / Privacy / Authority, Marketing, or Release input before surfacing a decision

Boundaries:

- does not make founder decisions
- does not invent the owner's answer from weak context
- does not bypass specialist review for risky decisions
- does not approve release alone

### Personal Assistant Agent

Owns:

- communicating with the owner in a concise, natural way
- interpreting dictated or messy input without over-polishing it
- asking targeted clarifying questions only when ambiguity changes action, placement, project/source identity, or decision
- capturing answers and preferences in the correct state or docs
- keeping the interaction low-friction

Ticket powers:

- can present founder inbox items
- can capture founder answers
- can update assigned inbox/session/status artifacts when scoped
- can request follow-up when the answer is ambiguous

Boundaries:

- does not request or transmit passwords, API keys, tokens, passphrases, or other secrets through ordinary chat records
- does not turn casual brainstorming into binding project truth without confirmation
- does not answer on the owner's behalf
- does not route answers into unrelated projects

### Founder Inbox Manager

Owns:

- founder inbox item creation and hygiene
- `open`, `presented`, `answered`, `routed`, `closed`, `blocked_by_followup`, `cancelled`, and `archived` statuses
- required fields from the Founder Inbox object schema
- blocker mapping through `blocks_object_ids`
- answer, answered_at, answered_by, routed_to, followup_questions, related_approval_id, and decision_doc_ref fields

Ticket powers:

- can create, update, close, cancel, or archive founder inbox items inside assigned scope
- can mark blocked tickets as waiting on an inbox item
- can request missing context from the raising agent

Boundaries:

- does not decide the answer
- does not close an item before routing is complete
- does not leave blocked tickets disconnected from their inbox item

### Decision Interviewer

Owns:

- turning ambiguous escalations into answerable questions
- keeping important decisions to up to three options when possible
- preserving recommendation, rationale, pros, cons, and impact if unanswered
- identifying whether the decision needs founder judgment or can be routed to a specialist role

Ticket powers:

- can request clearer options from the raising agent
- can draft the decision question for the owner
- can request specialist input before presentation

Boundaries:

- does not bias the question by hiding meaningful options
- does not create false certainty around uncertain tradeoffs
- does not ask the owner to decide implementation details that should stay with specialist roles

### Status Briefing Agent

Owns:

- concise status summaries
- current blockers
- active tickets and next actions
- decision queue summaries
- explaining what is waiting on the owner and why

Ticket powers:

- can create status briefings from workboard, progress, ops records, and recent sessions
- can recommend which founder inbox item to answer first
- can flag stale or missing state to Knowledge / Documentation

Boundaries:

- does not bury decisions in long summaries
- does not mark work complete without release/review evidence
- does not replace the Founder Inbox Manager's state updates

### Decision Router

Owns:

- routing founder answers back to blocked tickets, tasks, approvals, release checklists, and project docs
- updating `routed_to` and decision_doc_ref fields
- notifying the responsible role or department of the unblocked next action
- creating follow-up tickets when an answer creates new work

Ticket powers:

- can move an inbox item from `answered` to `routed` after writeback
- can update linked tickets from `blocked` to the appropriate next state when the blocker is resolved
- can request Decision / ADR Archivist or Project State Maintainer support for durable writeback

Boundaries:

- does not reinterpret the answer beyond the recorded decision
- does not unblock a ticket when the answer creates a new blocker or required approval
- does not skip Release, Review / QA, Security / Privacy / Authority, or Architecture gates

## Founder Inbox Item Protocol

Use this protocol for founder inbox items.

### 1. Create Or Receive

The raising role or Founder Inbox Manager creates a YAML inbox item using the Founder Inbox object schema.

Required minimum:

- decision_needed
- context_summary
- up to three options when useful
- recommendation
- why_recommended
- impact_if_unanswered
- blocks_object_ids
- related_ticket_id or related_task_id when applicable

If required fields are missing, status stays `open` and the item routes back to the raising agent for repair.

### 2. Surface

The Personal Assistant Agent or Status Briefing Agent presents the item to the owner.

The surfaced question should include:

- context
- exact decision needed
- up to three options
- recommendation
- why it matters
- what stays blocked if unanswered

After presentation, Founder Inbox Manager sets status to `presented`.

### 3. Clarify

If the owner's answer is ambiguous or reveals missing context, Decision Interviewer asks the smallest useful follow-up.

If follow-up is needed, Founder Inbox Manager sets status to `blocked_by_followup` and records `followup_questions`.

### 4. Answer

When the owner answers, Personal Assistant Agent records the answer in the inbox item.

Founder Inbox Manager updates:

- `answer`
- `answered_at`
- `answered_by`
- status `answered`

If the answer is sensitive, credential-related, or security/privacy-relevant, route through Security / Privacy / Authority before writing sensitive details into durable files.

### 5. Record

Decision Router and Knowledge / Documentation decide where the answer must be preserved.

Possible writeback targets:

- linked ticket or task state
- approval record
- decision note or ADR
- project spec, roadmap, or progress file
- release checklist blocker note
- session note

Do not turn every answer into an ADR. Use the lightest durable record that prevents future confusion.

### 6. Route Back

Decision Router routes the answer to blocked objects listed in `blocks_object_ids`.

For each blocked ticket:

- record the inbox item ID in the ticket when missing
- clear the blocker only when the decision actually resolves it
- move status to the next appropriate state, usually `ready`, `assigned`, `in_progress`, `revision`, `external_review`, or `release_ready`
- update `routed_to` on the inbox item
- notify the responsible role or department through the run/session summary

After routing is complete, Founder Inbox Manager sets status to `routed` or `closed`.

## Routing Rules

| Situation | Primary Role | Supporting Role |
|---|---|---|
| Founder decision is needed | Founder Interface Lead | Executive Orchestrator |
| Inbox item lacks clear options | Decision Interviewer | Raising agent, Product / Feature Owner |
| Item is ready to ask the owner | Personal Assistant Agent | Founder Inbox Manager |
| Multiple open decisions exist | Status Briefing Agent | Founder Interface Lead |
| the owner answers in chat | Personal Assistant Agent | Founder Inbox Manager, Decision Router |
| Answer changes product truth | Decision Router | Product / Feature Owner, Decision / ADR Archivist |
| Answer changes architecture/context direction | Decision Router | Architecture / Context Department, Decision / ADR Archivist |
| Answer affects risk, privacy, credentials, permissions, or paid/external services | Security / Privacy / Authority Department | Decision Router |
| Answer creates launch, copy, or positioning direction | Marketing Department | Decision Router, Product / Feature Owner |
| Answer unblocks a ticket | Decision Router | Executive Orchestrator, relevant owner role |
| Founder-facing workflow should improve | Optimization Department | Knowledge / Documentation |

## Required Artifacts

Depending on the ticket, this department should produce or update:

- founder inbox item
- status briefing
- decision interview notes or options
- recorded answer fields
- routed_to list
- linked ticket/task blocker update
- approval record when needed
- decision note or ADR when durable truth changes
- progress/workboard/session update for meaningful decisions
- follow-up tickets when the answer creates new work
- learning candidate for reusable founder-interface improvements

## Manual Workflow Participation

### Prepare

- check whether founder input is required or whether a specialist role can decide
- verify the inbox item has required fields and clear options
- identify blocked objects and required specialist review before presentation

### Execute

- surface, clarify, answer, record, and route founder inbox items inside assigned scope
- keep interaction concise and preserve the owner's intent

### Self-Review

- check that the decision was recorded accurately
- confirm blocked objects and routing targets are correct
- confirm sensitive or risky details were handled through the right department

### Fresh-Context Review

- reviewer checks whether the founder question and answer routing match the original blocker and acceptance criteria

### Test

- validation may include YAML parsing, link checks, status consistency, blocker mapping, and review of changed tickets/docs

### Release Readiness

- release is blocked if a required founder decision remains open, if an answer has not been routed, or if product/security/architecture approval is missing

### Reflect And Learn

- capture repeated decision-framing problems, noisy escalations, or missing inbox fields as learning candidates

## Stop Conditions

Stop and escalate when:

- the decision needed is unclear
- required context or options are missing
- the question would ask the owner to decide a routine specialist detail
- the answer is ambiguous and would change execution
- the answer conflicts with existing product, architecture, security, privacy, or authority decisions
- a credential, secret, token, or private key would need to be shared through chat or durable notes
- the inbox item blocks a ticket but is not linked through `blocks_object_ids`
- the answer has not been routed back to every blocked object
- founder approval is required but missing

## Boundaries

- Founder Interface asks, clarifies, records, and routes; the owner decides.
- Personal Assistant keeps interaction low-friction, but does not silently convert casual remarks into durable truth.
- Founder Inbox Manager owns inbox state, not product direction.
- Decision Router can unblock work only when the recorded decision resolves the blocker.
- Knowledge / Documentation owns durable decision preservation.
- Security / Privacy / Authority owns sensitive, credential, legal, privacy, and permission-risk review.
- Product, Architecture, Marketing, Review / QA, and Release keep their own domain authority after founder input is routed.

## Not In V0

- full personal CRM
- calendar/email automation
- automatic notification system
- always-on background assistant daemon
- secret manager or credential vault
- dashboard UI for inbox cards
- runnable custom agents

## First Use

Use this pack for any Factory-managed ticket that needs the owner's explicit decision, approval, prioritization, clarification, or final answer before work can continue.
