# The Factory Progress

Live project-state file for The Factory.

## Current Phase

Architecture, operating model, and v0 scope definition.

## Current Status

The Factory has been activated as a project design space under `03-projects/ai-development-team/`.

The foundational direction is clear: build a reusable AI development company operating system for the owner's projects, with [project] as the first serious test. The next step is not dashboard implementation. The next step is to turn discovery into a clear architecture, roadmap, folder templates, and source comparison decisions.

## Locked Decisions

- Name: The Factory.
- The Factory is reusable across projects, not [project]-specific.
- [project] is the first serious test project.
- The Factory should replicate a company-like operating model as closely as useful.
- Canonical design/spec work belongs in `03-projects/ai-development-team/`.
- Reusable agents and skills belong in `04-agents/`.
- Project-specific operational output should live in each project workspace, not in the brain by default.
- Preferred project workspace folders: `.github/`, `agents/`, `product/`, `ops/`.
- Work hierarchy: Project -> Goal -> Feature -> Task -> Ticket.
- Ticket is the smallest assignable unit.
- Execution agents should not commit directly; commits go through a release agent.
- Important founder decisions should flow into a founder inbox with options and recommendations.
- Markdown should hold product/spec/design docs; YAML/JSON should hold operational state when useful.
- Start with architecture/spec documentation, then folder templates, then dashboard/control-plane implementation.
- For self-improvement, use Hermes Agent as the learning-intake and curation reference, and SkillOpt as the validation/promotion reference.

## Current Design Areas

- [Architecture](design/architecture.md)
- [Operating Model](design/operating-model.md)
- [Project Workspace Layout](design/project-workspace-layout.md)
- [Source Comparison Plan](design/source-comparison-plan.md)
- [Open Questions](design/open-questions.md)
- [Roadmap](roadmap.md)

## Next Recommended Moves

1. Review the initial architecture and operating-model docs with the owner.
2. Run a targeted source-comparison pass for the first implementable areas: control plane, workflow loop, agent/skill structure, review/release gates, and optimization.
3. Define the v0 learning-candidate lifecycle for Reflect: captured, candidate, validated, promoted, rejected, archived.
4. Define v0 folder templates for `agents/`, `product/`, and `ops/` in a project workspace.
5. Define the first ticket, context pack, founder inbox item, release gate, and learning-candidate schemas.
6. Decide dashboard v0 scope: read-only, write-capable ops state, or local CLI bridge.

## Related Docs

- [Spec](spec.md)
- [Roadmap](roadmap.md)
- [Design Docs](design/README.md)
- [AI Development Team Discovery](../../session-logs/2026-06-03-ai-development-team-discovery.md)
- [AI Development Team Blueprint](../../knowledge-base/ai-development/ai-development-team-blueprint.md)
- [Agent Control Plane Dashboard Patterns](../../knowledge-base/ai-development/agent-control-plane-dashboard-patterns.md)
- [Self-Improving Agent Learning Loops](../../knowledge-base/ai-development/self-improving-agent-learning-loops.md)

## Last Updated

2026-06-03