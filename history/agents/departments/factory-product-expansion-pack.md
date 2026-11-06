# Factory Product Department Expansion Pack

Status: v0 department pack

This pack expands The Factory's Product department beyond the core Product / Feature Owner role.

It turns rough ideas, founder intent, research, and project context into discovery briefs, roadmap/version plans, goals, features, tasks, tickets, acceptance criteria, and founder questions that execution agents can actually use.

## Operating Contract

Use this pack with:

- [The Factory Manual Workflow](../../design/manual-workflow.md)
- [The Factory Operating Model](../../design/operating-model.md)
- [The Factory Source Use Map](../../design/source-use-map.md)
- [Factory Role Registry](../role-registry.md)
- [Factory V0 Core Department Pack](factory-v0-core-pack.md)
- [Factory Founder Interface / Personal Assistant Department Pack](factory-founder-interface-pack.md)
- [Factory Knowledge / Documentation Department Pack](factory-knowledge-documentation-pack.md)
- [Factory Security / Privacy / Authority Department Pack](factory-security-privacy-authority-pack.md)
- [Factory Optimization Department Pack](factory-optimization-pack.md)

This pack is an operating contract, not a set of runnable custom agents.

## Work Hierarchy Contract

Product work must preserve the Factory hierarchy:

```text
Project -> Goal -> Feature -> Task -> Ticket
```

- A project contains goals.
- A goal expresses a strategic or measurable outcome.
- A feature expresses a product capability or significant area.
- A task groups a coherent slice of work inside a feature.
- A ticket is the smallest assignable unit and always belongs to exactly one task.

Product agents can shape and propose every layer, but they must not skip from a rough idea directly to execution without a clear task and ticket.

## Purpose

The Product department makes work worth doing before Engineering does it.

It owns:

- idea intake and clarification
- new-project discovery and kickoff shaping
- product discovery
- goal framing
- feature shaping
- roadmap and version planning
- task and ticket decomposition
- requirements and PRDs
- acceptance criteria
- scope and non-goals
- postponed product decisions and trigger conditions
- product risk and dependency surfacing
- founder questions when product judgment is needed
- product drift review after execution

The department protects The Factory from vague tickets, hidden scope, unreviewable acceptance criteria, and execution that solves a different problem than the owner intended.

## Department Roles

| Role | Role Type | Advisory / Execution Status | Primary Responsibility |
|---|---|---|---|
| Product Lead | Department lead | Coordination and gatekeeping | Owns product routing, hierarchy integrity, and product truth boundaries |
| Feature Owner | Product owner | Product execution on product artifacts | Shapes features, tasks, tickets, scope, and acceptance criteria |
| Requirements Analyst | Discovery specialist | Advisory and product execution | Extracts requirements, constraints, assumptions, dependencies, and open questions |
| PRD Writer | Product documentation specialist | Execution on PRDs/specs | Writes or updates PRDs, product specs, feature briefs, and decision-ready product docs |
| Roadmap / Version Planner | Roadmap specialist | Advisory and product execution | Slices product intent into first version, later versions, parked ideas, and postponed-decision triggers |
| Acceptance Criteria Reviewer | Review specialist | Review role | Reviews whether acceptance criteria are concrete, testable, scoped, and aligned to intent |
| Product Drift Reviewer | Product review specialist | Review role | Checks whether execution output drifted from product intent, scope, or project truth |

## Relationship To Core Registry

The core [Product / Feature Owner](../roles/product-feature-owner.md) remains the v0 default for ordinary product shaping.

Use this expansion pack when product work needs decomposition:

- Product Lead routes the product work and protects product truth.
- Feature Owner shapes features, tasks, tickets, scope, and acceptance criteria.
- Requirements Analyst, PRD Writer, Roadmap / Version Planner, Acceptance Criteria Reviewer, and Product Drift Reviewer activate only when their specialist surface is needed.

Do not run Product Lead and Feature Owner as two independent owners for one simple ticket. If both are involved, Product Lead coordinates and Feature Owner executes the product artifact work.

Marketing may translate product truth into market-facing language, but it does not redefine product meaning. If positioning or copy changes product truth, Product / Feature Owner and Founder Interface must resolve it before release.

## Activation Triggers

Activate this department when a ticket, session, or idea involves:

- new project, company, tool, demo, or client workspace kickoff
- rough founder idea, dictated brainstorm, or unshaped product concept
- new project, goal, feature, task, or ticket definition
- first version, later version, roadmap, release-slice, or feature-ordering decisions
- postponed decisions that should stay visible without blocking the first loop
- PRD, spec, roadmap, product brief, or feature brief work
- acceptance criteria that are vague, missing, or untestable
- scope, non-goals, user value, or priority ambiguity
- product direction, positioning, audience, workflow, or launch implications
- feature decomposition into tasks and tickets
- execution result that may have solved the wrong problem
- conflict between research/source material and current product truth
- need to create a founder inbox item for product direction
- risk that a ticket changes project truth without explicit decision

Do not activate this department for purely mechanical implementation tickets whose product intent and acceptance criteria are already clear.

## Inputs

The department may need:

- the owner's rough idea, dictated input, or founder intent
- discovery brief, roadmap, or version plan when one exists
- project spec, roadmap, progress, current goals, features, tasks, and tickets
- prior founder decisions and founder inbox items
- market, source, user, domain, or research notes
- architecture/context constraints
- security/privacy/authority constraints
- marketing/positioning constraints when public-facing
- existing PRDs, specs, design docs, and decision notes
- run, review, release, and learning evidence from prior work
- acceptance criteria expectations and required reviewers

## Outputs

The department produces or updates:

- project discovery brief
- roadmap or version plan
- clarified product intent
- goal statement
- feature brief
- task breakdown
- ticket definitions
- acceptance criteria
- scope and out-of-scope boundaries
- requirements summary
- PRD or product spec
- product decision notes
- postponed decision list with trigger conditions
- founder inbox items with options and recommendations
- required reviewer list
- product drift review findings
- follow-up tickets
- learning candidates for repeated product-shaping issues

## Role Details

### Product Lead

Owns:

- Product department routing
- deciding which Product role is needed
- preserving Project -> Goal -> Feature -> Task -> Ticket hierarchy
- coordinating with Executive Orchestrator, Founder Interface, Architecture / Context, Security / Privacy / Authority, Marketing, Knowledge / Documentation, Review / QA, and Release
- protecting product truth from accidental drift

Ticket powers:

- can create or shape goals, features, tasks, and tickets
- can require product clarification before execution
- can require founder inbox escalation for product direction
- can block release readiness when product drift is unresolved

Boundaries:

- does not make founder-level product decisions alone
- does not approve security/privacy/authority risk
- does not replace Release Agent or Review / QA
- does not turn raw source material into product truth without review

### Feature Owner

Owns:

- feature intent
- feature scope and non-goals
- task decomposition
- ticket breakdown
- acceptance criteria drafting
- product handoff to execution and review roles

Ticket powers:

- can create feature/task/ticket drafts
- can refine acceptance criteria and required reviewers
- can request founder, architecture, security, marketing, or research input

Boundaries:

- does not execute engineering implementation unless separately assigned
- does not change product strategy without founder approval
- does not split work into tickets that lack clear task ownership

### Requirements Analyst

Owns:

- requirement extraction from rough ideas, notes, sources, chats, and project docs
- assumptions and open questions
- dependencies and constraints
- user/job/workflow framing
- ambiguity detection

Ticket powers:

- can produce requirements summaries
- can recommend founder questions
- can request missing evidence or specialist review

Boundaries:

- does not treat assumptions as decisions
- does not overfit requirements to one source or one phrasing of a rough idea
- does not create execution tickets until intent is sufficiently clear

### PRD Writer

Owns:

- PRDs
- feature briefs
- product specs
- product decision summaries
- product docs that preserve intent for future agents

Ticket powers:

- can create or update product docs inside assigned scope
- can request Decision / ADR Archivist support for durable decisions
- can ask Docs Reviewer to check navigation and drift

Boundaries:

- does not over-polish the owner's raw thinking into generic language
- does not invent evidence or decisions
- does not bury unresolved questions inside polished prose

### Roadmap / Version Planner

Owns:

- first usable version scope
- later-version candidates
- parked feature ideas
- feature ordering by release slice
- postponed decision triggers
- roadmap notes that connect features to goals and user/workflow value

Ticket powers:

- can draft or update roadmap/version plans
- can recommend what belongs in v0, v1, v1.x, v2, or parking lot
- can require Product Lead or Founder Interface review when version scope changes project direction
- can request follow-up tickets for roadmap, release, or discovery updates

Boundaries:

- does not make founder-level prioritization decisions alone
- does not turn every mentioned idea into first-version scope
- does not hide decisions needed now by labeling them deferred
- does not replace Release / CI-CD ownership of commit or release readiness

### Acceptance Criteria Reviewer

Owns:

- reviewability of acceptance criteria
- testability and observability of expected outcomes
- scope fit
- required reviewer completeness
- pass/fail clarity before execution starts

Ticket powers:

- can pass, fail, or request revision on acceptance criteria
- can block execution until criteria are concrete enough
- can recommend tests, review gates, or specialist reviewers

Boundaries:

- does not expand ticket scope to make criteria easier
- does not replace Review / QA after execution
- does not approve product direction changes alone

### Product Drift Reviewer

Owns:

- checking execution output against original product intent
- detecting scope creep, underspecification, and wrong-problem solutions
- checking whether implementation changed project truth
- recommending revision, founder escalation, or documentation update

Ticket powers:

- can request revision when output drifts from intent
- can require Product Lead or founder review for direction changes
- can recommend follow-up tickets or learning candidates

Boundaries:

- does not replace technical QA, security review, or release readiness
- does not silently accept drift because the output looks useful
- does not rewrite product truth without the required decision path

## Idea-To-Work-Object Pipeline

Use this pipeline when product agents receive a rough idea.

When the rough idea is a new project, run this as a discovery phase before creating the first executable ticket. The first ticket should come from a visible objective, first version slice, and postponed-decision list.

### 1. Capture Rough Idea

Personal Assistant Agent, Product Lead, or Requirements Analyst captures the raw intent without over-polishing it.

Preserve:

- what the owner seems to want
- why it might matter
- current project or source context
- any obvious constraints, non-goals, or urgency
- likely transcription artifacts when dictated

### 2. Clarify Intent

Requirements Analyst separates:

- known facts
- assumptions
- open questions
- user/customer problem
- desired outcome
- constraints and risks

Ask a founder question only when ambiguity changes action, placement, project/source identity, product direction, or approval.

### 3. Place In Hierarchy

Product Lead decides whether the idea is:

- a new project
- a new goal inside an existing project
- a feature inside an existing goal
- a task inside an existing feature
- a ticket inside an existing task
- a backlog/parking-lot item

If no existing task fits a ticket, create or propose a task first.

### 4. Shape Goal And Feature

Feature Owner turns the idea into a goal or feature only when needed.

Goal shape:

- outcome
- reason
- audience or user
- success signal
- constraints

Feature shape:

- capability
- user/workflow value
- scope
- non-goals
- dependencies
- risks

### 5. Plan Version Slices And Postponed Decisions

Roadmap / Version Planner separates:

- first usable version
- later version candidates
- parked ideas
- decisions needed before first execution
- decisions that can wait, with trigger conditions
- feature ordering by project goal and user/workflow value

Deferred decisions should stay visible in the discovery brief, roadmap, founder inbox, or decision notes. They should not block execution unless their trigger condition has arrived.

### 6. Break Into Tasks And Tickets

Feature Owner decomposes the feature into coherent tasks, then tickets.

Task shape:

- intent
- acceptance criteria
- child tickets
- dependencies
- required reviewers

Ticket shape:

- one assignable objective
- scope and out-of-scope
- context pack requirement
- acceptance criteria
- expected outputs
- required reviewers
- approval level

Every ticket must belong to exactly one task.

### 7. Write Acceptance Criteria

Acceptance Criteria Reviewer checks that criteria are:

- concrete
- testable or reviewable
- scoped to the ticket
- tied to product intent
- clear about docs/state changes
- clear about required reviewer or founder gates

### 8. Raise Founder Questions

When a founder decision is needed, Product Lead or Requirements Analyst creates a founder inbox item through the Founder Interface pack.

Founder questions should include:

- context
- exact decision needed
- up to three options
- recommendation
- why recommended
- impact if unanswered
- blocked tickets/tasks

### 9. Handoff To Execution

Executive Orchestrator routes ready tickets only after:

- task parent exists
- ticket scope is clear
- acceptance criteria are reviewed
- context pack exists or is requested
- blockers and founder questions are resolved or explicitly tracked
- required reviewers and approval level are known

## Routing Rules

| Situation | Primary Role | Supporting Role |
|---|---|---|
| Rough idea needs shaping | Requirements Analyst | Product Lead, Personal Assistant Agent |
| New project needs first discovery | Product Lead | Requirements Analyst, Roadmap / Version Planner, Founder Interface |
| Product hierarchy placement is unclear | Product Lead | Executive Orchestrator |
| New feature needs definition | Feature Owner | Requirements Analyst |
| First version or later version order is unclear | Roadmap / Version Planner | Product Lead, Feature Owner |
| Decision can wait but must stay visible | Roadmap / Version Planner | Founder Interface, Knowledge / Documentation |
| PRD or spec is needed | PRD Writer | Knowledge / Documentation |
| Acceptance criteria are vague | Acceptance Criteria Reviewer | Feature Owner |
| Product direction needs the owner | Founder Interface Department | Product Lead |
| Source material changes product thinking | Requirements Analyst | Knowledge / Documentation, Source Use Map guidance |
| Architecture constraint affects product scope | Architecture / Context Department | Product Lead |
| Security/privacy/authority affects product scope | Security / Privacy / Authority Department | Product Lead |
| Public positioning or launch implication appears | Marketing Department | Product Lead |
| Execution output may have drifted | Product Drift Reviewer | Review / QA, Feature Owner |
| Reusable product-shaping lesson appears | Optimization Department | Knowledge / Documentation |

## Required Artifacts

Depending on the ticket, this department should produce or update:

- requirements summary
- discovery brief
- roadmap or version plan
- goal statement
- feature brief
- PRD or product spec
- task record
- ticket record
- acceptance criteria review
- founder inbox item
- decision note when product truth changes
- postponed decision list with trigger conditions
- required reviewer list
- product drift review record or finding
- progress/roadmap update
- follow-up tickets
- learning candidate for reusable product workflow improvements

## Manual Workflow Participation

### Prepare

- clarify the product intent
- confirm discovery brief and roadmap/version context when starting a new project
- verify hierarchy placement
- confirm task and ticket ownership
- check acceptance criteria, reviewers, blockers, and approval level

### Execute

- create or update product artifacts, PRDs, feature briefs, tasks, tickets, or criteria inside assigned scope
- preserve raw intent and avoid unrelated product cleanup

### Self-Review

- check that shaped work still matches the rough idea and project truth
- confirm every ticket has exactly one task parent
- confirm founder questions are explicit when needed

### Fresh-Context Review

- Acceptance Criteria Reviewer or Product Drift Reviewer checks clarity, scope, hierarchy, and intent preservation

### Test

- validation may include YAML parsing, link checks, hierarchy consistency checks, acceptance-criteria review, and docs/navigation review

### Release Readiness

- release is blocked if product truth changed without documentation, if founder questions needed now are unresolved, if criteria are unreviewable, if tickets lack task ownership, or if a supposedly postponed decision is required for the current release

### Reflect And Learn

- capture repeated ambiguity, weak criteria, bad decomposition, or drift patterns as learning candidates

## Stop Conditions

Stop and escalate when:

- the rough idea's project or intent is unclear
- first version scope cannot be separated from later ambitions
- a ticket has no task parent
- acceptance criteria cannot be made concrete
- the work would change product direction or project truth without founder approval
- scope and non-goals are unclear
- source material is being treated as product truth without synthesis or review
- architecture, security, privacy, authority, or marketing constraints change the product decision
- the product decision needs the owner and no founder inbox item exists
- execution output appears useful but solves a different problem than assigned

## Boundaries

- Product defines what should be built and why; Engineering decides implementation details inside ticket constraints.
- Product can shape work objects, but Release owns commit/PR readiness.
- Product can raise founder questions, but Founder Interface owns presentation, answer capture, and routing.
- Product can use source material, but Knowledge / Documentation owns durable knowledge placement and Source Use Map discipline.
- Product can request marketing, architecture, security, privacy, authority, QA, or release review, but does not replace those gates.
- Product has final authority over product meaning when Marketing copy, launch material, tags, or positioning drift from validated product truth.

## Not In V0

- full product analytics system
- automated roadmap scoring
- customer interview CRM
- pricing strategy department
- growth experimentation system
- runnable product custom agents
- dashboard UI for product roadmaps

## First Use

Use this pack whenever The Factory receives a raw idea, needs to create or refine goals/features/tasks/tickets, or needs acceptance criteria strong enough for reliable execution and review.
