# Factory Engineering Department Expansion Pack

Status: v0 department pack

This pack expands The Factory's Engineering department beyond the core Execution Agent role.

It defines how implementation, refactoring, integration, debugging, and handoff work move from context packs through scoped execution, self-review, fresh-context review, testing, release readiness, and learning capture without execution agents committing directly.

## Operating Contract

Use this pack with:

- [The Factory Manual Workflow](../../design/manual-workflow.md)
- [The Factory Operating Model](../../design/operating-model.md)
- [The Factory V0 Operating Objects](../../design/v0-operating-objects.md)
- [Factory Role Registry](../role-registry.md)
- [Factory V0 Core Department Pack](factory-v0-core-pack.md)
- [Factory Architecture / Context Architecture Department Pack](factory-architecture-context-pack.md)
- [Factory Knowledge / Documentation Department Pack](factory-knowledge-documentation-pack.md)
- [Factory Security / Privacy / Authority Department Pack](factory-security-privacy-authority-pack.md)
- [Factory Optimization Department Pack](factory-optimization-pack.md)

This pack is an operating contract, not a set of runnable custom agents.

## Purpose

The Engineering department turns execution-ready tickets into working artifacts while keeping scope, evidence, review, and release ownership clean.

It owns:

- scoped implementation
- refactoring inside assigned boundaries
- integration work
- debugging and diagnosis
- implementation evidence
- self-review before external review
- engineering handoff records
- follow-up ticket recommendations
- engineering learning candidates when repeatable patterns or failures appear

Engineering does not own product direction, final review acceptance, release readiness, or commits.

## Department Roles

| Role | Role Type | Advisory / Execution Status | Primary Responsibility |
|---|---|---|---|
| Engineering Lead | Department lead | Coordination and gatekeeping | Routes engineering work, protects implementation scope, and decides specialist engineering assignment |
| Implementation Agent | Execution specialist | Execution role | Implements scoped features, docs, scripts, or artifacts from the assigned ticket and context pack |
| Refactor Agent | Refactoring specialist | Execution only when assigned | Improves structure inside explicit scope without changing product behavior unless approved |
| Integration Agent | Integration specialist | Execution only when assigned | Connects modules, tools, services, data flows, or project components inside approved boundaries |
| Debugging Agent | Diagnosis and fix specialist | Investigation and execution when assigned | Reproduces, diagnoses, isolates, fixes, or routes defects with evidence |
| Engineering Handoff Agent | Handoff specialist | Coordination and light execution | Produces handoff summaries, evidence bundles, follow-up tickets, and review-ready state |

## Activation Triggers

Activate this department when a ticket involves:

- scoped implementation work
- code, script, template, prompt wrapper, CLI, dashboard, automation, or project artifact creation
- refactoring or cleanup with explicit scope
- integration between files, modules, tools, services, agents, prompts, data, or ops objects
- debugging a failed check, broken behavior, unclear error, or regression
- applying architecture constraints in code or docs
- translating a context pack into concrete changes
- creating implementation evidence for review and release
- engineering handoff after partial or completed work
- follow-up tickets caused by technical blockers or discovered work

Do not activate this department for pure product shaping, marketing copy, knowledge capture, security review, or release-only work unless engineering execution is also needed.

## Inputs

The department may need:

- assigned ticket
- parent task and work hierarchy context
- context pack
- acceptance criteria
- scope and out-of-scope
- architecture/context constraints
- security/privacy/authority constraints
- required reviewers and approval level
- relevant files, docs, tests, scripts, templates, or project objects
- prior runs, review findings, failed checks, or bug reports
- expected output and handoff format
- release checklist requirements when known

## Outputs

The department produces or updates:

- implementation or artifact
- changed files list
- run record update
- commands/checks and test evidence
- self-review record
- handoff summary
- blocker notes
- follow-up ticket recommendations
- specialist review requests
- debugging diagnosis or reproduction notes
- integration notes
- learning candidates for reusable engineering patterns or failures

## Role Details

### Engineering Lead

Owns:

- engineering routing
- assigning Implementation, Refactor, Integration, Debugging, or Handoff roles
- checking engineering readiness before execution starts
- coordinating with Product, Architecture / Context, Security / Privacy / Authority, Review / QA, Release, Knowledge / Documentation, and Optimization
- protecting implementation boundaries

Ticket powers:

- can assign engineering roles to ready tickets
- can block engineering execution when context, scope, approvals, or architecture constraints are missing
- can request specialist review or follow-up tickets
- can recommend revision when implementation exceeds scope

Boundaries:

- does not make product or founder decisions
- does not bypass architecture, security/privacy/authority, review, test, or release gates
- does not commit directly
- does not treat useful discovered work as in-scope without ticket update

### Implementation Agent

Owns:

- scoped implementation from the assigned ticket and context pack
- local reasoning inside the ticket boundary
- changed-file evidence
- command/check output summaries
- self-review before handoff

Ticket powers:

- can edit files inside assigned scope
- can create or recommend follow-up tickets
- can update run evidence and self-review records
- can stop and request clarification when context is missing

Boundaries:

- does not commit directly
- does not expand scope silently
- does not change architecture or product truth without approval
- does not use external APIs, paid services, credentials, MCPs, or privileged automation without required approval

### Refactor Agent

Owns:

- structure-preserving refactors
- duplication reduction inside explicit scope
- local readability and maintainability improvements
- mechanical migration steps when assigned
- before/after behavior evidence

Ticket powers:

- can edit scoped files for refactoring
- can request broader architecture review when refactor pressure suggests a larger design issue
- can recommend follow-up tickets for out-of-scope cleanup

Boundaries:

- does not change behavior unless the ticket explicitly allows it
- does not perform drive-by cleanup
- does not rewrite unrelated modules
- does not commit directly

### Integration Agent

Owns:

- connecting components across approved boundaries
- interface and contract alignment
- integration points and data/control flow wiring
- verifying handoff between modules, tools, prompts, agents, or ops objects
- integration test or manual verification evidence when applicable

Ticket powers:

- can implement approved integrations
- can request Architecture / Context review for boundary, data-flow, or contract concerns
- can request Security / Privacy / Authority review for external, credential, permission, or data concerns

Boundaries:

- does not introduce new external services or privileged tools without approval
- does not redefine architecture alone
- does not ignore failed integration checks
- does not commit directly

### Debugging Agent

Owns:

- reproducing failures
- isolating causes
- separating symptoms from root cause
- proposing or applying scoped fixes
- recording failed and passing checks
- routing out-of-scope defects

Ticket powers:

- can run appropriate diagnostics and tests
- can apply fixes inside assigned scope
- can request follow-up tickets for unrelated or broader defects
- can request specialist review when a bug crosses security, privacy, architecture, data, or product boundaries

Boundaries:

- does not mask failures without explanation
- does not fix unrelated bugs unless assigned
- does not claim root cause without evidence
- does not commit directly

### Engineering Handoff Agent

Owns:

- final engineering handoff summary
- changed-file inventory
- run and test evidence completeness
- blocker and follow-up ticket recommendations
- review-ready context for Review / QA and specialist reviewers
- ensuring execution agents do not leave opaque work behind

Ticket powers:

- can request missing evidence from implementation roles
- can recommend follow-up tickets
- can block handoff when changed files, tests, or scope notes are incomplete

Boundaries:

- does not approve its own implementation as accepted
- does not replace Review / QA or Release
- does not commit directly

## Context Pack Execution Protocol

Engineering execution agents work from context packs, not from memory or vibes.

### 1. Confirm Assignment

Before editing, the assigned engineering role checks:

- ticket belongs to exactly one task
- context pack exists and matches the ticket
- objective and acceptance criteria are clear
- scope and out-of-scope are explicit
- architecture/context constraints are included or not needed
- security/privacy/authority constraints are included or not needed
- approval level and required reviewers are known

Stop if any required field is missing or stale.

### 2. Execute Inside Scope

During execution:

- edit only files required by the ticket
- avoid unrelated refactors or cleanup
- preserve existing project style and patterns
- create or recommend follow-up tickets for discovered work
- update run evidence with changed files, checks, failures, blockers, and output summary

### 3. Verify Locally

Run or record checks appropriate to the ticket:

- tests
- type checks
- lint/build checks
- JSON/YAML/frontmatter parsing
- link checks
- manual QA
- targeted reproduction or regression checks

If verification fails, record the failure and move the ticket toward `revision` or `blocked` instead of pretending the work is done.

### 4. Self-Review

The executing role creates or updates a self-review record before handoff.

Self-review must check:

- acceptance criteria
- scope match
- changed files
- tests/checks
- required docs/state updates
- unresolved blockers
- needed specialist reviews

### 5. Handoff

Engineering Handoff Agent or the executing role gives Review / QA:

- ticket ID and task ID
- context pack ID
- implementation summary
- changed files
- test/check evidence
- known risks or follow-ups
- required specialist reviewer notes

### 6. No Direct Commit

Engineering execution agents do not commit directly.

Release Agent owns commit/PR readiness after self-review, fresh-context review, required specialist reviews, testing evidence, docs/state updates, and approvals are complete.

## Routing Rules

| Situation | Primary Role | Supporting Role |
|---|---|---|
| Scoped implementation is ready | Implementation Agent | Engineering Lead |
| Refactor is explicitly requested | Refactor Agent | Architecture / Context when design pressure appears |
| Multiple components must connect | Integration Agent | Architecture / Context, Security / Privacy / Authority when relevant |
| Failure needs reproduction and diagnosis | Debugging Agent | Review / QA, Implementation Agent |
| Context pack is stale or incomplete | Engineering Lead | Architecture / Context, Product |
| Acceptance criteria are unclear | Product Department | Engineering Lead |
| Security/privacy/authority risk appears | Security / Privacy / Authority Department | Engineering Lead |
| Architecture boundary or tradeoff appears | Architecture / Context Department | Engineering Lead |
| Work is ready for external review | Engineering Handoff Agent | Review / QA |
| Release readiness is needed | Release Agent | Engineering Handoff Agent, Review / QA |
| Reusable engineering lesson appears | Optimization Department | Knowledge / Documentation |

## Required Artifacts

Depending on the ticket, this department should produce or update:

- run record
- changed-file list
- implementation summary
- command/test evidence
- self-review record
- debugging diagnosis or reproduction notes
- integration notes
- handoff summary
- follow-up ticket recommendations
- specialist review requests
- learning candidate when engineering friction is reusable

## Manual Workflow Participation

### Prepare

- confirm ticket, task, context pack, scope, acceptance criteria, reviewers, approvals, and blockers
- route to the correct engineering specialist

### Execute

- perform only assigned engineering work
- record evidence while working
- stop when scope, approval, or safety boundaries are crossed

### Self-Review

- compare work to ticket intent and acceptance criteria
- record tests/checks and unresolved risks
- move incomplete work to `revision` or `blocked`

### Fresh-Context Review

- Review / QA and required specialist reviewers compare output against intent, criteria, architecture, and risk constraints

### Test

- run or record appropriate verification and preserve evidence in run, ticket, and release records

### Release Readiness

- Release Agent, not Engineering, decides commit/PR readiness and commit scope

### Reflect And Learn

- capture repeated implementation failures, context-pack gaps, weak tests, integration friction, or refactor patterns as learning candidates

## Stop Conditions

Stop and escalate when:

- context pack is missing or stale
- ticket objective, scope, or acceptance criteria are unclear
- ticket does not belong to exactly one task
- implementation requires product, founder, architecture, security, privacy, authority, external-service, paid-service, or credential approval
- work would require unrelated cleanup or broad refactor
- tests/checks fail and the fix is outside scope
- changed files include unrelated work
- an integration changes data/control flow beyond the approved design
- debugging reveals a root cause outside the assigned ticket
- release scope or handoff evidence is unclear

## Boundaries

- Engineering implements assigned work; Product defines intent.
- Engineering follows architecture/context constraints; Architecture / Context owns system-shape decisions.
- Engineering records evidence; Review / QA accepts or rejects fresh-context review.
- Engineering can recommend release, but Release Agent owns commit/PR readiness and commits.
- Engineering can request Security / Privacy / Authority review, but cannot approve risk alone.
- Engineering can recommend learning candidates, but Optimization owns validation and promotion.
- Engineering can update docs/state inside assigned scope, but Knowledge / Documentation owns durable documentation quality and continuity.

## Not In V0

- runnable engineering custom agents
- automatic commit or PR creation by execution agents
- autonomous parallel build system
- CI/CD implementation
- build farm or cloud runner
- production deployment automation
- dependency management policy beyond ticket-level checks

## First Use

Use this pack for implementation tickets, prompt-wrapper work, CLI/helper implementation, dashboard prototypes, integrations, bug fixes, and refactors once the relevant product, architecture, context, and approval gates are clear.
