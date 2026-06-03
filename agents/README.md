# Agents

Development-team agents, prompts, workflows, and skills for building the owner's ideas and projects.

Core brain OS customizations live in [../.github](../.github/README.md). Use `.github/` for repository-maintenance instructions, runnable brain OS skills, prompts, workflows, and future agents/hooks.

## Main Entry Points

- [Role Registry](role-registry.md): registry of Factory roles, departments, authority, boundaries, inputs, outputs, and ticket powers.
- [Departments](departments/README.md): reusable Factory department specs.
- [Roles](roles/README.md): reusable Factory role specs.
- [Orchestrator](orchestrator/README.md): current orchestrator status and future agent boundary rules.
- [Skills](skills/README.md): reusable development-team workflow definitions for ideas, sessions, tasks, and project-building support.
- [Copilot Instructions](../.github/copilot-instructions.md): always-on workspace schema.
- [Brain OS Skills](../.github/skills/README.md): runnable repository-maintenance skills.

## Current Agent Files

No runnable custom development-team agent files are active yet.

The first reusable Factory department and role specs now exist under [Departments](departments/README.md) and [Roles](roles/README.md). These are operating contracts, not executable agents.

## Factory Design Link

[The Factory](../03-projects/ai-development-team/README.md) is the active project for designing the owner's reusable AI development company operating system.

Reusable agent and skill definitions live here in `04-agents/`; The Factory project holds the product, architecture, operating-model, manual workflow, and project-workspace design.

## Rule

Clarify existing skills before adding new agents. Add a new agent only when the workflow needs a separate role, persistent scope, or context isolation.

Do not put [project]-specific project truth or general brain OS behavior here by default. [project] project docs belong in [../03-projects/[project]](../03-projects/[project]/), and brain OS behavior belongs in [../.github](../.github/README.md).