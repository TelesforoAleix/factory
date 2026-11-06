# The Factory Source Use Map

This map defines how The Factory should use each major reference source.

The goal is not to copy one repository. The goal is to use the best source for each layer, then adapt it to the owner's local-first, VS Code/Copilot, project-workspace model.

## Source Roles

| Source | Primary Use | Secondary Use | Do Not Copy Blindly |
|---|---|---|---|
| Paperclip | Control plane, dashboard, agent communication, task ownership, inbox, approvals, activity | Work hierarchy, run/session ledger, heartbeat concept | API-key-centric runtime, complex agent creation platform, full server/database model as v0 |
| ECC | Agent/skill/rule architecture, department breadth, cross-harness portability | Team-builder, security review, hooks/checklists, continuous learning ideas | Full catalog import, global context bloat, unreviewed hooks/MCPs |
| gstack | Workflow loop and proven skills: product office hours, engineering review, review, QA, ship, reflect | Safety modes, browser QA, cross-model review, memory/trust policy | Claude-specific commands, auto-commit intensity, browser daemon before needed |
| Hermes Agent | Experiential learning intake, memory/session/skill separation, background reflection, curator | Local session search, candidate skill patches, anti-bloat lifecycle | Auto-editing canonical skills, every-session skill creation, full runtime adoption |
| SkillOpt | Validation and promotion of improved skills/agents | Versioned snapshots, rejected-change memory, bounded edits | Heavy optimizer infrastructure before stable validation tasks |
| Claude Playbook | Rule/skill/agent/hook placement discipline, compact scaffold | Review/security/fix workflow shape | Claude-specific file layout as canonical |
| Anthropic Cybersecurity Skills | Security/privacy review anatomy and progressive loading | Risk tags, prerequisites, verification format | Large offensive/security catalog without scoped authorization |
| Prompt Master | Prompt wrapper anatomy, memory/context blocks, stop conditions | Prompt diagnostics | Long prompts for their own sake |
| Agent Reference Repositories | Practical skill ideas and agent curriculum coverage | Matt Pocock skill patterns, Microsoft agent curriculum, host architecture awareness | Treating reference catalogs as implementation-ready |

## Decision Topics

### 1. Control Plane And Work Objects

Dominant source: Paperclip.

Supporting sources: ECC for architecture boundaries, gstack for workflow stage artifacts.

Factory approach:

- Use Paperclip's dashboard/control-plane grammar.
- Keep Factory work objects file-backed first.
- Canonical hierarchy: Project -> Goal -> Feature -> Task -> Ticket.
- Tickets always belong to exactly one task.
- A task can have many tickets.
- Bugs, chores, or follow-ups should create tickets under an existing task, or a new task should be created when needed.

Why:

Paperclip solves visibility and communication better than the other sources, but its runtime is too heavy and too API-key/platform-centric for v0.

### 2. Team And Department Structure

Dominant source: ECC.

Supporting sources: gstack for product/engineering/review roles, Paperclip for org-chart thinking.

Factory approach:

- Define departments first, then agents inside departments.
- Use ECC's breadth as a role catalog, not a catalog to import fully.
- Add Marketing as a department for copy, positioning, marketing assets, website messaging, launch materials, and market research when relevant.
- Keep departments project-selectable; not every project activates every department.

Recommended v0 departments:

- Founder Interface
- Executive Orchestration
- Product
- Architecture / Context Architecture
- Engineering
- Review / QA
- Release / CI/CD
- Security / Privacy / Authority
- Knowledge / Documentation
- Optimization
- Marketing

### 3. Agent Types And Ownership

Dominant source: ECC.

Supporting source: Paperclip for reporting lines.

Factory approach:

- Owner/orchestrator agents can own features, tasks, or product areas.
- Execution agents implement tickets.
- Review agents validate with fresh context.
- Specialist agents are called only when relevant.
- Release agents own commit/PR readiness.

Open design point:

Feature owner and orchestrator may be the same agent in v0. Later, The Factory can split them if coordination becomes complex.

### 4. Agent Communication

Dominant source: Paperclip.

Supporting sources: ECC team-builder and gstack review routing.

Factory approach:

- Agents communicate through operational objects: tickets, comments, handoffs, review requests, inbox items, and approvals.
- Agent-to-agent messages do not always need three options.
- Agents should share insights, recommendations, risks, and next-action suggestions based on their expertise.
- The options plus recommendation rule is mandatory for important founder decisions and useful for high-impact agent-to-agent decisions.

### 5. Founder Inbox

Dominant source: Paperclip.

Factory approach:

- Founder inbox is an operational queue, shown in dashboard and surfaced by the personal assistant agent.
- If a ticket raises a founder question, the ticket is blocked until the owner answers.
- The owner answers through the personal assistant.
- The personal assistant records the decision and unblocks/routes the ticket.
- Important inbox items include up to three options, recommendation, context, and impact.

### 6. Sessions, Runs, And Heartbeats

Dominant source: Paperclip.

Supporting source: Hermes for session search and reflection.

Factory approach:

- Adapt Paperclip's heartbeat as a local run/session concept.
- A founder command like "what's next?" or "go" can let orchestrators pick ready tickets and start multiple parallel execution sessions when safe.
- The dashboard should show active runs, blocked runs, and review/release state.
- Sessions should produce run records and context for future search/reflection.

Open design point:

How automated parallelization can be in v0 depends on the bridge between dashboard, CLI, and VS Code/Copilot.

### 7. Context Packs

Dominant sources: ECC, Prompt Master, Paperclip.

Supporting sources: context-engineering notes and Hermes prompt/context separation.

Factory approach:

- Use a machine-friendly format, but keep human readability.
- Recommended v0: JSON or YAML metadata plus Markdown body.
- Execution packs and review packs can share schema but differ by purpose.
- The goal is lightweight context for LLMs, not giant project dumps.

Open design point:

Decide whether JSON or YAML is better for v0 agent/dashboard tooling. Markdown with frontmatter may be the best compromise.

### 8. Workflow Lifecycle

Dominant source: gstack.

Supporting sources: Paperclip task state and Claude Playbook compact lifecycle discipline.

Factory approach:

- Keep Think -> Plan -> Build -> Review -> Test -> Release -> Reflect as the macro-loop.
- Ticket lifecycle should include both self-review and external review.

Recommended ticket lifecycle:

```text
inbox -> discovery -> ready -> assigned -> in_progress -> self_review -> external_review -> testing -> revision -> release_ready -> shipped -> archived
blocked
```

Notes:

- self_review: execution agent reflects on its own result before handing off.
- external_review: fresh-context reviewer checks against intent.
- testing: checks that it works; can be performed by QA/test agents or specialized reviewers.
- revision can route back to execution after self-review, external review, or testing.

### 9. Review And Specialist Routing

Dominant sources: gstack and Cybersecurity Skills.

Supporting sources: ECC role catalog and Paperclip approvals.

Factory approach:

- Every ticket declares required reviewers.
- The orchestrator or feature owner can also infer missing reviewers.
- Specialist reviewers join when relevant: security, privacy/GDPR, UX/UI, data, architecture, context, performance, marketing/copy.

Why:

Ticket-declared reviewers make routing explicit. Orchestrator inference prevents omissions.

### 10. Release And CI/CD

Dominant source: gstack.

Supporting sources: Claude Playbook review/PR discipline and Paperclip approval state.

Factory approach:

- Execution agents do not commit.
- Release agent commits or prepares PRs after validation.
- Tickets can be batched into a task-level commit when coherent.
- A task may produce one commit containing multiple tickets.
- Release agent decides whether ticket-level or task-level commits are cleaner based on scope and review state.

Open design point:

Define exact branch/commit/PR rules in a release-flow pass.

### 11. Self-Improvement

Dominant sources: Hermes Agent and SkillOpt.

Supporting source: ECC continuous learning.

Factory approach:

- Use Hermes for experiential capture: what happened, what failed, what should be remembered, what skill might need a patch.
- Use SkillOpt for validation and promotion: score representative tasks, compare versions, promote only if better.
- Each department keeps improvement notes.
- Central Optimization Department validates and promotes canonical changes.

Open design point:

Where project-specific learning candidates live before promotion. Candidate lessons may start in project `ops/`, then promote to the shared knowledge layer if reusable across projects.

### 12. Dashboard And Bridge

Dominant source: Paperclip.

Supporting sources: Odysseus for workspace/control-plane inspiration, gstack for browser/QA tooling.

Factory approach:

- Dashboard is local-first.
- It should support founder inbox, task/ticket board, agent roster, runs, approvals, and release state.
- It should route work to VS Code/Copilot or CLI instead of replacing the execution environment.
- Start with file-backed state and CLI/generated context packs before deeper editor integration.

## Recommended Source-Use Order

1. Control plane and ticketing: Paperclip + ECC + gstack.
2. Workflow lifecycle: gstack + Paperclip + Claude Playbook.
3. Department/agent taxonomy: ECC + gstack + Paperclip + Agent Reference Repos.
4. Context packs: Prompt Master + ECC + Paperclip + context-engineering notes.
5. Review/release gates: gstack + Claude Playbook + Cybersecurity Skills.
6. Self-improvement: Hermes + SkillOpt + ECC.
7. Dashboard bridge: Paperclip + Odysseus + local project constraints.

## Immediate Recommendation

Next design pass should produce the first v0 state schemas for:

- task
- ticket
- run
- founder inbox item
- approval
- context pack
- review record
- release checklist
- learning candidate

The schema pass should use this source map as the decision guide.
