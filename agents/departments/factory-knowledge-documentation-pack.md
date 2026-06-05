# Factory Knowledge / Documentation Department Pack

Status: v0 department pack

This pack defines The Factory's reusable Knowledge / Documentation department.

It preserves project truth, operating continuity, decisions, documentation quality, session history, and reusable learning while Factory-managed work moves through tickets.

## Operating Contract

Use this pack with:

- [The Factory Manual Workflow](../../03-projects/ai-development-team/design/manual-workflow.md)
- [The Factory Operating Model](../../03-projects/ai-development-team/design/operating-model.md)
- [Factory Role Registry](../role-registry.md)
- [Factory V0 Core Department Pack](factory-v0-core-pack.md)
- [Factory Ops](../../03-projects/ai-development-team/ops/README.md)

This pack is an operating contract, not a set of runnable custom agents.

## Purpose

The Knowledge / Documentation department makes sure Factory work does not disappear into chat history or unstructured agent transcripts.

It owns the connective tissue between:

- product/design truth
- ops state
- sessions and runs
- decisions and ADRs
- documentation quality
- learning candidates
- reusable knowledge promotion

## Department Roles

| Role | Role Type | Advisory / Execution Status | Primary Responsibility |
|---|---|---|---|
| Knowledge / Documentation Lead | Department lead | Coordination and light execution | Owns docs/knowledge routing and decides what must be written back |
| Session Archivist | Documentation specialist | Execution on session/log artifacts | Creates and updates session notes and run summaries |
| Project State Maintainer | Ops/documentation specialist | Execution on state files | Keeps progress, workboard, roadmap, and active ops state aligned |
| Decision / ADR Archivist | Decision-record specialist | Execution on decision records | Captures decisions, ADRs, founder answers, and rationale |
| Docs Reviewer | Review specialist | Review role | Reviews docs for correctness, navigation, links, scope, and drift |
| Learning Candidate Router | Learning/optimization liaison | Coordination and advisory | Routes learning candidates toward project-local, reusable, validation, promotion, parked, or rejected states |

## Activation Triggers

Activate this department when a ticket:

- changes product/spec/design truth
- changes Factory docs, templates, roles, prompts, skills, or ops rules
- creates or closes meaningful tasks, tickets, reviews, releases, or learning candidates
- produces an important decision, ADR, founder answer, or approval
- has a session/run that changes current focus or next actions
- exposes documentation drift, stale links, unclear status, or missing navigation
- creates reusable learning that might belong in Factory docs or `04-agents/`
- has enough complexity that future agents will need a durable handoff trail

## Inputs

The department may need:

- task, ticket, context pack, run, review, release, approval, inbox, and learning records
- changed files and artifacts
- implementation or review summaries
- founder answers and decision context
- progress, roadmap, and design docs
- existing README/index/navigation files
- related knowledge/source notes
- current workboard and brain log when the session changes active state
- validation output such as wiki health, lint, tests, or review findings

## Outputs

The department produces or updates:

- session notes
- run/session summaries
- progress files
- workboard updates when active focus or next actions change
- brain log entries for meaningful events
- README/index/navigation links
- decision or ADR records
- documentation review findings
- learning candidates and routing decisions
- project doc updates when durable truth changes
- promotion recommendations for reusable knowledge, templates, agents, or skills

## Role Details

### Knowledge / Documentation Lead

Owns:

- department routing
- deciding which docs/state must be updated
- deciding whether learning is local, reusable, or canonical-candidate
- coordinating Session Archivist, Project State Maintainer, Decision / ADR Archivist, Docs Reviewer, and Learning Candidate Router

Ticket powers:

- can create documentation follow-up tickets
- can block release readiness when required docs/state are missing
- can recommend learning candidates or validation tasks

Boundaries:

- does not rewrite product direction without Product / Feature Owner or founder approval
- does not promote canonical agent/skill changes without validation
- does not replace Review / QA for implementation acceptance

### Session Archivist

Owns:

- session notes
- run/session summaries
- files changed sections
- key decisions, insights, and action items
- continuity after meaningful conversations

Ticket powers:

- can update session records and request missing handoff details
- can recommend follow-up tickets for unresolved work

Boundaries:

- does not turn every minor chat into heavy documentation
- does not invent decisions that were not made
- preserves the owner's intent and avoids generic over-polish

### Project State Maintainer

Owns:

- progress files
- active work state
- workboard/project current-state entries when relevant
- roadmap/status alignment
- ops record cross-links

Ticket powers:

- can update project state when a ticket changes current focus, next actions, or status
- can flag stale or contradictory state as a blocker

Boundaries:

- does not modify unrelated project state
- does not close work without release/review evidence
- does not mix another project's ops state into The Factory

### Decision / ADR Archivist

Owns:

- decision records
- ADRs when architecture or durable tradeoffs are decided
- founder answers that affect product truth
- rationale, options, tradeoffs, and consequences

Ticket powers:

- can request a founder inbox item when a decision is missing
- can block release readiness when a required decision is undocumented

Boundaries:

- does not make founder-level decisions
- does not silently convert suggestions into decisions
- does not create ADR ceremony for tiny reversible changes

### Docs Reviewer

Owns:

- documentation review
- navigation and link quality
- consistency between docs and ops state
- checking whether docs match ticket intent
- detecting stale claims and missing outward links

Ticket powers:

- can pass, fail, or request revision on docs quality
- can recommend follow-up tickets for docs debt

Boundaries:

- does not replace product review or architecture review
- does not expand scope into broad cleanup unless assigned
- focuses on changed docs and necessary nearby navigation

### Learning Candidate Router

Owns:

- triaging learning candidates
- deciding local vs reusable vs canonical-candidate scope
- routing candidates toward validation, promotion, rejection, parking, or archive
- preventing every lesson from bloating canonical instructions

Ticket powers:

- can create or update learning candidates
- can recommend validation tasks
- can recommend rejection with reason

Boundaries:

- does not promote to canonical `04-agents/` or global rules without validation
- does not delete rejected learning without preserving rationale
- does not treat one-off project quirks as global rules

## Routing Rules

| Situation | Primary Role | Supporting Role |
|---|---|---|
| Meaningful session completed | Session Archivist | Knowledge / Documentation Lead |
| Current focus or next action changed | Project State Maintainer | Session Archivist |
| Ticket changes product/design truth | Project State Maintainer | Product / Feature Owner, Decision / ADR Archivist |
| Founder answer affects direction | Decision / ADR Archivist | Founder Interface, Product / Feature Owner |
| Architecture tradeoff is accepted | Decision / ADR Archivist | Advisory Architect |
| Docs changed materially | Docs Reviewer | Project State Maintainer |
| Links/navigation may be stale | Docs Reviewer | Project State Maintainer |
| Reusable friction appears | Learning Candidate Router | Knowledge / Documentation Lead |
| Candidate may affect agents/skills | Learning Candidate Router | Optimization Department later |
| Release readiness needs docs confirmation | Project State Maintainer | Docs Reviewer, Release Agent |

## Coordination With Optimization

Knowledge / Documentation captures the trail; Optimization changes the reusable system.

- Knowledge / Documentation owns session notes, progress/current-state files, decision records, docs navigation, and initial learning-candidate routing.
- Learning Candidate Router can mark a lesson as local, reusable, validation-needed, parked, rejected, or candidate for Optimization.
- Optimization owns validation, bounded edits, promotion/rejection decisions, and reusable learning-library curation.
- Canonical changes to role specs, department packs, prompts, skills, templates, or workflow rules require Optimization-style evidence and release gates.

If Knowledge / Documentation notices a repeated workflow issue, it should create or route a learning candidate rather than directly promoting a broad rule.

## Required Artifacts

Depending on the ticket, this department should produce or update:

- session note
- run summary
- progress/current-state update
- workboard update when active focus changes
- brain log entry for meaningful Factory events
- README/index/navigation update
- decision/ADR record when durable choices are made
- docs review record or review finding
- learning candidate
- learning routing decision
- validation evidence for docs and links

## Manual Workflow Participation

### Prepare

- check whether documentation/state/decision work is required
- identify required docs reviewers or decision archivists
- confirm current-state files that might need updating

### Execute

- update docs, state, session notes, decisions, or learning candidates inside assigned scope
- preserve project truth and avoid unrelated cleanup

### Self-Review

- verify links, references, changed files, and state consistency
- check that decisions are represented as decisions, not vague notes

### Fresh-Context Review

- Docs Reviewer checks whether documentation and state match ticket intent
- Project State Maintainer checks whether current-state files reflect the new reality

### Test

- run or request link checks, YAML/JSON parsing, Markdown/frontmatter checks, and `git diff --check` as appropriate

### Release Readiness

- confirm docs/state are complete enough for the Release Agent
- ensure pending founder inbox items, approvals, or ADRs are not ignored

### Reflect And Learn

- create or route learning candidates for repeated workflow/documentation problems
- preserve rejected-change rationale

## Stop Conditions

Stop and escalate when:

- a decision is required but not recorded
- a founder answer is needed
- docs would change product truth without Product / Feature Owner or founder approval
- links or references cannot be verified
- current state contradicts project progress or ops records
- reusable learning lacks evidence
- canonical agent/skill promotion is requested without validation
- the requested documentation update would touch unrelated projects

## Relationship To Other Departments

- Executive Orchestrator routes work into this department when documentation/state/learning is needed.
- Product / Feature Owner owns product intent; this department preserves and organizes it.
- Advisory Architect provides architecture/context advice; Decision / ADR Archivist records accepted decisions.
- Review / QA can request Docs Reviewer support for documentation-heavy tickets.
- Release Agent depends on this department for docs/state readiness.
- Optimization Department validates reusable learning before promotion and owns reusable agent/skill/template improvement gates.

## Not In V0

- automated documentation generation
- dashboard state automation
- scheduled documentation audits
- full ADR template system
- automatic promotion into `04-agents/`
- cross-project knowledge sync automation

## First Use

Use this department pack for the next Factory tickets that create prompt wrappers, custom agent files, project workspace templates, or update reusable role/skill docs.

This pack should also be the default documentation layer for future Factory-managed project workspaces.