# Factory Release / CI-CD Department Expansion Pack

Status: v0 department pack

This pack expands The Factory's Release / CI-CD department beyond the core Release Agent role.

It defines how validated work becomes a focused commit, PR, merge, release, or intentionally rejected/revision-requested change while protecting branch rules, commit scope, review/test gates, approvals, documentation, and repository hygiene.

## Operating Contract

Use this pack with:

- [The Factory Manual Workflow](../../03-projects/ai-development-team/design/manual-workflow.md)
- [The Factory Operating Model](../../03-projects/ai-development-team/design/operating-model.md)
- [Release Checklist Template](../../03-projects/ai-development-team/templates/ops/release-checklist.md)
- [Factory Role Registry](../role-registry.md)
- [Factory V0 Core Department Pack](factory-v0-core-pack.md)
- [Factory Review / QA Department Expansion Pack](factory-review-qa-expansion-pack.md)
- [Factory Security / Privacy / Authority Department Pack](factory-security-privacy-authority-pack.md)
- [Factory Knowledge / Documentation Department Pack](factory-knowledge-documentation-pack.md)
- [Factory Optimization Department Pack](factory-optimization-pack.md)
- [Factory Ops](../../03-projects/ai-development-team/ops/README.md)

This pack is an operating contract, not a set of runnable custom agents or CI/CD automation.

## Purpose

The Release / CI-CD department protects the final transition from validated work to repository/project state.

It owns:

- release readiness
- release checklist quality
- branch and target validation
- commit scope review
- commit message and PR readiness
- PR creation/management rules when relevant
- CI/CD check monitoring when automation exists
- release notes coordination
- batching decisions
- escalation when release is unsafe
- post-release follow-up recording

The department is the last human/agent gate before a commit, PR, merge, or ship action. It does not implement ticket work or replace Review / QA.

## Department Roles

| Role | Role Type | Advisory / Execution Status | Primary Responsibility |
|---|---|---|---|
| Release Lead | Department lead | Coordination and gatekeeping | Owns release routing, release policy, and final release-readiness path |
| Commit Readiness Reviewer | Commit gate reviewer | Review/gate role | Checks changed files, staged scope, commit message, branch, and release checklist readiness |
| PR Manager | PR coordinator | Coordination and light execution | Prepares PR scope, summary, reviewers, labels, and merge-readiness handoff when PRs are used |
| CI/CD Monitor | Automation/check monitor | Monitoring and gate role | Watches build/test/check status and records pass/fail/blocker evidence |
| Release Notes Coordinator | Documentation/release specialist | Light execution | Prepares release notes, changelog snippets, migration notes, rollback notes, and post-release follow-ups |
| Release Gatekeeper | Final gatekeeper | Gatekeeping role | Approves ready/rejected/revision/escalation decision based on all review, test, approval, and repository evidence |

## Relationship To Core Registry

The core [Release Agent](../roles/release-agent.md) remains the v0 default for release readiness, commit/PR scope, and final repository gatekeeping.

Use this expansion pack when release work needs decomposition:

- Release Lead routes release path and branch/commit/PR policy.
- Commit Readiness Reviewer checks changed/staged file scope, branch, commit message, and repository hygiene.
- PR Manager, CI/CD Monitor, Release Notes Coordinator, and Release Gatekeeper activate only when their surfaces are needed.

Release consumes Review / QA, specialist review, test, approval, and documentation evidence. It cannot create release readiness by bypassing those gates.

## Activation Triggers

Activate this department when a ticket, task, or batch is moving toward:

- commit
- PR creation
- merge
- release checklist creation or update
- task-level batching decision
- release notes or changelog update
- CI/check monitoring
- branch target selection
- repository-state cleanup before commit
- post-release follow-up recording
- rejection or revision request due to missing evidence
- escalation because approvals, review, tests, docs, or branch safety are unresolved

Do not activate this department to implement the original ticket or to bypass review/testing. Release starts after execution self-review and fresh-context review are available, or when it is intentionally rejecting missing gates.

## Inputs

The department may need:

- task and ticket records
- run record
- self-review record
- fresh-context review record
- required specialist review records
- test/check evidence
- approval and founder inbox state
- release checklist draft
- changed files and staged files
- branch name and intended target branch
- commit message proposal
- PR description, reviewers, labels, or merge target when relevant
- docs/state update evidence
- migration, rollback, and release note needs
- known blockers, follow-ups, and learning candidates

## Outputs

The department produces or updates:

- release checklist
- release readiness decision
- commit message recommendation
- staged-file scope decision
- PR summary or PR readiness plan
- CI/CD status summary
- release notes
- migration or rollback notes
- post-release follow-up tickets
- release blocker or escalation record
- learning candidates for repeated release friction

## Role Details

### Release Lead

Owns:

- department routing
- deciding whether commit, PR, merge, release, rejection, revision, or escalation is the right path
- assigning Commit Readiness Reviewer, PR Manager, CI/CD Monitor, Release Notes Coordinator, or Release Gatekeeper
- coordinating with Review / QA, Security / Privacy / Authority, Knowledge / Documentation, Engineering, Product, and Founder Interface
- ensuring release work follows project branch rules

Ticket powers:

- can require release checklist completion
- can block release readiness
- can request revision or specialist review
- can decide ticket-level versus task-level release routing
- can require founder escalation for branch, external service, deployment, paid service, credential, or high-risk release decisions

Boundaries:

- does not implement ticket work
- does not replace Review / QA or specialist reviewers
- does not bypass missing approvals
- does not commit unrelated work

### Commit Readiness Reviewer

Owns:

- changed-file and staged-file scope review
- commit message quality
- branch/target confirmation
- checking that release checklist fields are complete
- checking that unrelated dirty work is not committed
- verifying repository state before commit

Ticket powers:

- can reject commit readiness
- can require staged-file correction
- can request release checklist revision
- can require docs/state or review evidence before commit

Boundaries:

- does not implement fixes
- does not accept broad staged sets without explanation
- does not commit when branch target is unclear

### PR Manager

Owns:

- PR scope and target branch
- PR title and summary
- changed-file summary
- reviewer list
- labels or metadata when relevant
- merge-readiness handoff
- post-PR follow-up notes

Ticket powers:

- can prepare PR descriptions and reviewer recommendations
- can block PR readiness when scope, target, or evidence is unclear
- can request release notes or migration details

Boundaries:

- does not merge without release gatekeeper approval
- does not change branch strategy without approval
- does not hide unresolved blockers in PR text

### CI/CD Monitor

Owns:

- monitoring automated checks when they exist
- recording build, test, lint, type, deploy, or workflow check state
- distinguishing failed, pending, skipped, absent, and not-applicable checks
- routing failures back to Engineering, Review / QA, Security / Privacy / Authority, or Release Lead

Ticket powers:

- can block release readiness on failing or missing required checks
- can request rerun only when the failure reason is known and rerun is safe
- can recommend follow-up tickets for flaky or missing checks

Boundaries:

- does not treat absent CI as passing CI
- does not approve deployment risk alone
- does not fix failing checks unless separately assigned an execution ticket

### Release Notes Coordinator

Owns:

- release notes
- changelog snippets
- migration notes
- rollback notes
- user-facing or internal summary when needed
- post-release follow-up list
- docs handoff to Knowledge / Documentation

Ticket powers:

- can require release notes for user-facing, project-truth, migration, or risk-relevant changes
- can request Marketing support for public-facing release copy
- can request Knowledge / Documentation support for durable project docs

Boundaries:

- does not invent product claims
- does not replace Marketing for launch copy
- does not rewrite project truth without Product/Founder approval

### Release Gatekeeper

Owns:

- final release decision
- ready, rejected, revision_requested, escalated, or parked decision
- checking all required gates are satisfied
- ensuring branch/commit/PR rules are followed
- protecting repository and project truth from unsafe release actions

Ticket powers:

- can approve commit/PR readiness when project rules allow
- can reject release readiness
- can request revision
- can require founder or specialist escalation
- can block release when repository state is dirty with unrelated changes

Boundaries:

- does not bypass missing fresh-context review, required tests, specialist review, approvals, or docs/state updates
- does not commit if changed files exceed release scope
- does not make founder-level product, architecture, security, privacy, authority, paid-service, or credential decisions

## Branch, Commit, And PR Rules

### Branch Rules

- Confirm current branch before release action.
- Confirm intended target branch or PR base.
- Follow project-specific branch rules before staging or committing.
- Do not commit [project]-specific work on `main`; [project] project truth belongs on `project/[project]` after bringing in the latest shared `main` state.
- Do not create or switch branches unless the ticket or project workflow calls for it.
- Stop if branch state, upstream state, or merge/rebase state is unclear.

### Commit Rules

- Execution agents do not commit directly.
- Commit only after self-review, fresh-context review, required specialist reviews, test evidence, docs/state updates, and approvals are complete or explicitly not needed.
- Stage only files inside the release scope.
- Use guarded staged-file checks for mixed or dirty worktrees.
- Do not include unrelated dirty or untracked files.
- Commit messages should be short, action-oriented, and match the release scope.
- If the staged set differs from the release checklist, stop and correct the scope.

### Scope Change Re-Review Rule

If Release changes staged files, batching, release scope, target branch, or commit/PR contents after Review / QA signoff, release readiness is no longer final.

Before commit or PR readiness, route the changed scope back to Review / QA and any triggered specialist reviewers. The release checklist should record whether the re-review passed, failed, or was explicitly not needed because the scope change was only a mechanical staging correction with no artifact/content difference.

### PR Rules

- Use PRs when project workflow, risk level, branch policy, external review, or collaboration requires them.
- PR summary must state scope, evidence, review status, test status, risks, and follow-ups.
- PR reviewers should map to required reviewers and specialist risk.
- Do not mark a PR merge-ready while required checks, approvals, docs, or founder decisions are pending.
- PR Manager coordinates PR readiness; Release Gatekeeper decides whether merge/release is allowed.

## Batching Rules

Batching is allowed when multiple tickets form one coherent task-level unit.

Batch when:

- tickets share the same task and release intent
- changed files form one coherent reviewable unit
- each ticket has required reviews and evidence
- release notes and docs/state updates can be summarized clearly
- batching reduces noise without hiding risk

Do not batch when:

- tickets belong to different tasks or projects
- unrelated files or user changes would be included
- one ticket has unresolved review, test, approval, or founder blockers
- risk profiles differ enough to need separate gates
- a rollback would need to undo unrelated work

Record batching rationale in the release checklist.

## Escalation Paths

Escalate when release cannot safely proceed.

| Situation | Escalate To | Release Action |
|---|---|---|
| Missing or failed fresh-context review | Review / QA Lead | `revision_requested` or `rejected` |
| Missing or failed tests/checks | Review / QA Lead, Engineering Lead | `revision_requested` |
| Security/privacy/authority risk | Security / Privacy / Authority Department | `blocked` or `escalated` |
| Product direction or project-truth change | Product Lead, Founder Interface | `blocked` until decision |
| Architecture/context tradeoff | Architecture / Context Department | `blocked` until review/decision |
| Missing docs/state/session update | Knowledge / Documentation Lead | `revision_requested` |
| Dirty repo with unrelated work | Commit Readiness Reviewer | stop staging/commit |
| Branch or PR target unclear | Release Lead | stop and clarify |
| External service, paid service, credential, deployment, or destructive action | Security / Privacy / Authority, Founder Interface | Level 2/3 escalation |
| Repeated release friction | Optimization Department | learning candidate |

## Routing Rules

| Situation | Primary Role | Supporting Role |
|---|---|---|
| Release checklist is needed | Release Lead | Commit Readiness Reviewer |
| Commit scope needs review | Commit Readiness Reviewer | Release Gatekeeper |
| PR is needed | PR Manager | Release Lead |
| CI/checks exist or are required | CI/CD Monitor | Review / QA, Engineering |
| Release notes are needed | Release Notes Coordinator | Knowledge / Documentation, Marketing when public-facing |
| Approval or risk is unresolved | Release Gatekeeper | Security / Privacy / Authority, Founder Interface |
| Batching decision is needed | Release Lead | Executive Orchestrator, Commit Readiness Reviewer |
| Docs/state update is missing | Knowledge / Documentation Department | Release Notes Coordinator |
| Review/test evidence is missing | Review / QA Department | Release Gatekeeper |
| Reusable release lesson appears | Optimization Department | Knowledge / Documentation |

## Required Artifacts

Depending on the ticket, this department should produce or update:

- release checklist
- branch/target decision
- staged-file or changed-file scope review
- commit message recommendation
- PR summary and reviewer list when relevant
- CI/check status summary when relevant
- release notes or changelog snippet
- migration notes when relevant
- rollback notes when relevant
- post-release follow-ups
- blocker or escalation record
- learning candidate for repeated release friction

## Manual Workflow Participation

### Prepare

- verify release scope, branch, target, ticket/task relation, reviews, tests, approvals, docs/state, and changed files
- stop if release scope or repository state is unclear

### Execute

- create or update release checklist, commit/PR readiness notes, release notes, and staged-file decisions
- do not implement ticket work while acting as release

### Self-Review

- check release checklist completeness and scope match
- verify commit/PR readiness evidence

### Fresh-Context Review

- confirm Review / QA and required specialist reviews are complete or explicitly not needed

### Test

- verify test evidence, CI/check status, or recorded reason why checks are not applicable

### Release Readiness

- decide ready, rejected, revision_requested, escalated, or parked
- commit or prepare PR only when project rules allow and all gates pass

### Reflect And Learn

- capture repeated release friction, branch confusion, staged-file mistakes, missing release notes, or CI gaps as learning candidates

## Stop Conditions

Stop, reject, request revision, or escalate when:

- release checklist is missing or incomplete
- self-review is missing for non-trivial work
- fresh-context review failed or is missing
- required specialist review is missing
- tests/checks are missing, failing, or insufficient for risk level
- docs/state updates are incomplete
- founder inbox item or approval is pending
- branch, PR target, or release scope is unclear
- changed files or staged files include unrelated work
- repo state is dirty in a way that could pollute the commit
- external service, paid service, credential, deployment, destructive action, or high-risk automation appears without approval
- rollback or migration risk is unclear for a risky change

## Boundaries

- Release owns commit/PR readiness, not original implementation.
- Release depends on Review / QA for review/test evidence.
- Release depends on Security / Privacy / Authority for risk review and approval-level decisions.
- Release depends on Knowledge / Documentation for durable docs/state continuity.
- Release can block or escalate, but it does not make founder-level decisions.
- Release can commit only when project rules allow, all gates pass, and staged scope is clean.
- Release scope changes after review require re-review unless they are purely mechanical staging corrections that do not change reviewed content.

## Not In V0

- full CI/CD implementation
- deployment automation
- release dashboard UI
- package publishing automation
- environment promotion system
- automatic branch creation
- automatic PR creation by execution agents
- rollback automation

## First Use

Use this pack whenever Factory work moves from validated output toward commit, PR, merge, release notes, or task-level batching.