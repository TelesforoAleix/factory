# The Factory Operating Model

## Company Model

The Factory should behave like a small software company with departments, managers, execution workers, reviewers, release ownership, and founder escalation.

Agents are functional roles, not personalities.

## Work Hierarchy

```text
Project -> Goal -> Feature -> Task -> Ticket
```

Tickets are the smallest assignable unit.

## Default Lifecycle

Initial lifecycle:

```text
inbox -> discovery -> ready -> assigned -> in_progress -> review -> revision -> release_ready -> shipped -> archived
blocked
```

Meaning:

- inbox: captured but not yet shaped.
- discovery: product/manager agents are asking questions and defining intent.
- ready: ticket has enough context and acceptance criteria.
- assigned: owner selected.
- in_progress: execution started.
- review: fresh-context review in progress.
- revision: execution needs changes.
- release_ready: release agent can evaluate commit/PR readiness.
- shipped: committed/merged/released according to project rules.
- archived: operational state closed, durable learning preserved.
- blocked: needs external decision, missing information, or dependency.

## Core Role Layers

### Founder Interface

Primary responsibility: communicate with the owner.

Owns:

- founder inbox
- status summaries
- decision interviews
- open questions
- important escalations

### Executive Orchestrator

Primary responsibility: route work across departments.

Owns:

- project-level coordination
- department routing
- dependency management
- parallel work coordination
- final synthesis for the owner

### Product / Feature Owner

Primary responsibility: define what should be built.

Owns:

- discovery
- requirements
- PRDs
- roadmap slices
- goals/features/tasks/tickets
- acceptance criteria
- product drift detection

### Architect / Context Architect

Primary responsibility: define system shape and context strategy.

Owns:

- system boundaries
- data flow
- architecture decisions
- context packs
- retrieval/memory/context decisions when relevant
- technical tradeoffs

### Execution Agent

Primary responsibility: complete scoped tickets.

Owns:

- implementation
- local reasoning about assigned ticket
- clear result reports
- creating help tickets when blocked

Does not own:

- global project direction
- final release
- committing directly

### Review / QA Agent

Primary responsibility: validate result against intent.

Owns:

- fresh-context review
- acceptance criteria checks
- regression/test checks
- revision feedback
- specialist review routing

### Specialist Reviewer

Primary responsibility: review work in a narrow domain when relevant.

Possible specialties:

- security
- privacy/GDPR
- authority/permissions
- UX/UI
- data
- architecture
- context/memory
- performance

### Release Agent

Primary responsibility: final code/repository transition.

Owns:

- branch rules
- commit readiness
- commit messages
- PR creation
- merge readiness
- release checklist
- escalation when implementation does not match ticket scope

### Knowledge And Documentation Agent

Primary responsibility: preserve durable learning.

Owns:

- project docs
- decisions
- session/run summaries
- archive hygiene
- documentation drift checks

### Optimization Department

Primary responsibility: improve agents and skills over time.

Owns:

- validation tasks
- scoring rubrics
- evidence review
- bounded improvement proposals
- canonical promotion gates

Each department can keep its own improvement notes, but central optimization runs validation and promotion.

## Communication Rule

When raising a meaningful problem or decision to the owner or another agent:

- state the context
- state the decision needed
- provide up to three options
- recommend one option
- explain why
- include pros/cons when useful

Important decisions should normally include three options.

## Approval Levels

Proposed approval levels:

- Level 0: agent can do freely inside assigned scope.
- Level 1: reviewer or release agent approval is enough.
- Level 2: founder inbox approval required.
- Level 3: blocked until explicit product/architecture decision.

Founder approval is required for:

- architecture changes
- project truth changes
- meaningful product direction drift
- external API/MCP/paid service usage unless already approved
- credential/security-sensitive changes

## Context Packs

Every execution or review session should receive a compact context pack.

Execution context pack:

- project, goal, feature, task, ticket
- objective
- acceptance criteria
- relevant files/docs
- constraints
- prior decisions
- expected output
- reporting format

Review context pack:

- original intent
- assigned ticket
- acceptance criteria
- implementation summary
- changed files/artifacts
- tests/evidence
- specialist concerns
- review output format

## Release Rule

Execution agents do not commit directly.

Release agent can commit when:

- ticket scope matches result
- review passed or required revision completed
- tests/checks are sufficient for risk level
- docs/state updates are complete when needed
- no founder-level approval is pending

If any of those fail, the release agent rejects, requests revision, or escalates.