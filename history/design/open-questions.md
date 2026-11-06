# The Factory Open Questions

## V0 Scope

- Are the current [Ops Templates](../templates/ops/README.md) complete enough for The Factory to dogfood its own operational workflow?
- Which Factory ticket should come next after the manual workflow: advisory-agent spec, project workspace template, or context-pack helper?
- Should the project workspace template wait until the internal Factory workflow has been tested once?
- Which source comparison area should happen next after the self-hosting pass?

## Operational State

Current v0 direction: YAML for tasks, tickets, inbox items, approvals, review records, and learning candidates; JSON or JSONL for run/session state and events; Markdown with YAML frontmatter for context packs and release checklists.

- What exact ID-generation rule should The Factory use for project-local objects?
- Should run/session history use one JSON state file in v0, or add JSONL event streams immediately?
- Should review records stay YAML, or shift back to Markdown with YAML frontmatter if review findings become narrative-heavy?
- Should context packs and release checklists share one common frontmatter schema?
- Which fields in [Manual Workflow](manual-workflow.md) are mandatory for all tickets versus optional for higher-risk work?
- How should archived project `ops/` objects be compacted after a task ships?

## Dashboard Bridge

- Should the first bridge be CLI-first?
- Should the dashboard write files directly, or call a local script/API?
- Can VS Code/Copilot be triggered cleanly from local HTML, or should the dashboard generate prompts/context packs first?
- Would a VS Code webview/extension be useful later?

## Department Taxonomy

- Which departments are mandatory for v0?
- Which specialist reviewers should exist on day one?
- What is the exact scope of the Marketing department beyond copy, tags, market research, launch materials, and public-facing phrasing?
- Should context architecture be a department or a specialist role inside architecture?
- Which roles should have advisory-only variants with read-only knowledge access?
- What permissions should advisory agents have when accessing the knowledge base and project docs?

## Release And CI/CD

- What branch model should project workspaces use?
- When should the release agent create ticket-level commits versus task-level batch commits?
- When should PRs be created?
- What tests/checks are required before a release agent can commit?
- Which release actions require founder approval?

## Self-Improvement

- What is the first agent or skill to optimize?
- What validation tasks should be created first?
- How should rejected improvements be stored?
- How does central optimization coordinate with department-owned improvement notes?
- Do project-specific learning candidates start in project `ops/` and promote to the shared knowledge layer only when reusable?

## Project Sync

- How should canonical `agents/` definitions sync into project workspaces?
- Should project overrides be allowed?
- How should updates from the Factory repository propagate to active project workspaces without overwriting project-specific changes?
- How should The Factory's internal `ops/` tickets trigger changes in canonical `agents/` assets without blurring ownership?

## Naming

- Project/system name is currently The Factory.
- Should internal folders use `factory`, `ops`, `ai-ops`, or another name?
