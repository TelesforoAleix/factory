# Factory Role Registry

Status: v0 registry

This registry lists the first reusable Factory roles and their operating boundaries.

It is the coordination layer between individual role specs and the [Factory V0 Core Department Pack](departments/factory-v0-core-pack.md). It does not make any role a runnable custom agent yet.

## Operating Contract

All roles in this registry use:

- [The Factory Manual Workflow](../03-projects/ai-development-team/design/manual-workflow.md)
- [The Factory Operating Model](../03-projects/ai-development-team/design/operating-model.md)
- [Factory V0 Core Department](departments/factory-v0-core.md)

## Registry Table

| Role | Department | Role Type | Advisory / Execution Status | Ticket Powers | Review / Release Authority | Spec |
|---|---|---|---|---|---|---|
| Executive Orchestrator | Executive Orchestration | Coordinator / manager | Coordination role; may execute only when explicitly assigned a docs/ops ticket | Create, shape, route, assign, block, and sequence tickets | Can require review and release; cannot approve own execution or release | [Executive Orchestrator](roles/executive-orchestrator.md) |
| Product / Feature Owner | Product | Product owner / feature manager | Product-intent role; executes only product/docs tickets when assigned | Create and refine goals, features, tasks, tickets, scope, and acceptance criteria | Can judge product intent; cannot replace Review / QA or Release Agent | [Product / Feature Owner](roles/product-feature-owner.md) |
| Execution Agent | Engineering | Execution worker | Execution role | Work assigned ticket, update run evidence, create help/follow-up tickets | Owns self-review only; cannot approve external review, release, or commit | [Execution Agent](roles/execution-agent.md) |
| Review / QA Agent | Review / QA | Fresh-context reviewer / QA | Review role | Request revision, recommend follow-up tickets, route specialist review | Can pass/fail fresh-context review; cannot commit or release | [Review / QA Agent](roles/review-qa-agent.md) |
| Release Agent | Release / CI/CD | Release gatekeeper | Release role | Set release-readiness state, create release checklist, request revision or escalation | Owns release readiness and commit/PR scope; does not replace review | [Release Agent](roles/release-agent.md) |
| Advisory Architect | Architecture / Context | Advisory specialist | Advisory-only by default; read-only unless separately assigned an execution ticket | Recommend tickets, blockers, reviews, or options; should not update ticket state by default | Can provide specialist architecture/context advice; cannot approve release | [Advisory Architect](roles/advisory-architect.md) |

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

## Authority Summary

| Authority | Roles |
|---|---|
| Can create or shape tickets | Executive Orchestrator, Product / Feature Owner |
| Can execute ticket work | Execution Agent, or another role only when explicitly assigned execution |
| Can self-review execution | Execution Agent |
| Can fresh-context review | Review / QA Agent; specialist reviewers when routed |
| Can provide read-only advisory synthesis | Advisory Architect |
| Can decide release readiness | Release Agent |
| Can commit directly | Release Agent only when project rules allow and all gates pass |
| Requires founder escalation | Any role when product direction, architecture, credentials, security/privacy, paid/external service, or project truth changes are involved |

## V0 Boundary

These are operating contracts. Do not create runnable custom agents from this registry until at least one more manual workflow pass proves the required prompt/context shape.