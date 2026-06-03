# Factory V0 Core Department Pack

Status: v0 department pack

This pack defines the minimum reusable department setup for operating The Factory before CLI helpers or dashboard automation exist.

It packages the first reusable role specs into a usable company-like loop.

## Operating Contract

Use this pack with:

- [Factory Role Registry](../role-registry.md)
- [The Factory Manual Workflow](../../03-projects/ai-development-team/design/manual-workflow.md)
- [The Factory Operating Model](../../03-projects/ai-development-team/design/operating-model.md)
- [Factory V0 Core Department](factory-v0-core.md)

## Included Departments And Roles

| Department | Role | Status | Purpose |
|---|---|---|---|
| Executive Orchestration | [Executive Orchestrator](../roles/executive-orchestrator.md) | Coordination | Routes work and keeps task/ticket flow coherent |
| Product | [Product / Feature Owner](../roles/product-feature-owner.md) | Product ownership | Defines intent, scope, and acceptance criteria |
| Engineering | [Execution Agent](../roles/execution-agent.md) | Execution | Completes scoped ticket work and self-reviews |
| Review / QA | [Review / QA Agent](../roles/review-qa-agent.md) | Review | Performs fresh-context review and QA judgment |
| Release / CI/CD | [Release Agent](../roles/release-agent.md) | Release | Checks release readiness and commit/PR scope |
| Architecture / Context | [Advisory Architect](../roles/advisory-architect.md) | Advisory-only by default | Provides read-only architecture/context synthesis |

## Default Ticket Flow

```text
Executive Orchestrator -> Product / Feature Owner -> Execution Agent -> Review / QA Agent -> Release Agent -> Learning capture
```

Advisory Architect can be called before execution, during review, or before release when architecture/context risk is present.

## Activation Checklist

Before using this pack on a ticket, confirm:

- ticket belongs to exactly one task
- objective and acceptance criteria are clear
- context pack exists
- assigned execution role is clear
- required reviewers are listed
- approval level is known
- stop conditions have been checked

## Routing Matrix

| Ticket Need | Primary Role | Supporting Role |
|---|---|---|
| Ambiguous intent or scope | Product / Feature Owner | Executive Orchestrator |
| Work sequencing or assignment | Executive Orchestrator | Product / Feature Owner |
| Scoped implementation or artifact | Execution Agent | Executive Orchestrator |
| Self-review | Execution Agent | None |
| Fresh-context review | Review / QA Agent | Product / Feature Owner when product intent is at risk |
| Architecture/context advice | Advisory Architect | Executive Orchestrator |
| Release readiness | Release Agent | Review / QA Agent |
| Founder decision | Founder Interface later; Executive Orchestrator in v0 | Product / Feature Owner |
| Reusable workflow improvement | Knowledge/Optimization later; Executive Orchestrator in v0 | Any role may propose |

## Required Artifacts

This pack should leave the manual workflow artifacts:

- ticket
- context pack
- run record
- self-review record
- fresh-context review record
- validation/test evidence
- release checklist
- learning candidate when needed
- session note for meaningful work

## Permissions And Boundaries

- Execution Agent can edit only inside assigned ticket scope and cannot commit directly.
- Review / QA Agent can pass, fail, or request revision, but cannot release.
- Release Agent can approve release readiness, but cannot bypass missing review, tests, approvals, or founder decisions.
- Advisory Architect is read-only unless separately assigned an execution ticket.
- Product / Feature Owner can shape product truth, but founder-level decisions must be escalated.
- Executive Orchestrator can route work and create blockers, but should not replace specialist review.

## What Is Now Separate From This Pack

- Knowledge / Documentation role
- Optimization Department role
- Marketing role
- Security / Privacy / Authority role
- runnable prompt wrappers
- custom agent files
- CLI or dashboard automation

Founder Interface now has a dedicated [Founder Interface / Personal Assistant Department Pack](factory-founder-interface-pack.md).

## Promotion Rule

This pack is reusable, but still v0. Promote it toward runnable agents only after it survives more manual Factory tickets without major boundary changes.