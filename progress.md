---
type: project
created: 2026-06-03
updated: 2026-06-08
---
# The Factory Progress

Live project-state file for The Factory.

## Current Phase

Management dashboard visibility plus project workspace template dogfood.

## Current Status

The Factory has been activated as a project design space under `03-projects/ai-development-team/`.

The foundational direction is clear: build a reusable AI development company operating system for the owner's projects, with [project] as the first serious test. The v0 operating objects now have initial copyable templates under `03-projects/ai-development-team/templates/ops/`.

The Factory itself is now being developed inside `03-projects/ai-development-team/`. Its own live operating state starts in `03-projects/ai-development-team/ops/`, and the seeded internal-ops ticket has now been dogfooded through execution evidence, self-review, fresh-context review, validation/testing evidence, release readiness, and learning capture.

The manual Factory workflow now exists as the canonical v0 operating procedure before CLI or dashboard automation. The first reusable Factory department and role specs now exist in `04-agents/` as operating contracts, not runnable custom agents.

The role registry and V0 core department pack now make those specs scannable by role, department, type, permissions, boundaries, inputs, outputs, ticket powers, review/release authority, and advisory/execution status.

The registry has now been operationalized as the role-layer source of truth across the full department-pack system. It distinguishes core v0 roles, department expansion roles, advisory-only roles, specialist/gate roles, and future runnable prompt-wrapper candidates; it also indexes every department pack and selects the first prompt-wrapper set.

The Knowledge / Documentation department pack now defines the documentation, state, session, decision/ADR, docs-review, and learning-routing layer for Factory-managed work.

The Security / Privacy / Authority department pack now defines risk review, approval-level mapping, required reviewers, and stop conditions for security/privacy/authority-sensitive Factory work.

The Optimization department pack now defines learning intake, validation, promotion gates, rejected-change memory, and curation for Factory agents, skills, templates, and workflow improvements.

The Architecture / Context Architecture department pack now defines system architecture, context architecture, tradeoff review, advisory-only knowledge synthesis, and ADR review for Factory-managed work.

The Marketing department pack now defines positioning, copy, launch materials, tags, market research, and marketing review for Factory-managed work.

The Founder Interface / Personal Assistant department pack now defines founder inbox management, decision interviews, status briefings, answer capture, and routing decisions back to blocked tickets.

The Product department expansion pack now defines idea intake, requirements analysis, PRD writing, feature/task/ticket shaping, acceptance criteria review, and product drift review.

The Engineering department expansion pack now defines scoped implementation, refactoring, integration, debugging, engineering handoff, and context-pack-driven execution without direct execution-agent commits.

The Review / QA department expansion pack now defines fresh-context review, test planning, regression testing, UX/UI review routing, revision request review, and explicit separation between review and testing stages.

The Release / CI-CD department expansion pack now defines release readiness, branch/commit/PR rules, batching rules, CI/CD monitoring, release notes coordination, and escalation paths.

The first thin prompt wrappers now exist under `.github/prompts/factory/` for Executive Orchestrator, Product / Feature Owner, Execution Agent, Review / QA Agent, Release Agent, Advisory Architect, and Founder Interface / Personal Assistant. Founder Interface now also has a compact individual role-spec bridge in `04-agents/roles/`.

The first real Factory self-build ticket after prompt-wrapper creation is complete: `TICKET-2026-0014` created the v0 project workspace template under `03-projects/ai-development-team/templates/project-workspace/` with tracked `.github/`, `agents/`, `product/`, and `ops/` folders.

The reusable ops templates were compared against the latest live dogfood records and still match at the top-level schema. No conservative field cleanup was needed yet.

The project workspace template now has a first-use checklist for applying it to a real project without mixing branch rules, canonical Factory assets, project-local ops, or product implementation files.

The new-project discovery phase is now explicit. Before the first executable ticket in a Factory-managed project, Product should produce or update a discovery brief, roadmap/version plan, first version slice, postponed-decision list, and role/skill routing recommendation. The project workspace template now includes `product/DISCOVERY.md` and `product/ROADMAP.md` for this first pass.

The local dashboard now exists at `03-projects/ai-development-team/dashboard/index.html` as a browser-side read-only management surface. It loads the selected Factory project or `ops/` folder directly in the browser and shows mission control, stage board, role roster, run ledger, release lane, context panel, decision queue, approvals, and learning records without requiring regenerated HTML, a server, CLI bridge, database, or writable control plane.

The Paperclip-style management-interface plan now exists in `design/paperclip-style-management-interface.md`. It splits the next dashboard/interface work into read-only drill-down, communication/decision cards, data-contract tightening, CLI bridge, writable control plane, and real project rollout.

The first read-only drill-down slice is now implemented. The dashboard builds an in-memory relationship index, adds a Task Explorer, and adds a Selected Work panel where the owner can inspect a task, see associated tickets, click a ticket, see runs/reviews/release evidence, changed files/tests, and understand stage plus next owner/action.

The communication-card slice is now implemented. The dashboard derives communication events from runs, reviews, releases, founder inbox items, approvals, learning records, and optional interactions; it renders a global Communication Feed plus ticket-level Communication Timeline cards.

The search/filter slice is now implemented. The dashboard can filter loaded tickets by text search, status, owner, risk level, and blocked-only state, and the filtered view updates metrics, stage board, task explorer, role roster, run ledger, and communication feed.

The interaction schema slice is now implemented. Interactions are now a first-class Factory ops object for lightweight agent-to-agent or agent-to-founder-interface communication cards, with reusable template, live `ops/interactions/` folder, workspace-template placeholder, and a sample `INTERACTION-2026-0001` record.

The next step is to load the full Factory `ops/` folder in the dashboard and inspect how the sample interaction appears alongside derived run/review/release communication cards. After that, decide whether the next slice should be saved views, interaction write/routing behavior, or real-project rollout. Dashboard and template changes should come from real setup and visibility friction.

## Locked Decisions

- Name: The Factory.
- The Factory is reusable across projects, not [project]-specific.
- [project] is the first serious test project.
- The Factory should replicate a company-like operating model as closely as useful.
- Canonical design/spec work belongs in `03-projects/ai-development-team/`.
- The Factory itself can be developed inside `03-projects/ai-development-team/` while it needs direct access to `04-agents/` and `knowledge-base/`.
- Reusable agents and skills belong in `04-agents/`.
- First reusable Factory role specs exist in `04-agents/roles/` and use the manual workflow as their shared operating contract.
- The Factory role registry and V0 core department pack live in `04-agents/` as coordination docs and prompt-wrapper source contracts before full custom agents exist.
- The Factory role registry now reflects all department packs, not only the original six core roles.
- Department expansion roles decompose or support core v0 roles when activation triggers apply; they are not runnable by default.
- First runnable prompt wrappers should be thin `.prompt.md` wrappers under the repo's GitHub prompt layer, with `04-agents/` remaining the source of truth.
- Founder Interface / Personal Assistant now has an individual role-spec bridge because it is part of the first wrapper set.
- The first Factory prompt wrappers live under `.github/prompts/factory/` and are thin wrappers over the canonical role specs and department packs.
- The Knowledge / Documentation department pack lives in `04-agents/departments/` as the reusable documentation/state/decision/session/learning contract.
- The Security / Privacy / Authority department pack lives in `04-agents/departments/` as the reusable risk review and approval-routing contract.
- The Optimization department pack lives in `04-agents/departments/` as the reusable learning-intake, validation, promotion, and curation contract.
- The Architecture / Context Architecture department pack lives in `04-agents/departments/` as the reusable system/context architecture, tradeoff, advisory, and ADR-review contract.
- The Marketing department pack lives in `04-agents/departments/` as the reusable positioning/copy/launch/tags/market-research contract.
- The Founder Interface / Personal Assistant department pack lives in `04-agents/departments/` as the reusable founder inbox, decision interview, status briefing, and decision-routing contract.
- The Product department expansion pack lives in `04-agents/departments/` as the reusable rough-idea-to-work-hierarchy and acceptance-criteria contract.
- The Engineering department expansion pack lives in `04-agents/departments/` as the reusable context-pack execution, implementation, refactor, integration, debugging, and handoff contract.
- The Review / QA department expansion pack lives in `04-agents/departments/` as the reusable fresh-context review, test planning, regression, UX/UI routing, revision review, and review/test separation contract.
- The Release / CI-CD department expansion pack lives in `04-agents/departments/` as the reusable release-readiness, branch/commit/PR, batching, CI/CD monitoring, release notes, and escalation contract.
- Some agents should be advisory-only: they can read/synthesize knowledge and provide recommendations, but do not execute tickets or edit code.
- Project-specific operational output should live in each project workspace, not in the brain by default.
- Preferred project workspace folders: `.github/`, `agents/`, `product/`, `ops/`.
- The copyable project workspace template lives under `03-projects/ai-development-team/templates/project-workspace/`.
- The project workspace first-use checklist lives under `03-projects/ai-development-team/templates/project-workspace/FIRST-USE.md`.
- Every new Factory-managed project should run project discovery before the first executable ticket.
- The new-project discovery pass should capture objectives, product shape, first version scope, later-version candidates, and visible postponed decisions.
- The project workspace template includes `product/DISCOVERY.md` and `product/ROADMAP.md` as the default discovery and version-planning artifacts.
- Factory Project Discovery lives in `04-agents/skills/` as reusable teammate expertise for kickoff work, not as a full custom agent.
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
- A read-only browser-side management dashboard can exist before the CLI bridge or writable control plane, as long as it reads file-backed ops state and does not become a second source of truth.
- Browser folder selection is the current local-file permission boundary for direct dashboard data loading.
- Start with architecture/spec documentation and folder templates, then read-only management dashboard visibility, then CLI/context-pack helper and writable dashboard/control-plane implementation.
- For self-improvement, use Hermes Agent as the learning-intake and curation reference, and SkillOpt as the validation/promotion reference.

## Current Design Areas

- [Architecture](design/architecture.md)
- [Manual Workflow](design/manual-workflow.md)
- [Operating Model](design/operating-model.md)
- [Project Workspace Layout](design/project-workspace-layout.md)
- [Paperclip-Style Management Interface](design/paperclip-style-management-interface.md)
- [Source Comparison Plan](design/source-comparison-plan.md)
- [Source Use Map](design/source-use-map.md)
- [V0 Operating Objects](design/v0-operating-objects.md)
- [Factory Ops](ops/README.md)
- [Management Dashboard](dashboard/index.html)
- [Templates](templates/README.md)
- [Open Questions](design/open-questions.md)
- [Roadmap](roadmap.md)

## Next Recommended Moves

1. Open the [Management Dashboard](dashboard/index.html), load the full Factory `ops/` folder, and inspect search/filtering, task/ticket drill-down, communication cards, and the sample interaction record with real data.
2. Decide whether the next interface slice is saved dashboard views, interaction write/routing behavior, or real-project rollout.
3. Use [Factory Project Discovery](../../04-agents/skills/factory-project-discovery.md) and the [Project Workspace First-Use Checklist](templates/project-workspace/FIRST-USE.md) when applying the template to the first future Factory-managed project workspace.
4. Capture template and dashboard visibility friction as learning candidates before changing canonical templates.
5. Delay CLI/context-pack helper or writable dashboard control-plane work until the read-only interface proves what writes are actually needed.

## Related Docs

- [Spec](spec.md)
- [Management Dashboard](dashboard/index.html)
- [Roadmap](roadmap.md)
- [Design Docs](design/README.md)
- [AI Development Team Discovery](../../session-logs/2026-06-03-ai-development-team-discovery.md)
- [AI Development Team Blueprint](../../knowledge-base/ai-development/ai-development-team-blueprint.md)
- [Agent Control Plane Dashboard Patterns](../../knowledge-base/ai-development/agent-control-plane-dashboard-patterns.md)
- [Self-Improving Agent Learning Loops](../../knowledge-base/ai-development/self-improving-agent-learning-loops.md)

## Last Updated

2026-06-08