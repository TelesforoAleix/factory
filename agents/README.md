# Agents

Development-team agents, prompts, workflows, and skills for building the owner's ideas and projects.

Core brain OS customizations live in [../.github](../.github/README.md). Use `.github/` for repository-maintenance instructions, runnable brain OS skills, prompts, workflows, and future agents/hooks.

## Main Entry Points

- [Orchestrator](orchestrator/README.md): current orchestrator status and future agent boundary rules.
- [Skills](skills/README.md): reusable development-team workflow definitions for ideas, sessions, tasks, and project-building support.
- [Copilot Instructions](../.github/copilot-instructions.md): always-on workspace schema.
- [Brain OS Skills](../.github/skills/README.md): runnable repository-maintenance skills.

## Current Agent Files

No custom development-team agent files are active yet.

## Rule

Clarify existing skills before adding new agents. Add a new agent only when the workflow needs a separate role, persistent scope, or context isolation.

Do not put [project]-specific project truth or general brain OS behavior here by default. [project] project docs belong in [../03-projects/[project]](../03-projects/[project]/), and brain OS behavior belongs in [../.github](../.github/README.md).