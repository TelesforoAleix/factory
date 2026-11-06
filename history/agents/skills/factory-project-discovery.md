---
type: skill
created: 2026-06-06
---
# Factory Project Discovery - Skill Agent

Runs the first discovery phase before a new Factory-managed project starts execution.

## Trigger

Use when the owner starts a new project, company, tool, product, demo, or client workspace that will use The Factory, or when existing work is still too vague to create reliable tasks and tickets.

This skill should run before execution when objectives, product shape, first version scope, postponed decisions, or required knowledge are unclear.

## Use With

- Product / Feature Owner
- Product Lead
- Requirements Analyst
- Roadmap / Version Planner
- Executive Orchestrator
- Founder Interface / Personal Assistant
- Advisory Architect when architecture or context strategy affects the first version
- Knowledge / Documentation when durable project truth, decisions, or source links need to be preserved

## Input Assumption

The owner may describe the project through dictated speech. Remove filler, repetition, and likely transcription artifacts while preserving intent. Ask only when ambiguity changes project identity, product direction, first version scope, approval, or execution readiness.

## Discovery Sequence

1. Capture the raw product intent in the owner's words.
2. Identify objectives, target users or audience, core workflows, success signals, and constraints.
3. Separate known facts, assumptions, open questions, and decisions needed later.
4. Check the knowledge base for relevant project history, source notes, personal principles, domain knowledge, and reusable patterns.
5. Draft the first version slice: what must be in the first usable release, what belongs in later versions, and what is explicitly out of scope.
6. Create a postponed decision list with trigger conditions so deferred decisions are visible instead of forgotten.
7. Place the first work into the Factory hierarchy: Project -> Goal -> Feature -> Task -> Ticket.
8. Decide which departments, roles, skills, reviewers, and context packs are needed for the first execution loop.
9. Hand off only when the first task and ticket can be written with objective, scope, non-goals, acceptance criteria, required reviewers, approval level, and context pack.

## Outputs

The discovery pass should produce or update:

- project discovery brief
- product roadmap or version plan
- first goal and feature candidates
- first task and ticket candidates
- scope and non-goals
- known constraints and assumptions
- postponed decision list with trigger conditions
- required knowledge inputs and source links
- department/role/skill routing recommendation
- founder inbox items for decisions that block execution

## Handoff Readiness

Execution can start only when:

- the project objective is clear enough to judge whether work matches intent
- the first version slice is explicit
- later-version ideas are parked or linked to the roadmap
- decisions needed now are answered or represented as blockers
- decisions not needed yet are visible with trigger conditions
- the first ticket has one parent task and reviewable acceptance criteria
- required reviewers, approval level, and context pack needs are known

## Stop Conditions

Stop and route to Founder Interface or Product Lead when:

- the project identity or owner is unclear
- the product objective cannot be stated without guessing
- the first version cannot be separated from later ambitions
- a postponed decision is actually needed before execution
- product direction, architecture, security/privacy/authority, or market positioning requires the owner's judgment
- the available knowledge is too thin to create responsible acceptance criteria

## In-Chat Receipt Style

Use a short receipt when discovery artifacts are updated:

- Discovery captured.
- Discovery updated.
- Roadmap updated.
