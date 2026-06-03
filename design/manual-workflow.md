# The Factory Manual Workflow

Status: v0 operating procedure

This is the canonical manual operating procedure for using The Factory before CLI helpers, dashboard automation, or deeper editor integration exists.

The goal is simple: make every Factory-managed ticket leave enough structured evidence that another agent, the owner, or a future dashboard can understand what happened, what passed, what is blocked, what shipped, and what should improve.

## When To Use

Use this workflow for any Factory-managed ticket while automation is not yet available.

Use it especially when:

- a ticket changes Factory docs, templates, ops state, agents, skills, or project truth
- a ticket needs review or release readiness
- an execution agent hands off work to another role
- a founder decision, approval, or blocker appears
- a repeated friction point should become a learning candidate

Do not use this as a heavyweight ritual for tiny typo fixes unless the fix is attached to an active Factory ticket.

## Inputs

Before execution starts, the assigned agent should have:

- task record
- ticket record
- context pack
- assigned agent or role
- required reviewers
- approval level
- known blockers and dependencies
- relevant product/design/docs files
- expected handoff format

The minimum useful set is one task, one ticket, one context pack, and one run record.

## Step 1: Prepare

The orchestrator, feature owner, or assigned agent checks whether the ticket is actually ready to run.

Check:

- ticket status is `ready`, `assigned`, `in_progress`, or otherwise intentionally being worked
- ticket belongs to exactly one task
- owner role and assigned agent are clear
- objective and acceptance criteria are specific
- scope and out-of-scope are explicit
- context pack exists and is not stale
- required reviewers are listed
- approval level is known
- blockers, inbox items, dependencies, and pending approvals are empty or understood

Update before execution:

- set ticket status to `assigned` or `in_progress`
- create or update the run record
- update context pack status to `assigned` if this is the first active use

Stop if the ticket is ambiguous, blocked, missing context, or needs founder approval.

## Step 2: Execute

The assigned execution agent performs only the scoped work.

During execution:

- keep work inside the ticket scope
- avoid unrelated refactors or cleanup
- create founder inbox items if a founder decision is needed
- create follow-up tickets for discovered work that should not be done now
- record changed files, commands/checks, outputs, and blockers in the run record

After execution:

- set run status to `completed`, `failed`, `waiting`, or `cancelled`
- summarize output in the run record
- update ticket status to `self_review` if execution completed
- leave failed or partial work in `revision` or `blocked` with a clear reason

Execution agents do not commit directly.

## Step 3: Self-Review

The execution agent reviews its own work before handoff.

Create a review record with:

- `review_type: self_review`
- reviewed ticket and task IDs
- context pack ID
- acceptance criteria checked
- implementation summary
- findings and risks
- required revisions if any
- decision: `passed`, `changes_requested`, or `failed`

Self-review checks:

- result matches the original ticket intent
- acceptance criteria are addressed
- scope did not drift
- files and state changes are accounted for
- tests/checks are recorded or explicitly not needed
- docs/state updates are complete enough for external review

If self-review fails, move the ticket to `revision` or `blocked` and do not request fresh-context review yet.

## Step 4: Fresh-Context Review

A reviewer who is not the execution agent compares the result against the original intent and acceptance criteria.

Create a separate review record with:

- `review_type: fresh_context`
- reviewer role
- specialist area when relevant
- original intent
- acceptance criteria checked
- implementation summary
- findings
- decision
- required revisions or follow-up tickets

Fresh-context review checks:

- the work solves the assigned ticket, not a different problem
- the implementation or artifact is complete enough for the risk level
- required specialist reviewers were used or explicitly not needed
- documentation and ops state are coherent
- validation/testing evidence is sufficient

If review fails, move the ticket to `revision` and route it back to execution with concrete findings.

## Step 5: Test

Run or record the appropriate verification for the ticket type.

For code tickets, testing may include:

- unit tests
- integration tests
- type checks
- linting
- build checks
- manual QA
- browser or UI checks when relevant

For docs or ops-state tickets, testing may include:

- JSON parsing
- YAML parsing
- Markdown/frontmatter parsing
- link health checks
- `git diff --check`
- targeted review of changed state objects

Record testing evidence in:

- run record
- ticket `test_evidence`
- release checklist
- review record when tests affect the review decision

If verification fails, move the ticket to `revision` or `blocked` and record the failing command, failure summary, and next action.

## Step 6: Release Readiness

The release agent checks whether the work is ready for commit, PR, merge, or task-level batching.

Create a release checklist with:

- release scope: ticket or task
- related task and ticket IDs
- review IDs
- approval IDs if any
- test evidence
- docs updated status
- scope match
- release decision
- changed files
- post-release follow-ups

Release readiness checks:

- ticket scope matches the result
- self-review passed
- fresh-context review passed
- required specialist reviews passed or were not needed
- tests/checks are sufficient for risk level
- docs and ops state are updated
- no founder inbox item or approval is pending
- changed files are accounted for
- commit or PR scope is coherent

If release readiness fails, the release agent rejects, requests revision, or escalates.

If multiple tickets form one coherent task-level unit, the release agent may batch them into one task-level commit.

## Step 7: Reflect And Learn

Create a learning candidate when the work reveals something awkward, missing, repeated, risky, or reusable.

Learning candidates are useful for:

- unclear ticket fields
- missing workflow steps
- repeated review findings
- weak templates
- better agent instructions
- better context-pack structure
- release or approval confusion
- reusable project patterns
- rejected changes that should not be proposed again

Learning candidate scope should be one of:

- project-specific: keep local unless it repeats
- reusable: candidate for Factory docs, templates, agents, or skills
- canonical: should be validated before promotion to `04-agents/` or global rules

Do not auto-promote learning into canonical agents or skills. Capture first, validate later.

## Step 8: Update Project State

Before final handoff, update the relevant state and narrative records.

Update operational state:

- ticket status
- task status when child tickets change the task state
- run status and output summary
- review record statuses
- release checklist status
- approval or inbox status when applicable
- learning candidate status when captured or promoted

Update project docs when the work changes durable truth:

- progress file
- design docs
- roadmap
- templates
- README/index files
- decision notes

Update brain continuity when the session changes active focus, next actions, or durable learning:

- workboard
- brain log
- session note

## Required Artifacts

Every manually operated Factory ticket should usually produce or update:

| Artifact | Required When | Purpose |
|---|---|---|
| Run record | Always | Shows who worked, on what context, with what result |
| Self-review | Execution completed | Execution agent checks its own result before handoff |
| Fresh-context review | Work needs acceptance | Independent check against intent and acceptance criteria |
| Test evidence | Work claims correctness or coherence | Shows what was verified |
| Release checklist | Work is ready to commit, PR, ship, or batch | Release agent gate |
| Learning candidate | Workflow friction or reusable learning appears | Captures improvement without bloating canonical rules |
| Session note | Meaningful Factory work happened | Preserves continuity and files changed |

Founder inbox items and approvals are required only when the ticket needs them.

## Stop Conditions

Stop or block the ticket when:

- context pack is missing or stale
- objective or acceptance criteria are unclear
- ticket has unresolved blockers or dependencies
- founder decision is needed
- approval is missing
- execution result drifts outside ticket scope
- self-review fails
- fresh-context review fails
- required specialist review is missing
- verification fails
- release scope is unclear
- changed files include unrelated work
- external API, paid service, credential, MCP, security, privacy, or architecture risk appears without approval

When stopped, update the ticket to `blocked` or `revision`, create the necessary inbox item, approval, follow-up ticket, or review finding, and record the next action.

## Status Guidance

Suggested ticket movement:

```text
ready -> assigned -> in_progress -> self_review -> external_review -> testing -> release_ready -> shipped -> archived
blocked
revision
```

Practical notes:

- `self_review` means execution is complete enough for the execution agent to inspect its own output.
- `external_review` means a fresh-context reviewer is checking the result.
- `testing` can overlap review in practice, but evidence should be recorded before release readiness.
- `release_ready` means release agent checks have passed or are being finalized.
- `shipped` means the release action is complete according to project rules.
- `archived` means operational state is closed and durable learning is preserved.

## Example: Internal Factory Ops Dogfood

The first manual dogfood pass used the seeded internal Factory ops ticket.

Core objects:

- [Internal Factory Ops Ticket](../ops/tickets/TICKET-2026-0001-internal-factory-ops.yaml)
- [Factory Self-Hosting Task](../ops/tasks/TASK-2026-0001-factory-self-hosting.yaml)
- [Internal Factory Ops Context Pack](../ops/context-packs/CP-2026-0001-internal-factory-ops.md)
- [Internal Factory Ops Run](../ops/runs/RUN-2026-0001-internal-factory-ops.json)

Review and release objects:

- [Self-Review](../ops/reviews/REVIEW-2026-0001-internal-factory-ops-self-review.yaml)
- [Fresh-Context Review](../ops/reviews/REVIEW-2026-0002-internal-factory-ops-fresh-review.yaml)
- [Release Checklist](../ops/releases/RELEASE-2026-0001-internal-factory-ops.md)
- [Learning Candidate](../ops/learning/LEARN-2026-0001-manual-workflow-gate.yaml)

Continuity records:

- [Factory Self-Hosting Ops Session](../../../session-logs/2026-06-03-factory-self-hosting-ops.md)
- [Factory Manual Dogfood Workflow Session](../../../session-logs/2026-06-03-factory-manual-dogfood-workflow.md)

What it proved:

- the v0 operating objects are enough to run a ticket manually
- self-review and fresh-context review should be explicit records
- release readiness should be a release checklist, not a loose note
- learning candidates are the right place to capture workflow gaps before changing templates or agents

## Next Use

Use this manual workflow as the shared operating contract for the first reusable Factory agent and department specs in `04-agents/`.

Those specs should assume that agents operate through tasks, tickets, context packs, run records, reviews, release checklists, and learning candidates until automation exists.