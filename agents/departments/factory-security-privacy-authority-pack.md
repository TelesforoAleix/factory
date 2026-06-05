# Factory Security / Privacy / Authority Department Pack

Status: v0 department pack

This pack defines The Factory's reusable Security / Privacy / Authority department.

It protects projects from unsafe implementation, unclear permissions, privacy/GDPR drift, unapproved external services, insecure agent/tool behavior, and authority-model confusion while Factory-managed work moves through tickets.

## Operating Contract

Use this pack with:

- [The Factory Manual Workflow](../../03-projects/ai-development-team/design/manual-workflow.md)
- [The Factory Operating Model](../../03-projects/ai-development-team/design/operating-model.md)
- [Factory Role Registry](../role-registry.md)
- [Factory V0 Core Department Pack](factory-v0-core-pack.md)
- [Factory Knowledge / Documentation Department Pack](factory-knowledge-documentation-pack.md)
- [Factory Ops](../../03-projects/ai-development-team/ops/README.md)

This pack is an operating contract, not a set of runnable custom agents.

## Purpose

The Security / Privacy / Authority department makes risk visible before work ships.

It owns review and escalation for:

- application security risks
- agent/tool infrastructure security risks
- privacy and GDPR implications
- authority and permission boundaries
- credentials, secrets, tokens, and sensitive configuration
- external APIs, MCPs, paid services, and data processors
- user data, company data, personal data, and retention concerns
- unsafe automation or agent autonomy
- release blockers caused by unresolved risk

## Department Roles

| Role | Role Type | Advisory / Execution Status | Primary Responsibility |
|---|---|---|---|
| Security / Privacy Lead | Department lead | Coordination and gatekeeping | Routes security/privacy/authority review and decides escalation path |
| Application Security Reviewer | Specialist reviewer | Review role | Reviews product/application code, auth, validation, storage, and common appsec risks |
| Agent Infrastructure Security Reviewer | Specialist reviewer | Review role | Reviews agent tools, MCPs, prompt/tool authority, automation boundaries, and execution environment risk |
| Privacy / GDPR Reviewer | Specialist reviewer | Review role | Reviews personal data, lawful basis, consent, retention, processor, transfer, and data-subject concerns |
| Authority / Permission Reviewer | Specialist reviewer | Review role | Reviews who can do what, scoped permissions, approval thresholds, and organization authority models |
| Risk Gatekeeper | Release gate specialist | Gatekeeping role | Maps risks to approval levels, required reviewers, release blockers, and founder escalation |

## Activation Triggers

Activate this department when a ticket touches or implies:

- authentication, authorization, roles, permissions, sessions, admin functions, or access control
- credentials, API keys, tokens, secrets, environment variables, or local/private config
- external APIs, MCP servers, paid services, third-party processors, or hosted integrations
- personal data, employee data, user data, customer data, company confidential data, or sensitive records
- GDPR, consent, data retention, deletion, portability, audit, logging, or data residency concerns
- agent autonomy, tool use, browser automation, code execution, file-system access, or privileged actions
- retrieval, memory, knowledge stores, vector databases, graph databases, or sync pipelines containing private data
- payments, billing, legal, compliance, security settings, or production deployment
- destructive operations, migrations, deletion, irreversible writes, or bulk data actions
- any change whose failure could expose data, grant wrong authority, or silently mutate project truth

## Required Activation From Core Flow

Review / QA and Release must route work into this department when any activation trigger appears. A generic fresh-context review is not enough for Level 2 or Level 3 risk.

Minimum routing rules:

- Execution self-review should state whether security/privacy/authority concerns appeared.
- Fresh-context review should route triggered risks to Security / Privacy Lead or the required specialist reviewer.
- Release should block readiness when required risk review, approval, founder decision, mitigation, or documentation is missing.
- Founder Interface handles founder-level approvals or unresolved risk decisions; Security / Privacy / Authority records the risk and required approval path.

## Inputs

The department may need:

- task, ticket, context pack, run, review, release, approval, and inbox records
- changed files and artifacts
- architecture notes and data-flow diagrams
- data classification and data sources
- list of external services, APIs, MCPs, processors, and integrations
- credential/secrets handling approach
- permission model and role model
- user journeys that collect, expose, or change data
- test and validation evidence
- prior decisions, ADRs, founder approvals, and project constraints
- relevant laws/regulatory assumptions when known

## Outputs

The department produces or updates:

- security/privacy/authority review records
- risk summary and severity
- approval-level recommendation
- required reviewer list
- release blocker or pass decision
- founder inbox item when founder approval is needed
- approval records when the risk level requires permission
- mitigation requirements
- follow-up tickets for fixes or deeper review
- decision/ADR update when risk changes architecture or project truth
- learning candidate for reusable security/privacy/authority improvements

## Role Details

### Security / Privacy Lead

Owns:

- department routing
- deciding which specialist reviewers are required
- ensuring risk gets mapped to approval level
- coordinating with Product, Architecture, Review / QA, Release, and Knowledge / Documentation

Ticket powers:

- can require specialist review
- can recommend or create risk follow-up tickets
- can block release readiness until review is complete
- can request founder inbox or approval records

Boundaries:

- does not approve founder-level risk alone
- does not implement security fixes unless assigned a separate execution ticket
- does not replace Release Agent final repository gate

### Application Security Reviewer

Owns:

- auth and authorization checks
- input validation and output encoding risks
- insecure storage or transport concerns
- dependency and configuration security concerns
- common web/application security risks
- test evidence for appsec-sensitive changes

Ticket powers:

- can pass, fail, or request revision on application-security grounds
- can require additional tests or code review
- can recommend follow-up remediation tickets

Boundaries:

- does not approve privacy/GDPR risks alone
- does not decide product tradeoffs without Product / Feature Owner or founder approval
- does not commit fixes directly

### Agent Infrastructure Security Reviewer

Owns:

- agent tool permissions
- MCP/server trust and approval
- prompt/tool authority boundaries
- code execution and shell/file-system risk
- autonomous or background execution risk
- model/tool/knowledge access boundaries
- plugin, bridge, dashboard, or CLI security concerns

Ticket powers:

- can block unapproved external tool/MCP/API usage
- can require a founder inbox item for privileged automation
- can require stronger sandboxing, logging, or explicit approval

Boundaries:

- does not approve paid/external services without required approval
- does not implement infrastructure changes directly unless separately assigned
- does not bypass release review

### Privacy / GDPR Reviewer

Owns:

- personal-data identification
- lawful basis and consent concerns
- retention, deletion, portability, and audit implications
- data minimization and purpose limitation
- processor/subprocessor and transfer concerns
- privacy notices and user-facing explanations when relevant

Ticket powers:

- can block tickets that collect or process personal data without a clear basis
- can require founder approval for new privacy-sensitive flows
- can require documentation or decision records before release

Boundaries:

- does not provide legal advice as a substitute for counsel
- does not silently approve high-risk processing
- does not treat GDPR concerns as solved by vague notes

### Authority / Permission Reviewer

Owns:

- organization authority model
- user roles and permissions
- scoped access and least privilege
- who can approve what
- agent authority versus human authority
- private/public/project/company truth boundaries

Ticket powers:

- can require authority-model clarification
- can block changes that grant unclear or excessive permissions
- can request founder decision for unresolved authority tradeoffs

Boundaries:

- does not invent organization policy without founder/product input
- does not approve architecture changes alone
- does not replace privacy or appsec review

### Risk Gatekeeper

Owns:

- mapping risk to approval level
- deciding required reviewers for the risk profile
- verifying unresolved risk is represented as blockers, approvals, or founder inbox items
- advising Release Agent whether release readiness is blocked

Ticket powers:

- can block release readiness
- can require approval records
- can require founder inbox escalation
- can require additional specialist review

Boundaries:

- does not implement fixes
- does not make founder-level decisions
- does not mark release ready without Review / QA and Release Agent gates

## Risk To Approval Level Mapping

| Risk Profile | Approval Level | Required Reviewers | Release Rule |
|---|---|---|---|
| Docs-only, no security/privacy/authority effect | Level 0 | None beyond normal review | Can proceed through normal review/release |
| Low-risk internal change, no personal data, no new permissions, no external service | Level 1 | Review / QA; optional Security / Privacy Lead | Reviewer or release approval is enough |
| Auth, permissions, private data, logs, retention, external API/MCP/paid service, credential handling, or agent tool authority changes | Level 2 | Relevant specialist reviewer plus Risk Gatekeeper; founder inbox when decision is needed | Block release until review and explicit approval path are complete |
| New architecture/project-truth risk, high-risk automation, production/private data migration, legal/privacy ambiguity, credential exposure, destructive data action, or unresolved authority model | Level 3 | Security / Privacy Lead, relevant specialists, Risk Gatekeeper, Founder Interface, Architecture/Product as needed | Block until explicit product/architecture/founder decision resolves the risk |

## Required Reviewer Matrix

| Trigger | Required Reviewer |
|---|---|
| Application auth, session, validation, storage, API, dependency, or config risk | Application Security Reviewer |
| MCP, external tool, agent autonomy, shell/file-system access, plugin, CLI, dashboard bridge, or code execution risk | Agent Infrastructure Security Reviewer |
| Personal data, retention, deletion, consent, processor, transfer, privacy notice, or GDPR concern | Privacy / GDPR Reviewer |
| Roles, permissions, organization authority, agent authority, private/public boundaries, or approval thresholds | Authority / Permission Reviewer |
| Any Level 2 or Level 3 risk | Risk Gatekeeper |
| Multiple risk domains or uncertain routing | Security / Privacy Lead |

## Routing Rules

| Situation | Primary Role | Supporting Role |
|---|---|---|
| Risk domain is unclear | Security / Privacy Lead | Risk Gatekeeper |
| Product feature touches auth or permissions | Authority / Permission Reviewer | Application Security Reviewer, Product / Feature Owner |
| Ticket introduces external API/MCP/paid service | Agent Infrastructure Security Reviewer | Risk Gatekeeper, Founder Interface |
| Ticket touches personal data | Privacy / GDPR Reviewer | Knowledge / Documentation Lead, Product / Feature Owner |
| Ticket changes agent tool authority | Agent Infrastructure Security Reviewer | Advisory Architect, Risk Gatekeeper |
| Ticket changes release/deploy/security config | Application Security Reviewer | Release Agent |
| Ticket has unresolved founder-level risk | Risk Gatekeeper | Founder Interface, Executive Orchestrator |
| Risk decision must be preserved | Decision / ADR Archivist | Security / Privacy Lead |

## Required Artifacts

Depending on the ticket, this department should produce or update:

- review record with specialist area
- risk summary
- approval-level recommendation
- required reviewer list
- founder inbox item for founder-level decisions
- approval record when needed
- decision/ADR record when durable risk tradeoff is accepted
- release checklist blocker or pass note
- mitigation follow-up tickets
- learning candidate for reusable security/privacy/authority improvements

## Manual Workflow Participation

### Prepare

- identify whether the ticket activates this department
- assign required specialist reviewers
- map initial approval level
- stop if risk context is missing

### Execute

- usually advisory/review only
- execute only if separately assigned a scoped security/privacy/docs ticket

### Self-Review

- execution agent self-review should state whether security/privacy/authority concerns appeared

### Fresh-Context Review

- specialist reviewers inspect the relevant risk domain
- Risk Gatekeeper checks approval-level mapping

### Test

- require risk-appropriate validation, such as permission tests, privacy documentation checks, config review, or tool-permission review

### Release Readiness

- release is blocked if required review, approval, founder decision, or mitigation is missing

### Reflect And Learn

- create learning candidates for repeated risk patterns, missing templates, unclear approval thresholds, or rejected unsafe changes

## Stop Conditions

Stop and escalate when:

- risk domain or approval level is unclear
- ticket changes auth, permissions, personal data, external services, credentials, or agent authority without review
- founder approval is required but missing
- privacy/GDPR basis is unclear
- credentials/secrets may be exposed
- production/private data could be migrated, deleted, leaked, or silently mutated
- an MCP/API/tool/service is unapproved
- agent autonomy can perform privileged actions without clear human control
- release scope includes unresolved security/privacy/authority risk

## Relationship To Other Departments

- Executive Orchestrator routes risk-sensitive tickets into this department.
- Product / Feature Owner clarifies product intent and founder-facing tradeoffs.
- Advisory Architect helps with architecture/context risk synthesis.
- Review / QA coordinates fresh-context review but does not replace specialist risk review.
- Release Agent depends on Risk Gatekeeper for unresolved risk before release readiness.
- Knowledge / Documentation records decisions, ADRs, approvals, and reusable lessons.
- Founder Interface captures founder-level risk decisions and routes answers back to blocked tickets.

## Not In V0

- automated SAST/DAST tooling
- dependency scanning automation
- privacy impact assessment templates
- full legal/compliance playbooks
- production incident response process
- dashboard risk scoring
- runnable security/privacy custom agents

## First Use

Use this pack for Factory tickets that touch external services, agent authority, future dashboard/CLI bridges, project workspace permissions, [project] authority/privacy design, or any security/privacy-sensitive implementation.