# The Factory Spec

The Factory is the owner's reusable AI development company operating system.

It should feel like a software company made of agents and skills: managers own areas of work, execution agents implement scoped tickets, reviewers validate with fresh context, release agents handle commit/PR flow, and a founder interface keeps the owner aware of decisions, blockers, and progress.

## Purpose

The Factory helps the owner build projects without losing product intent, architectural decisions, task state, or learning across long agent-assisted development cycles.

The first serious test is [project], but The Factory is not an [project]-only team. It should be reusable for any project the owner starts.

## Core Thesis

AI development should be managed through company-like operating structures, not loose chat sessions.

The stable system should include:

- a reusable agent and skill layer
- a project-specific operational layer
- read-only advisory agents that can use brain knowledge without executing work
- clear work objects and ownership
- context packs for isolated agent sessions
- explicit review and release gates
- a founder inbox for important decisions
- self-improvement loops for agents and skills
- a dashboard/control plane that shows what is happening

## Work Hierarchy

Preferred hierarchy:

```text
Project -> Goal -> Feature -> Task -> Ticket
```

- Project: the product or tool being built.
- Goal: the outcome or strategic objective.
- Feature: a user-facing or system-facing capability.
- Task: a larger unit of work inside a feature, such as adding a functionality.
- Ticket: the smallest assignable unit for an agent.

Tasks can contain multiple tickets. Tickets are what execution agents should normally receive.

## Operating Loop

The default loop is inspired by gstack but adapted to The Factory:

```text
Think -> Plan -> Build -> Review -> Test -> Release -> Reflect
```

Each stage should produce durable state:

- Think: product framing, discovery questions, assumptions.
- Plan: goals, features, tasks, tickets, context packs.
- Build: execution agent outputs, changed files, implementation notes.
- Review: fresh-context review, specialist review, revision requests.
- Test: verification evidence and failures.
- Release: commit/PR/merge decision and release notes.
- Reflect: session notes, knowledge updates, agent/skill improvement candidates.

## Roles And Departments

The Factory should eventually feel like a full company, but v0 should start with a compact core.

Initial departments:

- Founder Interface: the owner's assistant/inbox layer.
- Executive Orchestration: routes work and coordinates departments.
- Product: discovery, requirements, PRDs, roadmaps, goals, features, tasks.
- Architecture: system boundaries, context architecture, data flow, tradeoffs.
- Engineering: execution agents that implement scoped tickets.
- Review And QA: fresh-context review, testing, regression checks, specialist review routing.
- Release And CI/CD: branch, commit, PR, merge, and verification gates.
- Knowledge And Documentation: specs, decisions, run/session logs, project docs.
- Security, Privacy, And Authority: risk review, GDPR, permissions, sensitive work.
- Optimization: validates and improves agents and skills over time.

## Company-Like Work Model

The Factory separates responsibilities:

- Manager/feature-owner agents own intent, context, decisions, decomposition, and assignment.
- Execution agents work on isolated tickets with context packs.
- Review agents compare result against intent and acceptance criteria with fresh context.
- Specialist reviewers join only when relevant: security, UX/UI, data, privacy, architecture, context.
- Release agents own commit/PR readiness and finalization.

## Founder Inbox

the owner should not have to inspect every agent transcript.

Important questions and blockers should flow to a founder inbox with:

- ticket or task context
- what is being built
- what problem was found
- up to three options
- recommendation and why
- pros/cons when useful
- impact of choosing nothing

The same inbox should be available in the dashboard and through a personal assistant conversation.

## Dashboard Direction

The dashboard should be a local control plane over The Factory.

It should eventually show:

- projects, goals, features, tasks, and tickets
- agent roster and current ownership
- founder inbox
- active runs/sessions
- blocked work
- approvals
- release/CI status
- knowledge/docs updates
- agent/skill improvement queue

The first dashboard does not need to be built immediately. The next step is architecture/spec and folder templates.

## Project Workspace Model

The Factory itself is a special case: its design and its reusable definitions in `agents/` live together in this repository while the operating system is still being designed.

Normal product projects should use the project workspace model below.

For each real project, The Factory should be copied or synced into a project workspace that separates:

```text
project-x/
  .github/
  agents/
  product/
  ops/
```

- `.github/`: project-local instructions, prompts, and tool configuration.
- `agents/`: synced reusable agent/skill layer from the brain.
- `product/`: actual product code and artifacts.
- `ops/`: project-specific tickets, runs, dashboard state, approvals, inbox, and operational logs.

The brain remains the canonical design/source for reusable agents. Project operational state should not flood the brain.

## State And Data Direction

Initial preference:

- Markdown for product descriptions, specs, roadmaps, decisions, and human-readable docs.
- YAML/JSON for operational state such as tickets, runs, inbox items, approvals, and dashboard data.
- Database only later if dashboard complexity justifies it.

## Dashboard Bridge Direction

The dashboard should run locally and communicate with VS Code/Copilot or CLI-based agent execution.

Possible bridge path:

1. Dashboard creates tickets/context packs and writes ops state.
2. A CLI or VS Code-adjacent command starts the correct agent workflow.
3. The agent works in VS Code/Copilot or CLI.
4. Results write back to ops state.
5. Dashboard displays status, inbox items, and release readiness.

## Source Strategy

The Factory should merge the best patterns from multiple sources:

- Paperclip: control plane, org chart, ticketing, heartbeats, inbox, approvals, activity.
- gstack: Think -> Plan -> Build -> Review -> Test -> Ship -> Reflect loop.
- ECC: layered architecture of rules, skills, agents, hooks, commands, adapters, memory.
- SkillOpt: self-improving skills and validation gates.
- Claude Playbook: compact rule/skill/agent/hook placement discipline.
- Cybersecurity Skills: security skill anatomy and progressive disclosure.
- Prompt Master and Matt Pocock skills: prompt wrappers and practical engineering workflows.

Overlapping source patterns should be compared before implementation rather than blindly copied.

## What The Factory Is Not

- Not an [project]-only development team.
- Not a loose pile of prompts.
- Not a generic chatbot.
- Not an always-on autonomous runtime in v0.
- Not a dashboard-first project before the operating model is defined.
- Not a system where every agent does everything.
- Not a replacement for the brain's markdown/git memory.

## Success Criteria

The Factory is working when the owner can start a project and quickly get:

- reusable agents and skills synced into the project workspace
- a clear project hierarchy and ticket flow
- agent assignments with context packs
- execution and review separation
- founder inbox items for important decisions
- release/CI/CD governance
- project docs updated as work progresses
- agent and skill improvement candidates captured after use
