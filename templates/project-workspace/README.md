# Project Workspace Template

Copyable v0 workspace scaffold for installing The Factory into future project workspaces.

This template keeps project-specific product work and operating state outside the brain while preserving a simple connection to the canonical Factory role and prompt system.

## Structure

```text
project-workspace/
  .github/
  agents/
  product/
    DISCOVERY.md
    ROADMAP.md
  ops/
```

## Folder Boundaries

- `.github/`: project-local instructions, prompts, workflows, and tool configuration.
- `agents/`: synced or copied reusable Factory roles, departments, skills, prompt wrappers, and local overrides.
- `product/`: discovery brief, roadmap/version plan, actual application, tool, product, or artifact code.
- `ops/`: project-specific Factory operating state.

## Operating State

The `ops/` folder starts with the v0 manual workflow surfaces:

```text
ops/
  goals/
  features/
  tasks/
  tickets/
  runs/
  interactions/
  inbox/
  approvals/
  context-packs/
  reviews/
  releases/
  learning/
  dashboard-state/
  archive/
```

Use the object examples in [Ops Templates](../ops/README.md) as the source shape for concrete task, ticket, run, interaction, inbox, approval, context-pack, review, release, and learning records.

## First Use

Use the [First-Use Checklist](FIRST-USE.md) when applying this template to a real project workspace.

Start with `product/DISCOVERY.md` and `product/ROADMAP.md` before creating the first executable ticket. The first task/ticket should come from a clear objective, first version slice, and visible postponed-decision list.

## Canonical Sources

- [Project Workspace Layout](../../design/project-workspace-layout.md)
- [Factory Manual Workflow](../../design/manual-workflow.md)
- [Factory Role Registry](../../agents/role-registry.md)
- [Factory Prompts](../../prompts/factory/README.md)
- [Factory Departments](../../agents/departments/README.md)
- [Factory Roles](../../agents/roles/README.md)

## Boundary

Reusable Factory definitions stay in the brain's `agents/` and `prompts/factory/` layers. This template is for project-local working copies, product code, and operating state.
