# Factory Role Registry

Status: v0 operationalization registry

This registry is the source-of-truth map for Factory roles, department packs, authority boundaries, and runnable-wrapper sequencing.

It coordinates individual role specs, department packs, and future prompt wrappers. A role appearing here does not automatically make it a runnable custom agent.

## Operating Contract

All roles in this registry use:

- [The Factory Manual Workflow](../03-projects/ai-development-team/design/manual-workflow.md)
- [The Factory Operating Model](../03-projects/ai-development-team/design/operating-model.md)
- [Factory V0 Core Department](departments/factory-v0-core.md)

## Role Status Taxonomy

| Status | Meaning | Default Runnable State |
|---|---|---|
| Core v0 role | Part of the smallest operating loop and backed by an individual role spec | Candidate for first prompt wrappers |
| Department expansion role | Specialist or decomposition role defined inside a department pack | Not runnable by default |
| Advisory-only role | Reads, synthesizes, recommends, or routes without mutating code, docs, ops state, or release state by default | Prompt wrapper allowed only when read-only scope is clear |
| Specialist / gate role | Review, risk, release, quality, or promotion gate role activated by trigger | Not runnable until repeated manual use proves the prompt shape |
| Future runnable wrapper | Role selected for a thin `.prompt.md` wrapper before any full custom agent exists | Wrapper candidate, not autonomous agent |

Expansion roles decompose or support core roles when a ticket's complexity, frequency, risk, or domain requires them. They do not automatically run beside the core loop.

## Registry Table

| Role | Department | Role Type | Advisory / Execution Status | Ticket Powers | Review / Release Authority | Spec |
|---|---|---|---|---|---|---|
| Executive Orchestrator | Executive Orchestration | Coordinator / manager | Coordination role; may execute only when explicitly assigned a docs/ops ticket | Create, shape, route, assign, block, and sequence tickets | Can require review and release; cannot approve own execution or release | [Executive Orchestrator](roles/executive-orchestrator.md) |
| Product / Feature Owner | Product | Product owner / feature manager | Product-intent role; executes only product/docs tickets when assigned | Create and refine goals, features, tasks, tickets, scope, and acceptance criteria | Can judge product intent; cannot replace Review / QA or Release Agent | [Product / Feature Owner](roles/product-feature-owner.md) |
| Execution Agent | Engineering | Execution worker | Execution role | Work assigned ticket, update run evidence, create help/follow-up tickets | Owns self-review only; cannot approve external review, release, or commit | [Execution Agent](roles/execution-agent.md) |
| Review / QA Agent | Review / QA | Fresh-context reviewer / QA | Review role | Request revision, recommend follow-up tickets, route specialist review | Can pass/fail fresh-context review; cannot commit or release | [Review / QA Agent](roles/review-qa-agent.md) |
| Release Agent | Release / CI/CD | Release gatekeeper | Release role | Set release-readiness state, create release checklist, request revision or escalation | Owns release readiness and commit/PR scope; does not replace review | [Release Agent](roles/release-agent.md) |
| Advisory Architect | Architecture / Context | Advisory specialist | Advisory-only by default; read-only unless separately assigned an execution ticket | Recommend tickets, blockers, reviews, or options; should not update ticket state by default | Can provide specialist architecture/context advice; cannot approve release | [Advisory Architect](roles/advisory-architect.md) |

These six roles are the core v0 loop. Department packs below add specialist contracts around the loop without making every specialist an immediate wrapper or custom agent.

## Department Pack Index

| Department Pack | Roles Covered | Relationship To Core Loop | Activation Stage | Runnable Status |
|---|---|---|---|---|
| [Factory V0 Core Department Pack](departments/factory-v0-core-pack.md) | Executive Orchestrator; Product / Feature Owner; Execution Agent; Review / QA Agent; Release Agent; Advisory Architect | Defines the minimum v0 loop | Always available for Factory tickets | First wrapper source |
| [Factory Product Department Expansion Pack](departments/factory-product-expansion-pack.md) | Product Lead; Feature Owner; Requirements Analyst; PRD Writer; Acceptance Criteria Reviewer; Product Drift Reviewer | Decomposes Product / Feature Owner when product shaping needs specialists | Activate for rough ideas, hierarchy shaping, PRDs, criteria, or drift | Expansion roles, not runnable by default |
| [Factory Engineering Department Expansion Pack](departments/factory-engineering-expansion-pack.md) | Engineering Lead; Implementation Agent; Refactor Agent; Integration Agent; Debugging Agent; Engineering Handoff Agent | Decomposes Execution Agent when implementation work needs specialist execution or handoff | Activate for scoped implementation, refactor, integration, debugging, or engineering handoff | Expansion roles, not runnable by default |
| [Factory Review / QA Department Expansion Pack](departments/factory-review-qa-expansion-pack.md) | Review / QA Lead; Fresh-Context Reviewer; Test Planner; Regression Tester; UX/UI Review Router; Revision Request Reviewer | Decomposes Review / QA Agent when review/test/routing depth increases | Activate after execution self-review or when test, UX, revision, or specialist routing is needed | Expansion/gate roles, not runnable by default |
| [Factory Release / CI-CD Department Expansion Pack](departments/factory-release-cicd-expansion-pack.md) | Release Lead; Commit Readiness Reviewer; PR Manager; CI/CD Monitor; Release Notes Coordinator; Release Gatekeeper | Decomposes Release Agent when release, commit, PR, CI, or batching depth increases | Activate when work approaches commit, PR, merge, release notes, or release checklist | Expansion/gate roles, not runnable by default |
| [Factory Architecture / Context Architecture Department Pack](departments/factory-architecture-context-pack.md) | Architecture Lead; System Architect; Context Architect; Technical Tradeoff Reviewer; Architecture Advisory Agent; Architecture Decision / ADR Reviewer | Supports Advisory Architect and adds architecture review/decomposition roles | Activate for architecture, context, ADR, workspace, retrieval, memory, integration, or tradeoff decisions | Advisory/specialist roles, not runnable by default |
| [Factory Security / Privacy / Authority Department Pack](departments/factory-security-privacy-authority-pack.md) | Security / Privacy Lead; Application Security Reviewer; Agent Infrastructure Security Reviewer; Privacy / GDPR Reviewer; Authority / Permission Reviewer; Risk Gatekeeper | Adds specialist risk gates that Review / QA and Release must respect when triggered | Activate for credentials, auth, permissions, external services, personal data, privacy, authority, destructive actions, or privileged automation | Specialist/gate roles, not runnable by default |
| [Factory Knowledge / Documentation Department Pack](departments/factory-knowledge-documentation-pack.md) | Knowledge / Documentation Lead; Session Archivist; Project State Maintainer; Decision / ADR Archivist; Docs Reviewer; Learning Candidate Router | Preserves session, state, docs, decision, and learning continuity around the loop | Activate when work changes durable docs/state/decisions or creates reusable learning | Expansion/support roles, not runnable by default |
| [Factory Marketing Department Pack](departments/factory-marketing-pack.md) | Marketing Lead; Positioning Strategist; Copywriter; Market Researcher; Launch Materials Reviewer; Marketing Advisory Agent | Translates product truth into market-facing language when public copy or launch material exists | Activate for positioning, launch, tags, market research, public claims, or market-facing copy | Expansion/advisory roles, not runnable by default |
| [Factory Optimization Department Pack](departments/factory-optimization-pack.md) | Optimization Lead; Learning Intake Curator; Skill / Agent Evaluator; Skill / Agent Editor; Promotion Gatekeeper; Learning Library Curator | Validates and promotes reusable improvements after evidence exists | Activate for repeated failures, learning candidates, prompt/skill/agent/template changes, or promotion decisions | Specialist/gate roles, not runnable by default |
| [Factory Founder Interface / Personal Assistant Department Pack](departments/factory-founder-interface-pack.md) | Founder Interface Lead; Personal Assistant Agent; Founder Inbox Manager; Decision Interviewer; Status Briefing Agent; Decision Router | Handles founder questions, decision capture, status briefings, and answer routing back into blocked tickets | Activate when the owner must decide, clarify, approve, or receive a status briefing | First wrapper source; role-spec bridge exists |

## First Runnable Wrapper Selection

The first runnable layer should be thin prompt wrappers, not full custom agents. The selected v0 wrapper set is:

| Wrapper Candidate | Source Contract | Why First | Precondition |
|---|---|---|---|
| Executive Orchestrator | [Executive Orchestrator](roles/executive-orchestrator.md) | Chooses next work, routes tickets, and keeps the loop coherent | Existing role spec is enough |
| Product / Feature Owner | [Product / Feature Owner](roles/product-feature-owner.md) | Turns rough intent into goals, features, tickets, and acceptance criteria | Existing role spec is enough |
| Execution Agent | [Execution Agent](roles/execution-agent.md) | Performs scoped ticket work without committing directly | Existing role spec is enough |
| Review / QA Agent | [Review / QA Agent](roles/review-qa-agent.md) | Performs fresh-context review before release | Existing role spec is enough |
| Release Agent | [Release Agent](roles/release-agent.md) | Owns release readiness and commit/PR scope | Existing role spec is enough |
| Advisory Architect | [Advisory Architect](roles/advisory-architect.md) | Provides read-only architecture/context synthesis from project docs and `knowledge-base/` | Existing role spec is enough; keep read-only by default |
| Founder Interface / Personal Assistant | [Founder Interface / Personal Assistant](roles/founder-interface-personal-assistant.md) | Manages founder inbox, decisions, status briefings, and answer routing | Department pack remains the supporting contract |

Recommended wrapper home: `.github/prompts/factory/`. Keep canonical role truth in `04-agents/`; wrappers should link back here instead of duplicating entire packs.

The first wrapper files now live in [Factory Prompts](../.github/prompts/factory/README.md).

## Cross-Department Boundary Rules

| Overlap | Boundary Rule | Escalation / Gate |
|---|---|---|
| Product vs Marketing | Product owns product truth, scope, non-goals, and acceptance criteria. Marketing translates validated product truth into audience, positioning, copy, launch, tags, and market language. | If marketing copy changes meaning or positioning becomes strategic, Product / Feature Owner and Founder Interface decide before release. |
| Architecture vs Advisory Architect | Core Advisory Architect is read-only in v0. Architecture Lead, System Architect, Context Architect, tradeoff, and ADR roles are v1+ decompositions unless separately assigned a ticket. | ADR writing and ADR review must not self-approve; founder-level tradeoffs go through Founder Interface. |
| Review / QA vs Security Review | Review / QA owns fresh-context review, test adequacy, and specialist routing. Security / Privacy / Authority owns risk review when credentials, auth, permissions, external services, personal data, privacy, authority, destructive actions, or privileged automation appear. | Release waits for both Review / QA and Security / Privacy / Authority when both are triggered. |
| Knowledge / Documentation vs Optimization | Knowledge / Documentation captures state, decisions, docs, session history, and learning candidates. Optimization validates, edits, promotes, rejects, or parks reusable workflow, prompt, skill, agent, and template improvements. | Canonical `04-agents/` or `.github/skills/` changes need validation and release gates, not only documentation routing. |
| Release vs Review / QA | Review / QA produces review/test evidence. Release consumes that evidence, checks branch/staged scope, and decides commit/PR/release readiness. | If Release changes the staged or release scope after Review / QA signoff, request re-review before commit/PR readiness. |

## Role Cards

### Executive Orchestrator

Department: Executive Orchestration.

Permissions and boundaries:

- Can prepare, route, sequence, assign, block, and summarize Factory work.
- Can create follow-up tickets, founder inbox items, and context-pack requests.
- Cannot silently change product direction, approve its own execution, or commit directly.

Inputs:

- project state
- tasks and tickets
- blockers and dependencies
- reviewer and approval requirements
- progress/current-state docs

Outputs:

- routing decision
- assigned or blocked ticket
- next-action summary
- context-pack request
- follow-up tickets or founder inbox items

### Product / Feature Owner

Department: Product.

Permissions and boundaries:

- Can define product intent, scope, non-goals, and acceptance criteria.
- Can create or refine goals, features, tasks, and tickets.
- Cannot make founder-level product decisions without escalation.

Inputs:

- founder intent
- project spec and roadmap
- task/ticket context
- market, user, or source notes when relevant

Outputs:

- clarified intent
- acceptance criteria
- scope and non-goals
- product decision notes
- founder inbox item when needed

### Execution Agent

Department: Engineering.

Permissions and boundaries:

- Can edit files and produce artifacts inside assigned ticket scope.
- Can update run evidence and create self-review.
- Can create help or follow-up ticket recommendations.
- Cannot commit directly, expand scope, or own final release.

Inputs:

- assigned ticket
- context pack
- acceptance criteria
- constraints
- expected output format

Outputs:

- implementation or artifact
- run update
- self-review record
- test/check evidence
- handoff summary

### Review / QA Agent

Department: Review / QA.

Permissions and boundaries:

- Can review output against original intent and acceptance criteria.
- Can request revision and recommend specialist review.
- Can run or verify checks when appropriate.
- Cannot commit or release.

Inputs:

- ticket and task
- context pack
- run summary
- self-review
- changed files and test evidence

Outputs:

- fresh-context review record
- pass/fail/changes-requested decision
- required revisions
- specialist review routing
- follow-up ticket recommendations

### Release Agent

Department: Release / CI/CD.

Permissions and boundaries:

- Can decide release readiness and commit/PR scope.
- Can create release checklist and request revision.
- Can batch coherent tickets into a task-level release.
- Cannot bypass missing review, tests, docs, or founder approvals.

Inputs:

- ticket and task
- run evidence
- self-review and fresh-context review
- test evidence
- approval and inbox state
- changed files

Outputs:

- release checklist
- ready/rejected/revision decision
- commit or PR recommendation
- release notes and follow-ups

### Advisory Architect

Department: Architecture / Context.

Permissions and boundaries:

- Can read Factory/project docs and relevant `knowledge-base/` notes.
- Can synthesize architecture/context risks, options, and recommendations.
- Can recommend follow-up tickets, reviews, or founder questions.
- Cannot execute tickets, edit files, change ops state, or approve release unless separately assigned a different role.

Inputs:

- architecture or context question
- project/task/ticket context
- relevant source and knowledge notes
- constraints and approval level

Outputs:

- recommendation
- options and tradeoffs
- risks and assumptions
- relevant references
- suggested next action

### Founder Interface / Personal Assistant

Department: Founder Interface / Personal Assistant.

Permissions and boundaries:

- Can present founder inbox items, decisions, and status briefings to the owner.
- Can capture founder answers and route them back to blocked tickets, approvals, sessions, or project-state artifacts when assigned.
- Cannot decide on the owner's behalf, request secrets through chat, or bypass specialist review and release gates.

Inputs:

- founder inbox item or decision request
- related task, ticket, approval, release, blocker, or status context
- options, recommendation, and impact if unanswered
- relevant specialist review findings
- prior founder decisions or preferences when relevant

Outputs:

- concise founder-facing question or briefing
- captured answer or follow-up question
- routing summary for blocked work
- assigned state/docs updates or recommendations
- next-role handoff

## Authority Summary

| Authority | Roles |
|---|---|
| Can create or shape tickets | Executive Orchestrator, Product / Feature Owner |
| Can execute ticket work | Execution Agent, or another role only when explicitly assigned execution |
| Can self-review execution | Execution Agent |
| Can fresh-context review | Review / QA Agent; specialist reviewers when routed |
| Can provide read-only advisory synthesis | Advisory Architect |
| Can decide release readiness | Release Agent |
| Can capture and route founder answers | Founder Interface / Personal Assistant when assigned |
| Can commit directly | Release Agent only when project rules allow and all gates pass |
| Requires founder escalation | Any role when product direction, architecture, credentials, security/privacy, paid/external service, or project truth changes are involved |

## Prompt Wrapper Boundary

These remain operating contracts. Thin `.prompt.md` wrappers may now be created for the selected first wrapper set, but full custom agents should wait until manual use proves a role needs context isolation, tool restrictions, or autonomous subagent-style execution.

Prompt wrappers must:

- link back to this registry and the relevant role spec or department pack
- state required inputs, stop conditions, expected outputs, and handoff target
- preserve the authority boundaries above
- avoid embedding whole department packs as duplicated prompt text

## Department Packs

Additional reusable department packs extend this registry without automatically creating runnable agents:

- [Factory V0 Core Department Pack](departments/factory-v0-core-pack.md)
- [Factory Architecture / Context Architecture Department Pack](departments/factory-architecture-context-pack.md)
- [Factory Engineering Department Expansion Pack](departments/factory-engineering-expansion-pack.md)
- [Factory Founder Interface / Personal Assistant Department Pack](departments/factory-founder-interface-pack.md)
- [Factory Knowledge / Documentation Department Pack](departments/factory-knowledge-documentation-pack.md)
- [Factory Marketing Department Pack](departments/factory-marketing-pack.md)
- [Factory Product Department Expansion Pack](departments/factory-product-expansion-pack.md)
- [Factory Review / QA Department Expansion Pack](departments/factory-review-qa-expansion-pack.md)
- [Factory Release / CI-CD Department Expansion Pack](departments/factory-release-cicd-expansion-pack.md)
- [Factory Security / Privacy / Authority Department Pack](departments/factory-security-privacy-authority-pack.md)
- [Factory Optimization Department Pack](departments/factory-optimization-pack.md)