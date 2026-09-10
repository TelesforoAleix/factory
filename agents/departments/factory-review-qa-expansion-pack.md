# Factory Review / QA Department Expansion Pack

Status: v0 department pack

This pack expands The Factory's Review / QA department beyond the core Review / QA Agent role.

It defines how fresh-context review, test planning, regression testing, UX/UI review routing, and revision-request review work together while keeping review and testing as separate stages before Release Agent evaluates release readiness.

## Operating Contract

Use this pack with:

- [The Factory Manual Workflow](../../design/manual-workflow.md)
- [The Factory Operating Model](../../design/operating-model.md)
- [The Factory V0 Operating Objects](../../design/v0-operating-objects.md)
- [Review Record Template](../../03-projects/ai-development-team/templates/ops/review-record.yaml)
- [Release Checklist Template](../../templates/ops/release-checklist.md)
- [Factory Role Registry](../role-registry.md)
- [Factory V0 Core Department Pack](factory-v0-core-pack.md)
- [Factory Knowledge / Documentation Department Pack](factory-knowledge-documentation-pack.md)
- [Factory Security / Privacy / Authority Department Pack](factory-security-privacy-authority-pack.md)
- [Factory Optimization Department Pack](factory-optimization-pack.md)

This pack is an operating contract, not a set of runnable custom agents.

## Purpose

The Review / QA department protects The Factory from accepting work that does not match intent, lacks evidence, skips needed tests, misses specialist risk, or becomes release-ready too early.

It owns:

- fresh-context review
- acceptance criteria checks
- review record quality
- test planning
- regression testing
- validation evidence adequacy
- UX/UI review routing
- revision request quality
- review/test separation
- specialist reviewer routing

It does not execute the original ticket, approve its own execution, commit, or replace Release Agent.

## Department Roles

| Role | Role Type | Advisory / Execution Status | Primary Responsibility |
|---|---|---|---|
| Review / QA Lead | Department lead | Coordination and gatekeeping | Routes review/QA work, decides required review depth, and protects review/test separation |
| Fresh-Context Reviewer | Review specialist | Review role | Reviews output against original intent, acceptance criteria, context pack, self-review, and evidence |
| Test Planner | QA planning specialist | Advisory and light execution | Defines appropriate verification for risk level, ticket type, and release surface |
| Regression Tester | QA execution specialist | Test role | Runs or verifies regression checks and records pass/fail evidence |
| UX/UI Review Router | Specialist routing role | Coordination and advisory | Detects user-facing/visual/interaction changes and routes UX/UI review when needed |
| Revision Request Reviewer | Revision review specialist | Review role | Checks whether requested revisions were addressed before work returns to release readiness |

## Relationship To Core Registry

The core [Review / QA Agent](../roles/review-qa-agent.md) remains the v0 default for fresh-context review and verification adequacy.

Use this expansion pack when review needs decomposition:

- Review / QA Lead routes review depth and specialist needs.
- Fresh-Context Reviewer handles intent, acceptance criteria, scope, self-review, and changed-artifact review.
- Test Planner and Regression Tester separate validation strategy from evidence collection.
- UX/UI Review Router and Revision Request Reviewer activate only when their surfaces appear.

Review / QA can route security/privacy/authority risk, but it does not replace the Security / Privacy / Authority department when that department's triggers appear.

## Activation Triggers

Activate this department when a ticket, run, or release candidate needs:

- fresh-context review after execution self-review
- acceptance criteria validation
- review record creation or quality check
- test plan or validation strategy
- regression testing or evidence review
- UX/UI review routing for user-facing changes
- specialist reviewer routing for security, privacy, authority, architecture, data, performance, marketing/copy, or context concerns
- revision request after failed review or testing
- review of a completed revision before release readiness
- release checklist evidence that reviews and tests are complete
- review/test learning capture after repeated failures

Do not activate this department to perform the original implementation. Review / QA may run or verify checks, but it should not become the execution role for the ticket under review.

## Inputs

The department may need:

- task and ticket records
- context pack
- run summary
- self-review record
- changed files or produced artifacts
- acceptance criteria
- scope and out-of-scope
- test/check evidence from execution
- required reviewers and approval level
- relevant product, architecture, security/privacy/authority, UX/UI, marketing, docs, or release constraints
- prior review findings and revision requests
- release checklist draft when release readiness is being evaluated

## Outputs

The department produces or updates:

- fresh-context review record
- acceptance criteria review findings
- test plan
- regression test evidence
- UX/UI review routing recommendation
- specialist reviewer routing recommendation
- revision request with concrete required changes
- revision verification record or finding
- follow-up ticket recommendations
- release checklist review/test evidence notes
- learning candidates for repeated review or testing gaps

## Role Details

### Review / QA Lead

Owns:

- department routing
- deciding review depth based on risk level and ticket type
- deciding whether Fresh-Context Reviewer, Test Planner, Regression Tester, UX/UI Review Router, or Revision Request Reviewer is needed
- coordinating with Engineering, Product, Architecture / Context, Security / Privacy / Authority, Knowledge / Documentation, Release, and Optimization
- protecting the boundary between review, testing, and release readiness

Ticket powers:

- can require fresh-context review before release readiness
- can require additional testing or specialist review
- can block release readiness when review/test evidence is missing or weak
- can request revision with concrete findings

Boundaries:

- does not execute the original ticket
- does not commit directly
- does not replace Release Agent final release decision
- does not approve security/privacy/authority risk alone

### Fresh-Context Reviewer

Owns:

- reading original ticket and context pack before judging output
- comparing result against original intent and acceptance criteria
- checking self-review quality
- inspecting changed files or artifacts at the right depth
- deciding whether the work passes, fails, or needs revision

Ticket powers:

- can pass, fail, or request changes on review grounds
- can request specialist review
- can recommend follow-up tickets
- can flag insufficient tests without becoming the Test Planner by default

Boundaries:

- does not implement fixes
- does not redefine the ticket after execution
- does not ignore missing self-review for non-trivial work
- does not decide release readiness alone

### Test Planner

Owns:

- defining appropriate verification for the ticket type
- mapping risk level to test depth
- distinguishing required tests from optional checks
- identifying manual QA, automated tests, parse checks, link checks, build checks, lint, type checks, or regression checks
- documenting what sufficient evidence would look like

Ticket powers:

- can require additional verification before release readiness
- can recommend test commands or manual QA steps
- can request specialist test input when needed

Boundaries:

- does not treat every docs change like a code release
- does not require heavy tests when lower-risk parse/link checks are enough
- does not replace Fresh-Context Reviewer judgment on intent fit

### Regression Tester

Owns:

- running or verifying regression checks
- comparing current behavior against expected behavior
- recording pass/fail evidence
- checking that revisions do not reintroduce known failures
- preserving failing command/output summaries when failures occur

Ticket powers:

- can fail testing when evidence or behavior is insufficient
- can request revision when regression fails
- can recommend follow-up tickets for unrelated failures

Boundaries:

- does not hide or hand-wave failing checks
- does not fix defects unless separately assigned an execution ticket
- does not broaden scope to unrelated regressions without routing

### UX/UI Review Router

Owns:

- detecting whether changed work affects visual UI, interaction, copy placement, accessibility, layout, flows, empty states, or user-facing behavior
- deciding whether UX/UI specialist review is required
- routing UI work to the right reviewer or follow-up ticket
- ensuring UI review does not disappear inside generic QA

Ticket powers:

- can require UX/UI review before release readiness
- can request screenshots, manual QA, browser checks, or design review evidence when appropriate
- can recommend follow-up UX/UI tickets

Boundaries:

- does not perform full design direction unless assigned
- does not replace Product or Marketing on user-facing intent/copy strategy
- does not approve accessibility or visual risk without appropriate evidence

### Revision Request Reviewer

Owns:

- making revision requests concrete and scoped
- checking whether requested revisions were actually addressed
- preventing vague review feedback from becoming churn
- deciding whether work can return to fresh-context review, testing, or release readiness

Ticket powers:

- can request clarification of vague review findings
- can pass or fail revision completion
- can recommend new tickets when a revision reveals out-of-scope work

Boundaries:

- does not add new acceptance criteria after the fact unless routed through Product/founder decision
- does not accept partial fixes as complete without evidence
- does not replace Release Agent final gate

## Review And Testing Separation

Review and testing are related but separate stages.

Review asks:

- Did the work solve the assigned ticket?
- Does it match original intent?
- Are acceptance criteria addressed?
- Is scope respected?
- Are required specialist reviewers present?
- Are docs/state changes coherent?
- Is the evidence sufficient for the risk level?

Testing asks:

- Does it work?
- Do commands/checks pass?
- Did behavior regress?
- Did parsing, links, builds, lint, type checks, manual QA, or browser checks pass when relevant?
- Are failures recorded with enough detail to route revision?

Default sequence:

```text
execution -> self-review -> fresh-context review -> testing -> release readiness
```

Practical notes:

- Review and testing can overlap in practice, but they must be recorded distinctly.
- A review can pass intent while tests fail.
- Tests can pass while review fails because the work solves the wrong problem.
- Release readiness requires both acceptable review and sufficient testing evidence.
- Release checklist records the final gate; Review / QA supplies the review/test evidence.

## Routing Rules

| Situation | Primary Role | Supporting Role |
|---|---|---|
| Execution completed and self-review exists | Fresh-Context Reviewer | Review / QA Lead |
| Test strategy is unclear | Test Planner | Engineering Lead, Release Agent |
| Regression or behavior check is needed | Regression Tester | Test Planner |
| UI/UX/user-facing changes appear | UX/UI Review Router | Product, Marketing, specialist UX/UI reviewer later |
| Review finds concrete problems | Revision Request Reviewer | Fresh-Context Reviewer |
| Revision claims are complete | Revision Request Reviewer | Regression Tester when tests were involved |
| Security/privacy/authority risk appears | Security / Privacy / Authority Department | Review / QA Lead |
| Architecture/context risk appears | Architecture / Context Department | Review / QA Lead |
| Docs/state drift appears | Knowledge / Documentation Department | Fresh-Context Reviewer |
| Release readiness is being evaluated | Release Agent | Review / QA Lead, Test Planner |
| Repeated review/test failure appears | Optimization Department | Knowledge / Documentation |

## Required Artifacts

Depending on the ticket, this department should produce or update:

- review record
- acceptance criteria check results
- test plan
- regression test evidence
- specialist review routing notes
- UX/UI review routing notes
- revision request
- revision verification finding
- follow-up ticket recommendations
- release checklist evidence references
- learning candidate for recurring review/test issues

## Manual Workflow Participation

### Prepare

- verify task, ticket, context pack, run summary, changed files, self-review, acceptance criteria, required reviewers, and approval level
- stop if self-review or essential context is missing for non-trivial work

### Fresh-Context Review

- compare output against original intent and acceptance criteria
- record decision, findings, risks, and required revisions in a review record

### Test

- plan and/or run appropriate verification
- record pass/fail evidence separately from review judgment
- route failures to revision or follow-up tickets

### Revision

- ensure requested revisions are concrete
- check whether revisions were completed before work returns to review, testing, or release readiness

### Release Readiness

- provide review/test evidence to Release Agent
- block release when required review, testing, specialist review, approval, docs, or state evidence is missing

### Reflect And Learn

- capture repeated review gaps, missing tests, weak acceptance criteria, vague revision feedback, or specialist-routing misses as learning candidates

## Stop Conditions

Stop and request revision, specialist review, or escalation when:

- self-review is missing for non-trivial work
- context pack, run summary, changed files, or acceptance criteria are missing
- review cannot determine original intent
- acceptance criteria are unmet or unreviewable
- test evidence is missing or insufficient for risk level
- regression checks fail
- changed files include unrelated work
- required specialist review is missing
- UX/UI changes lack appropriate review evidence
- work changes product, architecture, security/privacy/authority, or project truth without approval
- release checklist claims readiness without review/test evidence

## Boundaries

- Review / QA judges and tests; Engineering implements fixes.
- Review / QA can run or verify tests, but it does not own the original execution.
- Review / QA can block release readiness, but Release Agent owns the final release checklist and commit/PR decision.
- Review / QA routes security/privacy/authority, architecture/context, UX/UI, docs, marketing/copy, product, and performance concerns to specialist reviewers.
- Review / QA can recommend follow-up tickets, but Product/Executive Orchestrator owns work shaping.
- A Review / QA pass does not satisfy Security / Privacy / Authority review when risk triggers apply.
- If Release changes staged files, batching, or release scope after review, the changed scope must return to Review / QA.

## Not In V0

- full automated test framework
- browser automation suite
- visual regression platform
- performance lab
- accessibility audit program
- runnable QA custom agents
- release automation

## First Use

Use this pack for every Factory ticket that moves from execution toward release readiness, especially prompt wrappers, project templates, CLI/helper work, dashboard prototypes, integrations, bug fixes, refactors, and user-facing changes.
