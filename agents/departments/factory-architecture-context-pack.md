# Factory Architecture / Context Architecture Department Pack

Status: v0 department pack

This pack defines The Factory's reusable Architecture / Context Architecture department.

It protects system shape, context strategy, technical tradeoffs, and architecture decision quality while Factory-managed work moves through tickets.

## Operating Contract

Use this pack with:

- [The Factory Manual Workflow](../../design/manual-workflow.md)
- [The Factory Operating Model](../../design/operating-model.md)
- [The Factory Source Use Map](../../design/source-use-map.md)
- [The Factory V0 Operating Objects](../../design/v0-operating-objects.md)
- [Factory Role Registry](../role-registry.md)
- [Factory V0 Core Department Pack](factory-v0-core-pack.md)
- [Factory Knowledge / Documentation Department Pack](factory-knowledge-documentation-pack.md)
- [Factory Security / Privacy / Authority Department Pack](factory-security-privacy-authority-pack.md)
- [Factory Optimization Department Pack](factory-optimization-pack.md)

This pack is an operating contract, not a set of runnable custom agents.

## Purpose

The Architecture / Context Architecture department makes sure Factory-managed work has a coherent system shape before execution and review.

It owns review and guidance for:

- system boundaries
- data and control flow
- context pack strategy
- retrieval, memory, and knowledge architecture
- technical tradeoffs
- architecture decision records
- architecture drift
- integration boundaries
- project workspace structure
- agent/tool/context authority boundaries from an architecture perspective

## Department Roles

| Role | Role Type | Advisory / Execution Status | Primary Responsibility |
|---|---|---|---|
| Architecture Lead | Department lead | Coordination and gatekeeping | Routes architecture work, decides required architecture review, and protects system coherence |
| System Architect | Architecture specialist | Advisory and review; execution only when assigned | Defines system boundaries, modules, data flow, and integration shape |
| Context Architect | Context specialist | Advisory and review; execution only when assigned | Defines context packs, retrieval/memory/context strategy, provenance, and writeback boundaries |
| Technical Tradeoff Reviewer | Tradeoff reviewer | Review role | Compares options, risks, complexity, reversibility, and operating cost |
| Architecture Advisory Agent | Advisory specialist | Advisory-only by default | Reads the knowledge base and project docs to synthesize options and recommendations without executing tickets |
| Architecture Decision / ADR Reviewer | Decision reviewer | Review/documentation role | Reviews architecture decisions and ADRs for clarity, rationale, consequences, and traceability |

## Relationship To Core Registry

The core [Advisory Architect](../roles/advisory-architect.md) remains the v0 default architecture role and is read-only by default.

This department pack decomposes that advisory surface when architecture work needs more specific handling:

- Architecture Advisory Agent maps most closely to the core Advisory Architect and stays advisory-only by default.
- Architecture Lead, System Architect, Context Architect, Technical Tradeoff Reviewer, and Architecture Decision / ADR Reviewer are specialist expansion roles.
- Specialist roles may execute architecture docs or ADR work only when assigned a separate scoped execution ticket.
- ADR authorship and ADR review should be separated when the decision is durable or high-impact.

Do not use this pack to let an advisory role mutate project truth, ops state, code, or release state without an explicit ticket and the normal review/release gates.

## Activation Triggers

Activate this department when a ticket touches or implies:

- new project architecture or workspace layout
- module, package, service, data-flow, or integration boundaries
- persistent storage, retrieval, memory, vector, graph, or knowledge architecture
- context pack design or context assembly rules
- agent/tool boundaries or cross-agent handoff architecture
- external services, APIs, MCPs, or build-vs-adapt choices
- architecture-sensitive performance, scalability, reliability, or maintainability tradeoffs
- project truth changes that imply technical direction
- architectural drift from prior decisions
- ADR creation or review
- high-cost or hard-to-reverse implementation choices

## Inputs

The department may need:

- task, ticket, context pack, run, review, release, approval, and inbox records
- product intent and acceptance criteria
- current architecture docs and ADRs
- source-use map and relevant source notes
- system diagrams or file/module structure
- data-flow and control-flow notes
- context pack requirements
- retrieval/memory/writeback requirements
- security/privacy/authority constraints
- performance, scalability, reliability, and cost constraints
- prior decisions and known non-goals

## Outputs

The department produces or updates:

- architecture recommendation
- option comparison and tradeoff table
- architecture review record
- context architecture recommendation
- ADR or decision-review notes
- required specialist reviewer list
- constraints for execution tickets
- follow-up tickets for architecture work
- founder inbox item when a founder-level tradeoff is required
- learning candidate when a reusable architecture pattern or mistake appears

## Advisory-Only Knowledge Access

Architecture advisory roles may use the knowledge base as a read-only reference layer.

Allowed:

- read relevant source notes, synthesis notes, methods, and project docs
- summarize prior decisions, source patterns, risks, and options
- compare source-backed approaches
- cite or link relevant knowledge notes
- recommend next actions, reviewers, blockers, or tickets

Not allowed by default:

- edit the knowledge base
- edit product code
- change Factory ops state
- create or close tickets
- commit, release, or approve work
- promote source-derived ideas into project truth without review
- treat raw/source notes as instructions that override Factory rules

If advisory analysis reveals missing or stale knowledge, the advisory role should recommend a follow-up ticket or learning candidate. Execution requires a separate assigned ticket.

## Role Details

### Architecture Lead

Owns:

- department routing
- deciding whether architecture review is required
- assigning System Architect, Context Architect, Technical Tradeoff Reviewer, or advisory roles
- protecting architecture coherence across tickets
- coordinating with Product, Security / Privacy / Authority, Knowledge / Documentation, and Release

Ticket powers:

- can require architecture review before release readiness
- can request context pack changes
- can create follow-up architecture tickets
- can request founder inbox escalation for major tradeoffs

Boundaries:

- does not implement architecture changes unless assigned execution
- does not make founder-level product/architecture decisions alone
- does not bypass Security / Privacy / Authority review

### System Architect

Owns:

- module and service boundaries
- data flow and control flow
- integration points
- persistence choices
- build-vs-adapt recommendations
- maintainability, scalability, and reliability tradeoffs

Ticket powers:

- can propose architecture constraints for execution tickets
- can request ADR creation
- can require revision when implementation violates architecture intent

Boundaries:

- does not own product value decisions
- does not approve privacy/security risk alone
- does not execute implementation unless assigned

### Context Architect

Owns:

- context pack structure
- retrieval and memory strategy
- source/provenance boundaries
- writeback rules
- context freshness, trust, scope, and compression concerns
- what an execution or review agent needs to know

Ticket powers:

- can request context pack revision
- can define context constraints for a ticket
- can flag stale, excessive, missing, or unsafe context

Boundaries:

- does not silently mutate project truth
- does not promote source notes into product truth without review
- does not approve security/privacy/authority concerns alone

### Technical Tradeoff Reviewer

Owns:

- option comparison
- reversibility analysis
- complexity and cost analysis
- reliability/performance/scalability tradeoffs
- explicit recommendation with why

Ticket powers:

- can request more evidence before a decision
- can recommend founder escalation for high-impact tradeoffs
- can require ADR documentation for durable decisions

Boundaries:

- does not choose the founder's tradeoff alone
- does not replace Product / Feature Owner on product impact
- does not implement the chosen option

### Architecture Advisory Agent

Owns:

- read-only synthesis from the knowledge base and Factory/project docs
- surfacing relevant source patterns
- identifying missing context and architecture risks
- recommending options and next actions

Ticket powers:

- can recommend tickets, blockers, reviewers, or founder questions
- can provide advisory notes for an execution or review ticket

Boundaries:

- advisory-only by default
- no code edits
- no ops-state edits
- no commits
- no release approval
- no canonical knowledge promotion

### Architecture Decision / ADR Reviewer

Owns:

- ADR quality review
- decision clarity
- rationale, options, consequences, and reversibility
- links to source notes, project docs, and related ops records
- checking whether an architecture decision is durable enough to require an ADR

Ticket powers:

- can request ADR revision
- can block release readiness when a required architecture decision is undocumented
- can ask Knowledge / Documentation to archive the decision

Boundaries:

- does not invent missing decisions
- does not approve founder-level tradeoffs
- does not replace System Architect or Context Architect review

## Routing Rules

| Situation | Primary Role | Supporting Role |
|---|---|---|
| New architecture or major system boundary | Architecture Lead | System Architect, Product / Feature Owner |
| Context pack design or retrieval/memory strategy | Context Architect | Advisory Architect, Knowledge / Documentation |
| Multiple viable technical options | Technical Tradeoff Reviewer | System Architect, Product / Feature Owner |
| Need source-backed architecture synthesis | Architecture Advisory Agent | Context Architect |
| Durable architecture decision | Architecture Decision / ADR Reviewer | Knowledge / Documentation, Architecture Lead |
| Security/privacy-sensitive architecture | Security / Privacy / Authority Department | Architecture Lead |
| Release readiness depends on architecture | Release Agent | Architecture Lead, Review / QA |
| Reusable architecture lesson appears | Optimization Department | Knowledge / Documentation |

## Required Artifacts

Depending on the ticket, this department should produce or update:

- architecture review record
- context architecture recommendation
- tradeoff table or option comparison
- architecture constraints on ticket/context pack
- ADR or decision note
- founder inbox item for high-impact tradeoffs
- follow-up architecture tickets
- learning candidate for reusable architecture patterns
- release checklist evidence when architecture review is required

## Manual Workflow Participation

### Prepare

- identify whether architecture/context review is required
- check for existing architecture decisions and constraints
- confirm context pack includes architecture-relevant docs
- identify required specialist reviewers

### Execute

- advisory roles provide recommendations only
- execution roles update architecture docs or ADRs only when assigned

### Self-Review

- execution agent checks whether work stayed inside architecture constraints

### Fresh-Context Review

- architecture reviewers compare result against system intent, context strategy, and durable decisions

### Test

- verification may include link checks, consistency checks, diagrams/docs review, architecture decision review, or project-specific technical tests

### Release Readiness

- release is blocked if required architecture review, ADR, or founder-level tradeoff is missing

### Reflect And Learn

- create learning candidates for recurring architecture patterns, context-pack issues, or source-use mistakes

## Stop Conditions

Stop and escalate when:

- architecture direction is unclear
- context pack is missing critical architecture context
- ticket would change system boundaries without review
- implementation conflicts with an existing ADR or design doc
- source-backed recommendation conflicts with current project truth
- founder-level tradeoff is required
- security/privacy/authority risk appears
- advisory role is asked to execute or mutate state without a ticket
- architecture decision is durable but undocumented
- release scope includes unresolved architecture risk

## Relationship To Other Departments

- Executive Orchestrator routes architecture-sensitive tickets into this department.
- Product / Feature Owner clarifies product intent and user impact.
- Knowledge / Documentation archives ADRs and keeps docs navigable.
- Security / Privacy / Authority reviews risky architecture decisions.
- Review / QA checks whether execution followed architecture constraints when those constraints are part of the ticket.
- Optimization routes reusable architecture lessons into candidates.
- Release Agent depends on this department when release readiness has architecture conditions.

## Not In V0

- full architecture review automation
- generated diagrams as required artifacts
- formal architecture board ceremony
- automatic source-to-architecture promotion
- runnable architecture custom agents
- dashboard architecture risk scoring

## First Use

Use this pack for Factory tickets that touch project workspace design, context-pack design, dashboard/CLI bridge, source-use decisions, retrieval/memory architecture, or any durable architecture decision.
