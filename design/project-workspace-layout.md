# Project Workspace Layout

## Purpose

The Factory should be reusable across projects without putting every operational artifact in the brain.

Each real project gets its own workspace that syncs reusable agents and keeps project-specific product and ops state local.

## Preferred Layout

```text
project-x/
  .github/
  agents/
  product/
  ops/
```

## `.github/`

Project-local instructions, prompts, workflows, and tool configuration.

Possible contents:

- `copilot-instructions.md`
- project-specific prompt wrappers
- workflow docs
- CI/CD configuration when appropriate
- templates for PRs/issues/checklists

Source:

- copied or synced from the brain's canonical agent system
- adapted with project-specific context

## `agents/`

Synced copy of reusable agent and skill definitions.

Possible contents:

- department definitions
- role/agent specs
- skill specs
- prompt wrappers
- validation/eval sets
- local project overrides

Source:

- canonical definitions from `04-agents/`
- generated or copied into the project workspace

## `product/`

Actual product/application code and artifacts.

This is where execution agents edit product files.

Release/CI/CD rules decide how work moves from local changes to commits, PRs, and merges.

## `ops/`

Project-specific operating state for The Factory.

Possible structure:

```text
ops/
  goals/
  features/
  tasks/
  tickets/
  runs/
  inbox/
  approvals/
  context-packs/
  reviews/
  releases/
  learning/
  archive/
  dashboard-state/
```

Use Markdown for human-readable product/decision records and YAML/JSON for machine-friendly state.

Potential files:

- `tickets/*.yaml`
- `runs/*.json`
- `inbox/*.yaml`
- `approvals/*.yaml`
- `context-packs/*.md`
- `reviews/*.yaml`
- `releases/*.md`
- `learning/*.yaml`

## V0 Template

The copyable v0 scaffold now lives at [Project Workspace Template](../templates/project-workspace/README.md).

The exact state schema is still allowed to evolve, but the v0 folder shape should include the manual workflow surfaces already used by The Factory itself: goals, features, tasks, tickets, runs, inbox, approvals, context packs, reviews, releases, learning, dashboard state, and archive.

## Open Design Choice

The exact object schema is not locked.

The next design pass should define minimal v0 schemas for:

- ticket
- run
- founder inbox item
- approval
- context pack
- review record
- release checklist
- learning candidate

## Guardrail

The brain should keep reusable design and high-level project knowledge. The project workspace should keep day-to-day operational state.