# The Factory Progress

Live project-state file for The Factory.

## Current Phase

First reusable agent/department specs.

## Current Status

The Factory has been activated as a project design space under `03-projects/ai-development-team/`.

The foundational direction is clear: build a reusable AI development company operating system for the owner's projects, with [project] as the first serious test. The v0 operating objects now have initial copyable templates under `03-projects/ai-development-team/templates/ops/`.

The Factory itself is now being developed inside `03-projects/ai-development-team/`. Its own live operating state starts in `03-projects/ai-development-team/ops/`, and the seeded internal-ops ticket has now been dogfooded through execution evidence, self-review, fresh-context review, validation/testing evidence, release readiness, and learning capture.

The manual Factory workflow now exists as the canonical v0 operating procedure before CLI or dashboard automation. The first reusable Factory department and role specs now exist in `04-agents/` as operating contracts, not runnable custom agents.

The role registry and V0 core department pack now make those specs scannable by role, department, type, permissions, boundaries, inputs, outputs, ticket powers, review/release authority, and advisory/execution status.

The Knowledge / Documentation department pack now defines the documentation, state, session, decision/ADR, docs-review, and learning-routing layer for Factory-managed work.

The Security / Privacy / Authority department pack now defines risk review, approval-level mapping, required reviewers, and stop conditions for security/privacy/authority-sensitive Factory work.

The Optimization department pack now defines learning intake, validation, promotion gates, rejected-change memory, and curation for Factory agents, skills, templates, and workflow improvements.

The next step is to review the registry and department packs with the owner, then decide whether to create the Founder Interface pack, prompt wrappers/custom agent files, or the project workspace template next.

## Locked Decisions

- Name: The Factory.
- The Factory is reusable across projects, not [project]-specific.
- [project] is the first serious test project.
- The Factory should replicate a company-like operating model as closely as useful.
- Canonical design/spec work belongs in `03-projects/ai-development-team/`.
- The Factory itself can be developed inside `03-projects/ai-development-team/` while it needs direct access to `04-agents/` and `knowledge-base/`.
- Reusable agents and skills belong in `04-agents/`.
- First reusable Factory role specs exist in `04-agents/roles/` and use the manual workflow as their shared operating contract.
- The Factory role registry and V0 core department pack live in `04-agents/` as coordination docs before runnable agents exist.
- The Knowledge / Documentation department pack lives in `04-agents/departments/` as the reusable documentation/state/decision/session/learning contract.
- The Security / Privacy / Authority department pack lives in `04-agents/departments/` as the reusable risk review and approval-routing contract.
- The Optimization department pack lives in `04-agents/departments/` as the reusable learning-intake, validation, promotion, and curation contract.
- Some agents should be advisory-only: they can read/synthesize knowledge and provide recommendations, but do not execute tickets or edit code.
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
- Initial v0 ops templates live under `03-projects/ai-development-team/templates/ops/` before being copied into any real project workspace.
- The Factory's own live operational state lives under `03-projects/ai-development-team/ops/` while The Factory is being built.
- Manual Factory operation is defined in `03-projects/ai-development-team/design/manual-workflow.md` and should be the shared operating contract for early agents.
- Recommended storage direction: YAML for most state objects, JSON or JSONL for run/session state and events, Markdown with YAML frontmatter for context packs and release checklists, and YAML for v0 review records.
- Start with architecture/spec documentation, then folder templates, then dashboard/control-plane implementation.
- For self-improvement, use Hermes Agent as the learning-intake and curation reference, and SkillOpt as the validation/promotion reference.

## Current Design Areas

- [Architecture](design/architecture.md)
- [Manual Workflow](design/manual-workflow.md)
- [Operating Model](design/operating-model.md)
- [Project Workspace Layout](design/project-workspace-layout.md)
- [Source Comparison Plan](design/source-comparison-plan.md)
- [Source Use Map](design/source-use-map.md)
- [V0 Operating Objects](design/v0-operating-objects.md)
- [Factory Ops](ops/README.md)
- [Templates](templates/README.md)
- [Open Questions](design/open-questions.md)
- [Roadmap](roadmap.md)

## Next Recommended Moves

1. Review the [Factory Role Registry](../../04-agents/role-registry.md), [Factory V0 Core Department Pack](../../04-agents/departments/factory-v0-core-pack.md), [Knowledge / Documentation Department Pack](../../04-agents/departments/factory-knowledge-documentation-pack.md), [Security / Privacy / Authority Department Pack](../../04-agents/departments/factory-security-privacy-authority-pack.md), [Optimization Department Pack](../../04-agents/departments/factory-optimization-pack.md), and first [Factory role specs](../../04-agents/roles/README.md) with the owner.
2. Use [Factory Ops](ops/README.md) to create the next ticket for Founder Interface pack, prompt wrappers/custom agent files, or the project workspace template.
3. Review the initial [Ops Templates](templates/ops/README.md) and tighten fields based on dogfooding.
4. Design the CLI/context-pack helper after the manual workflow is clear.
5. Decide dashboard v0 scope only after object templates, self-hosting ops, manual workflow, and first role specs are stable.

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