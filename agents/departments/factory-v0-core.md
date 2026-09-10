# Factory V0 Core Department

Status: v0 reusable department spec

## Purpose

The Factory V0 Core department set defines the minimum reusable roles needed to operate Factory-managed work before dashboard or CLI automation exists.

The goal is not to create a large agent catalog. The goal is to make the first company-like loop reliable:

```text
intent -> ticket -> context pack -> execution -> self-review -> fresh review -> test -> release readiness -> learning
```

## Operating Contract

All roles in this department set use [The Factory Manual Workflow](../../design/manual-workflow.md).

They operate through:

- tasks
- tickets
- context packs
- run records
- review records
- release checklists
- founder inbox items when needed
- approvals when needed
- learning candidates

## Core Roles

| Role | Spec | Primary Responsibility |
|---|---|---|
| Executive Orchestrator | [executive-orchestrator.md](../roles/executive-orchestrator.md) | Route work, maintain task/ticket flow, coordinate roles |
| Product / Feature Owner | [product-feature-owner.md](../roles/product-feature-owner.md) | Define intent, acceptance criteria, scope, and product truth |
| Execution Agent | [execution-agent.md](../roles/execution-agent.md) | Complete scoped tickets and self-review before handoff |
| Review / QA Agent | [review-qa-agent.md](../roles/review-qa-agent.md) | Fresh-context review, QA judgment, and specialist routing |
| Release Agent | [release-agent.md](../roles/release-agent.md) | Release readiness, commit/PR scope, and final gatekeeping |
| Advisory Architect | [advisory-architect.md](../roles/advisory-architect.md) | Read-only architecture/context advice and risk synthesis |

## V0 Activation Rule

Use the smallest role set that can safely complete the ticket.

Default v0 path:

1. Executive Orchestrator prepares or routes the ticket.
2. Product / Feature Owner clarifies intent when needed.
3. Execution Agent completes scoped work.
4. Execution Agent performs self-review.
5. Review / QA Agent performs fresh-context review.
6. Release Agent checks release readiness.
7. Knowledge/Optimization responsibility captures learning candidates when needed.

Advisory Architect is called when the ticket involves architecture, context design, project structure, source interpretation, or reusable agent/system boundaries.

## Department Boundaries

This department does not own:

- the owner's final founder decisions
- canonical brain OS skills under the knowledge base's maintenance skills
- project-specific product truth outside the active project workspace
- direct commits from execution agents
- dashboard or CLI automation before the manual workflow is stable

## Required Artifacts

For Factory-managed work, the department should leave the artifacts required by the manual workflow:

- run record
- self-review record
- fresh-context review record
- test or validation evidence
- release checklist
- learning candidate when reusable learning appears
- session note for meaningful Factory work

## First Use

This department spec was created after the first Factory dogfood workflow proved that the operating objects are enough to run a ticket manually.

Related Factory evidence:

- [Manual Workflow](../../design/manual-workflow.md)
- [Internal Factory Ops Ticket](../../03-projects/ai-development-team/ops/tickets/TICKET-2026-0001-internal-factory-ops.yaml)
