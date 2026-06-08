# The Factory

Reusable AI development company operating system for the owner's projects.

The Factory is the design home for the agentic development team: product, architecture, engineering, review, release, documentation, security, context, and optimization roles working through a visible operating system.

It is not [project]-specific. [project] is the first serious test project, but The Factory should be reusable for future tools, products, demos, and client/project work.

## Entry Points

- [Spec](spec.md)
- [Progress](progress.md)
- [Roadmap](roadmap.md)
- [Management Dashboard](dashboard/index.html)
- [Factory Ops](ops/README.md)
- [Design Docs](design/README.md)
- [Templates](templates/README.md)

## Layer Boundary

- This folder holds the product/architecture/spec work for The Factory.
- This folder is also the live build home for The Factory itself while the system needs direct access to the brain's knowledge and reusable agent layers.
- The Factory's own operational state lives in [ops](ops/README.md).
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

Active self-hosting/spec phase. The first `ops/` templates exist, The Factory has its own live [ops](ops/README.md) layer, and a browser-side [management dashboard](dashboard/index.html) now loads local ops records for mission control, stage board, role roster, run ledger, release lane, context panel, decisions, approvals, and learning before CLI or writable dashboard automation.