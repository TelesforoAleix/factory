# The Factory Architecture

## Architecture Thesis

The Factory should be a reusable operating system for agentic product development.

It should separate:

- reusable agents and skills
- project-specific product code
- project-specific operational state
- human/founder decisions
- release and governance gates

## Core Layers

### 1. Canonical Brain Layer

Lives in this brain.

Purpose:

- design The Factory
- maintain reusable agent and skill definitions
- preserve source research and decisions
- improve agents/skills over time
- support The Factory's own early development alongside the reusable definitions in `agents/`

Primary locations:

- [The Factory project](../README.md)
- [Development Team Layer](../agents/README.md)

### 2. Project Workspace Layer

Lives in each real project workspace.

Purpose:

- run The Factory for a specific project
- keep project-specific tickets, runs, inbox, approvals, and archives local to the project
- avoid flooding the brain with every operational artifact

Recommended structure:

```text
project-x/
  .github/
  agents/
  product/
  ops/
```

The Factory is an exception during its own design/build phase: its design and its reusable definitions in `agents/` are developed together in this repository. Once The Factory is used for external products, project-specific operational state should live in each product workspace.

### Advisory Knowledge Layer

Some agents should be advisory only.

Purpose:

- read relevant knowledge from the knowledge base
- synthesize options, risks, and references
- provide architectural, product, market, privacy, or context advice
- avoid direct execution, commits, file edits, or operational state changes unless explicitly promoted into another role

Architecture advisory agents are the first expected example, but the pattern can apply to product, marketing, context, privacy, security, or research advisors.

### 3. Control Plane Layer

Starts as files and templates; later becomes a local dashboard.

Purpose:

- show what is happening
- route work
- create and assign tickets
- manage founder inbox
- track approvals and release readiness
- generate context packs

### 4. Execution Layer

Runs in VS Code/Copilot, CLI agents, or future adapters.

Purpose:

- execute assigned tickets
- review work
- run tests/checks
- produce artifacts
- report results back to ops state

### 5. Learning Layer

Improves agents and skills from usage evidence.

Purpose:

- collect failure patterns
- maintain department improvement notes
- run validation tasks
- propose bounded edits
- promote better agent/skill versions only after review

## Data Direction

Use the simplest durable representation that serves the workflow.

- Markdown: specs, requirements, decisions, roadmaps, documentation, retros.
- YAML/JSON: tickets, runs, inbox items, approvals, dashboard state.
- Git: history, provenance, rollback.
- Database: defer until dashboard performance/query complexity requires it.

## Integration Direction

The dashboard should not need deep VS Code integration at v0.

Possible bridge sequence:

1. Ops state generates context packs.
2. CLI or dashboard command opens/prints the right context.
3. Agent execution happens in VS Code/Copilot or CLI.
4. Results are written back to ops state.
5. Release agent verifies and commits when appropriate.

## Source Influence

- Paperclip: control plane and operational objects.
- gstack: workflow loop and review gates.
- ECC: layered agent/skill/rule architecture.
- SkillOpt: improvement and validation loop.
- Claude Playbook: compact placement discipline.

## Architecture Guardrails

- Do not make every agent global or always active.
- Do not give every agent every responsibility.
- Do not hide important decisions inside chat transcripts.
- Do not commit execution output without fresh-context review.
- Do not add background automation before manual workflows are reliable.
- Do not introduce a database before YAML/JSON/Markdown state proves insufficient.
