# The Factory Progress

Live project-state file for The Factory.

## Current Phase

Architecture, operating model, and v0 scope definition.

## Current Status

The Factory has been activated as a project design space under `03-projects/ai-development-team/`.

The foundational direction is clear: build a reusable AI development company operating system for the owner's projects, with [project] as the first serious test. The current pass defines the v0 operating objects that will later become project-workspace templates and dashboard-readable state.

The next step is still not dashboard implementation. The next step is to review the v0 operating objects, turn them into lightweight `ops/` templates, and keep source comparison tied to concrete components.

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
- Tickets always belong to exactly one task; tasks can contain many tickets.
- Execution agents should not commit directly; commits go through a release agent.
- Important founder decisions should flow into a founder inbox with options and recommendations.
- Founder inbox items block their related ticket until the owner answers through the personal assistant and the decision is routed back.
- Every ticket should declare required reviewers when known.
- Ticket lifecycle includes execution self-review, external fresh-context review, and testing before release readiness.
- Marketing is a Factory department for market-facing copy, tags, positioning, launch materials, and market research when relevant.
- Markdown should hold product/spec/design docs; YAML/JSON should hold operational state when useful.
- V0 operating objects are task, ticket, run/session, founder inbox item, approval, context pack, review record, release checklist, and learning candidate.
- Recommended storage direction: YAML for most state objects, JSON or JSONL for run/session state and events, and Markdown with YAML frontmatter for context packs, reviews, and release checklists.
- Start with architecture/spec documentation, then folder templates, then dashboard/control-plane implementation.
- For self-improvement, use Hermes Agent as the learning-intake and curation reference, and SkillOpt as the validation/promotion reference.

## Current Design Areas

- [Architecture](design/architecture.md)
- [Operating Model](design/operating-model.md)
- [Project Workspace Layout](design/project-workspace-layout.md)
- [Source Comparison Plan](design/source-comparison-plan.md)
- [Source Use Map](design/source-use-map.md)
- [V0 Operating Objects](design/v0-operating-objects.md)
- [Open Questions](design/open-questions.md)
- [Roadmap](roadmap.md)

## Next Recommended Moves

1. Review [V0 Operating Objects](design/v0-operating-objects.md) with the owner and tighten field names, statuses, and storage choices.
2. Turn the v0 operating objects into lightweight project-workspace templates under the future `ops/` structure.
3. Define v0 folder templates for `.github/`, `agents/`, `product/`, and `ops/` in a project workspace.
4. Use the source-use map to run targeted comparison only when a Factory component is being designed.
5. Decide dashboard v0 scope after the operating objects and templates are stable: read-only, write-capable ops state, or local CLI bridge.

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