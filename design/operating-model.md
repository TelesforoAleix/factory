# The Factory Operating Model

## Company Model

The Factory should behave like a small software company with departments, managers, execution workers, reviewers, release ownership, and founder escalation.

Agents are functional roles, not personalities.

## Work Hierarchy

```text
Project -> Goal -> Feature -> Task -> Ticket
```

- Project: product or initiative.
- Goal: strategic or measurable outcome inside the project.
- Feature: product capability or significant functional area.
- Task: larger unit of work inside a feature.
- Ticket: smallest assignable unit for an agent.

Tickets always belong to exactly one task. A task can contain multiple tickets. Bugs, chores, and follow-ups should still be represented as tickets under an existing task, or under a newly created task when no existing task fits.

Before the first goal, feature, task, or ticket in a new project, Product runs project discovery. Discovery turns raw founder intent into objectives, first version scope, postponed decisions, and the first work hierarchy.

## Default Lifecycle

Initial lifecycle:

```text
inbox -> discovery -> ready -> assigned -> in_progress -> self_review -> external_review -> testing -> revision -> release_ready -> shipped -> archived
blocked
```

New-project kickoff lifecycle:

```text
raw intent -> product discovery -> discovery brief -> roadmap/version plan -> first goal/feature/task/ticket
```

Meaning:

- inbox: captured but not yet shaped.
- discovery: product/manager agents are asking questions and defining intent.
- ready: ticket has enough context and acceptance criteria.
- assigned: owner selected.
- in_progress: execution started.
- self_review: execution agent reflects on its own work before handoff.
- external_review: fresh-context review is active.
- testing: the system checks that the work behaves correctly.
- revision: execution needs changes after self-review, external review, or testing.
- release_ready: release agent can evaluate commit/PR readiness.
- shipped: committed/merged/released according to project rules.
- archived: operational state closed, durable learning preserved.
- blocked: needs external decision, missing information, or dependency.

Review and testing are separate concepts. Review checks what was built against intent and quality; testing checks that it works.

## Core Role Layers

### Founder Interface

Primary responsibility: communicate with the owner.

Owns:

- founder inbox
- status summaries
- decision interviews
- open questions
- important escalations

Founder inbox items can block a ticket. When the owner answers through the personal assistant, the assistant records the decision and unblocks or reroutes the ticket.

### Executive Orchestrator

Primary responsibility: route work across departments.

Owns:

- project-level coordination
- department routing
- dependency management
- parallel work coordination
- final synthesis for the owner
- deciding which ready tickets can run in parallel

### Product / Feature Owner

Primary responsibility: define what should be built.

Owns:

- project discovery and kickoff shaping
- discovery
- requirements
- PRDs
- roadmap and version slices
- roadmap slices
- goals/features/tasks/tickets
- acceptance criteria
- postponed decision register when product decisions can wait
- product drift detection

Feature-owner and orchestrator responsibilities may be held by the same agent in v0 when that is simpler.

### Architect / Context Architect

Primary responsibility: define system shape and context strategy.

Owns:

- system boundaries
- data flow
- architecture decisions
- context packs
- retrieval/memory/context decisions when relevant
- technical tradeoffs

Architectural advice can be provided by a read-only advisory agent when the task needs knowledge synthesis rather than execution.

### Advisory Agent

Primary responsibility: provide knowledge-backed advice without executing work.

Owns:

- reading relevant notes from the knowledge base
- surfacing useful references and prior decisions
- comparing options
- identifying risks and missing context
- recommending an approach

Does not own:

- editing product code
- committing or releasing
- changing operational state
- executing tickets

Advisory agents can support architecture, product, marketing, research, context, security, privacy, or authority decisions. They should be used when a role needs broad knowledge access but should not act directly.

### Execution Agent

Primary responsibility: complete scoped tickets.

Owns:

- implementation
- local reasoning about assigned ticket
- clear result reports
- creating help tickets when blocked
- self-review before handoff

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

Every ticket should declare required reviewers when known. The orchestrator or feature owner can add missing reviewers when the ticket's risk profile changes.

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
- marketing/copy

### Marketing Agent

Primary responsibility: market-facing language and materials when relevant.

Owns:

- landing-page copy suggestions
- tags and messaging
- positioning alternatives
- market research when needed
- launch or marketing material review

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

When raising a meaningful problem or decision to the owner:

- state the context
- state the decision needed
- provide up to three options
- recommend one option
- explain why
- include pros/cons when useful

Important decisions should normally include three options.

Agent-to-agent communication does not always need the options format. Agents should share insight, recommendations, risks, and next-action suggestions in the format most useful to the receiving agent.

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

The v0 format can be JSON, YAML, or Markdown with frontmatter. The priority is lightweight machine usability plus enough human readability for the owner to inspect.

## Release Rule

Execution agents do not commit directly.

Release agent can commit when:

- ticket scope matches result
- self-review is complete
- external review passed or required revision completed
- tests/checks are sufficient for risk level
- docs/state updates are complete when needed
- no founder-level approval is pending

If any of those fail, the release agent rejects, requests revision, or escalates.

Release agent can batch multiple tickets into a task-level commit when they form one coherent unit of work.
