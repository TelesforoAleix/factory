# Agents

Development-team agents, prompts, workflows, and skills for building the owner's ideas and projects.


## Main Entry Points

- [Role Registry](role-registry.md): registry of Factory roles, departments, authority, boundaries, inputs, outputs, and ticket powers.
- [Departments](departments/README.md): reusable Factory department specs.
- [Roles](roles/README.md): reusable Factory role specs.
- [Orchestrator](orchestrator/README.md): current orchestrator status and future agent boundary rules.
- [Skills](skills/README.md): reusable development-team workflow definitions for ideas, sessions, tasks, and project-building support.

## Current Agent Files

No full custom development-team agent files are active yet.

The first thin Factory prompt wrappers are active under [Factory Prompts](../prompts/factory/README.md). They are prompt wrappers, not custom agents; canonical role and department truth remains in `agents/`.

The first reusable Factory department and role specs now exist under [Departments](departments/README.md) and [Roles](roles/README.md). These are operating contracts, not executable agents.

## Factory Design Link

[The Factory](../README.md) is the active project for designing the owner's reusable AI development company operating system.

Reusable agent and skill definitions live here in `agents/`; The Factory project holds the product, architecture, operating-model, manual workflow, and project-workspace design.

## Rule

Clarify existing skills before adding new agents. Add a new agent only when the workflow needs a separate role, persistent scope, or context isolation.

Do not put project-specific truth here. Project documentation and operational state belong in that project's own workspace.
