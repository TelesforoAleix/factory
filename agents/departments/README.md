# Departments

Reusable Factory department specs.

Departments define ownership boundaries and role groupings. They are not runnable agents by themselves; runnable prompts, skills, or custom agents should be created only after the department contract is stable.

## Current Department Specs

- [Factory V0 Core](factory-v0-core.md): first reusable operating department set for The Factory.
- [Factory V0 Core Department Pack](factory-v0-core-pack.md): packaged v0 role roster, routing matrix, permissions, and activation checklist.
- [Factory Architecture / Context Architecture Department Pack](factory-architecture-context-pack.md): reusable system architecture, context architecture, tradeoff, advisory, and ADR-review department.
- [Factory Engineering Department Expansion Pack](factory-engineering-expansion-pack.md): reusable implementation, refactoring, integration, debugging, engineering handoff, and context-pack execution department.
- [Factory Founder Interface / Personal Assistant Department Pack](factory-founder-interface-pack.md): reusable founder inbox, personal assistant, decision interview, status briefing, and decision-routing department.
- [Factory Knowledge / Documentation Department Pack](factory-knowledge-documentation-pack.md): reusable documentation, state, decision, session, and learning-routing department.
- [Factory Marketing Department Pack](factory-marketing-pack.md): reusable positioning, copy, launch materials, tags, market research, and marketing-review department.
- [Factory Product Department Expansion Pack](factory-product-expansion-pack.md): reusable idea intake, requirements, PRD, feature/task/ticket shaping, acceptance criteria, and product-drift review department.
- [Factory Security / Privacy / Authority Department Pack](factory-security-privacy-authority-pack.md): reusable security, privacy/GDPR, permissions, authority, and risk-gating department.
- [Factory Optimization Department Pack](factory-optimization-pack.md): reusable learning intake, validation, promotion, and curation department.

## Operating Contract

All Factory departments should use [The Factory Manual Workflow](../../03-projects/ai-development-team/design/manual-workflow.md) until CLI or dashboard automation exists.

## Boundary

- Department specs live here when they are reusable across projects.
- The Factory product/spec/design home remains [The Factory](../../03-projects/ai-development-team/README.md).
- Project-specific operational state belongs in that project's `ops/` folder.