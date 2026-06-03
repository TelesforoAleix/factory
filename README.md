# The Factory

Reusable AI development company operating system for the owner's projects.

The Factory is the design home for the agentic development team: product, architecture, engineering, review, release, documentation, security, context, and optimization roles working through a visible operating system.

It is not [project]-specific. [project] is the first serious test project, but The Factory should be reusable for future tools, products, demos, and client/project work.

## Entry Points

- [Spec](spec.md)
- [Progress](progress.md)
- [Roadmap](roadmap.md)
- [Design Docs](design/README.md)
- [Templates](templates/README.md)

## Layer Boundary

- This folder holds the product/architecture/spec work for The Factory.
- Reusable agent and skill definitions belong in [04-agents](../../04-agents/README.md).
- Project-specific operational state should live inside each project workspace, not in this brain by default.

## Related Knowledge

- [AI Development Team Blueprint](../../knowledge-base/ai-development/ai-development-team-blueprint.md)
- [Agent Control Plane Dashboard Patterns](../../knowledge-base/ai-development/agent-control-plane-dashboard-patterns.md)
- [Self-Improving Agent Learning Loops](../../knowledge-base/ai-development/self-improving-agent-learning-loops.md)
- [AI Development Team Source Extraction Matrix](../../knowledge-base/ai-development/ai-development-team-source-extraction-matrix.md)
- [Development Team Sprint Workflow](../../knowledge-base/methods/development-team-sprint-workflow.md)
- [Skill Improvement Loop](../../knowledge-base/methods/skill-improvement-loop.md)

## Current Status

Active design/spec phase. The first `ops/` templates now exist; the next work is the project workspace template before agent specs, manual workflow, CLI helpers, or dashboard prototypes.