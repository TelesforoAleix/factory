# The Factory Open Questions

## V0 Scope

- What is the minimum architecture/spec bundle the owner wants before folder templates?
- Which source comparison area should happen first?
- Should v0 include only docs, or also first state templates?

## Operational State

- What exact schema should tickets use?
- Should state be YAML, JSON, or mixed?
- Should context packs be Markdown with frontmatter?
- Should run logs be JSON, Markdown, or both?

## Dashboard Bridge

- Should the first bridge be CLI-first?
- Should the dashboard write files directly, or call a local script/API?
- Can VS Code/Copilot be triggered cleanly from local HTML, or should the dashboard generate prompts/context packs first?
- Would a VS Code webview/extension be useful later?

## Department Taxonomy

- Which departments are mandatory for v0?
- Which specialist reviewers should exist on day one?
- Should market research be a default department or on-demand?
- Should context architecture be a department or a specialist role inside architecture?

## Release And CI/CD

- What branch model should project workspaces use?
- How often should the release agent commit?
- When should PRs be created?
- What tests/checks are required before a release agent can commit?
- Which release actions require founder approval?

## Self-Improvement

- What is the first agent or skill to optimize?
- What validation tasks should be created first?
- How should rejected improvements be stored?
- How does central optimization coordinate with department-owned improvement notes?

## Project Sync

- How should canonical `04-agents/` definitions sync into project workspaces?
- Should project overrides be allowed?
- How should updates from the brain propagate to active project workspaces without overwriting project-specific changes?

## Naming

- Project/system name is currently The Factory.
- Should internal folders use `factory`, `ops`, `ai-ops`, or another name?