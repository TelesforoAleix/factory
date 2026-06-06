# The Factory Roadmap

## Principle

Keep the plan visible so implementation does not drift.

The Factory should move from design to templates to local control plane gradually. Do not build the dashboard before the operating model and state objects are clear.

## V0 - Architecture And Specs

Goal: preserve intent and decide the operating model.

Includes:

- project spec and roadmap
- operating-model docs
- department/role taxonomy
- Project -> Goal -> Feature -> Task -> Ticket model
- folder layout for project workspaces
- source comparison plan
- first open questions and approval thresholds
- first v0 operating-object schemas and `ops/` templates

Exit criteria:

- the owner approves the operating model.
- First v0 operating-object templates are clear enough to copy into a project workspace template.
- First schemas for task, ticket, context pack, inbox item, run, approval, review, release, and learning candidate are ready to refine through use.

## V1 - Project Workspace Templates

Goal: make The Factory installable/syncable into a project workspace without dashboard automation.

Includes:

- `.github/` project instructions template
- `agents/` synced agent/skill template
- `product/` discovery brief, roadmap/version plan, and placeholder convention
- `ops/` structure for tickets, runs, inbox, approvals, dashboard state, and archives
- markdown/YAML/JSON templates for core operational objects
- manual workflow instructions for using The Factory through VS Code/Copilot

Exit criteria:

- A new project can copy/sync the template and run a manual Factory workflow.
- A new project starts with objectives, first version scope, and postponed decisions captured before the first executable ticket.
- A ticket can be created, assigned, executed, reviewed, released, and archived manually.

## V2 - CLI Bridge And Context Packs

Goal: reduce friction between ops state and VS Code/Copilot or CLI execution.

Includes:

- local CLI commands to create/read/update tickets and inbox items
- context-pack generation for execution and review agents
- run/session logging helpers
- release-agent checklist helpers
- git status and branch awareness

Exit criteria:

- the owner can start a role/ticket from local state and get a usable context pack.
- Execution and review results can be written back into ops state.

## V3 - Local Dashboard Control Plane

Goal: give the owner a local HTML dashboard for The Factory.

Includes:

- project overview
- work hierarchy browser
- task/ticket board
- agent roster/org chart
- founder inbox
- run/session ledger
- approvals
- release readiness
- improvement queue

Exit criteria:

- the owner can use the dashboard as the main operational surface while agents execute through VS Code/Copilot or CLI.

## V4 - Self-Improvement And Automation

Goal: make agents and skills improve from evidence.

Includes:

- department-level improvement notes
- central optimization department
- validation tasks and scoring rubrics
- versioned agent/skill snapshots
- promotion gates
- rejected-change memory
- recurring maintenance routines

Exit criteria:

- At least one agent or skill improves through a validated update cycle.
- The system captures failures and improves without bloating canonical instructions.

## Later

- scheduled/background agent runs
- richer local database if JSON/YAML state becomes painful
- VS Code extension or deeper editor integration
- project marketplace/templates
- cross-model review gates
- stronger security/privacy/compliance automation