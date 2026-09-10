# Factory Optimization Department Pack

Status: v0 department pack

This pack defines The Factory's reusable Optimization department.

It turns lessons from Factory-managed work into validated improvements without letting every correction, one-off preference, or clever prompt mutation become canonical policy.

## Operating Contract

Use this pack with:

- [The Factory Manual Workflow](../../design/manual-workflow.md)
- [The Factory Operating Model](../../design/operating-model.md)
- [Factory Role Registry](../role-registry.md)
- [Factory V0 Core Department Pack](factory-v0-core-pack.md)
- [Factory Knowledge / Documentation Department Pack](factory-knowledge-documentation-pack.md)
- [Factory Security / Privacy / Authority Department Pack](factory-security-privacy-authority-pack.md)

This pack is an operating contract, not a runnable optimizer.

## Purpose

The Optimization department improves Factory agents, skills, templates, workflows, and operating docs through evidence.

It owns the bridge from experience to durable improvement:

```text
experience -> learning candidate -> triage -> validation -> promotion or rejection -> curated library
```

The core design is hybrid:

- Hermes-style learning intake captures lessons from real work, corrections, failures, repeated patterns, and session history.
- SkillOpt-style validation promotes only changes that pass representative tasks, review, and gates.

The department prevents two opposite failures:

- never learning from repeated work
- learning too aggressively and bloating canonical instructions

## Department Roles

| Role | Role Type | Advisory / Execution Status | Primary Responsibility |
|---|---|---|---|
| Optimization Lead | Department lead | Coordination and gatekeeping | Owns optimization routing, validation strategy, and promotion policy |
| Learning Intake Curator | Intake specialist | Advisory and light execution | Converts observations into well-formed learning candidates |
| Skill / Agent Evaluator | Evaluation specialist | Review/evaluation role | Scores candidate changes against validation tasks and rubrics |
| Skill / Agent Editor | Bounded-edit specialist | Execution only when assigned | Proposes or applies small edits to skills, agents, templates, or docs |
| Promotion Gatekeeper | Release-style gatekeeper | Gatekeeping role | Decides whether a candidate can promote, reject, park, or needs more validation |
| Learning Library Curator | Library maintenance specialist | Coordination and maintenance | Maintains active/stale/archived learning candidates, rejected-change memory, and reusable learning indexes |

## Activation Triggers

Activate this department when a ticket, review, session, or founder correction reveals:

- repeated agent failure
- repeated user correction
- unclear or missing workflow step
- weak template or schema field
- recurring review finding
- a useful tactic that should be reused
- a prompt/agent/skill boundary problem
- a candidate change to `agents/` assets
- a candidate change to Factory templates or manual workflow
- a rejected idea that agents may rediscover later
- a need to evaluate whether a local project lesson should become reusable
- a skill or agent that is becoming too broad, stale, duplicated, or over-specific

Do not activate this department for every tiny task. It is for reusable learning, not routine status updates.

## Inputs

The department may need:

- learning candidate records
- source ticket, task, run, review, release, approval, and inbox records
- session notes and transcripts when available
- user corrections or founder decisions
- current skill/agent/template/doc version
- proposed patch or candidate change
- validation tasks and scoring rubric
- baseline score and candidate score
- rejected-change history
- security/privacy/authority review when candidate changes tooling, permissions, scripts, prompts, or external services
- Knowledge / Documentation routing for provenance and writeback

## Outputs

The department produces or updates:

- learning candidate triage decision
- validation task or rubric
- candidate patch proposal
- evaluation result
- promotion, rejection, parked, or archived decision
- rejected-change memory
- versioned skill/agent/template snapshot when needed
- updated Factory docs, templates, or `agents/` assets after approval
- learning-library index or curation note
- follow-up tickets for validation, editing, security review, or documentation

## Role Details

### Optimization Lead

Owns:

- department routing
- choosing whether a lesson needs validation
- deciding validation depth and reviewers
- coordinating with Knowledge / Documentation and Security / Privacy / Authority
- protecting canonical assets from unvalidated mutation

Ticket powers:

- can create optimization tickets
- can require validation before release readiness
- can route candidates to evaluator, editor, or gatekeeper
- can park low-evidence candidates

Boundaries:

- does not edit canonical skills without evidence and review
- does not bypass founder approval for high-impact behavior changes
- does not treat one-off preferences as global policy without confirmation

### Learning Intake Curator

Owns:

- converting raw observations into structured learning candidates
- separating memory, session history, project state, workflow changes, template changes, skill changes, and rejected lessons
- preserving provenance from source tickets, runs, reviews, sessions, or founder corrections
- preventing vague lessons from entering the queue

Ticket powers:

- can create and update learning candidates
- can request missing evidence
- can mark candidates as project-specific, reusable, canonical-candidate, parked, or rejected for review

Boundaries:

- does not promote candidates
- does not edit canonical agents/skills
- does not create a new skill from every session

### Skill / Agent Evaluator

Owns:

- validation tasks
- scoring rubrics
- baseline versus candidate comparison
- regression detection
- deciding whether evidence is strong enough for promotion consideration

Ticket powers:

- can request or create validation tasks
- can fail a candidate when evidence is weak
- can recommend a smaller edit or broader test set

Boundaries:

- does not edit the candidate under evaluation
- does not promote directly
- does not use private/external model calls without approval when validation would expose sensitive data

### Skill / Agent Editor

Owns:

- small bounded edits to skills, role specs, department packs, prompts, templates, or workflow docs
- candidate patch proposals
- versioned candidate drafts when needed
- preserving old behavior unless evidence says to change it

Ticket powers:

- can propose append, replace, delete, or rewrite patches
- can create candidate versions
- can request review when an edit touches authority, security, privacy, or core workflow behavior

Boundaries:

- does not self-promote edits
- avoids large rewrites unless explicitly assigned
- cannot modify runnable/custom agent behavior without release and approval gates

### Promotion Gatekeeper

Owns:

- promotion decision
- rejection decision
- parked decision
- deciding whether approval or specialist review is required before promotion
- final check that evidence, validation, provenance, and rollback path exist

Ticket powers:

- can block promotion
- can require more validation
- can require Security / Privacy / Authority review
- can require founder approval for high-impact canonical behavior changes

Boundaries:

- does not evaluate its own edits as sole evidence
- does not promote candidates with unclear provenance
- does not delete rejected-change rationale

### Learning Library Curator

Owns:

- active, stale, parked, rejected, promoted, and archived learning queues
- duplicate candidate detection
- rejected-change memory
- stale learning cleanup
- usage/patch history when available
- library index and curation notes

Ticket powers:

- can archive stale candidates
- can merge duplicates
- can preserve rejection reasons
- can recommend validation or deletion with review

Boundaries:

- does not silently remove active candidates
- does not rewrite history
- does not promote without gatekeeper approval

## Learning Candidate Lifecycle

Use this lifecycle for Factory learning candidates.

```text
captured -> triaged -> candidate -> validation_ready -> validating -> promoted
                                      -> rejected
                                      -> parked
                                      -> archived
```

### 1. Captured

Project-local observation exists, usually in project `ops/learning/`.

Requirements:

- source object IDs
- problem observed
- proposed change or open question
- evidence
- initial scope guess

### 2. Triaged

Learning Intake Curator decides whether it is:

- project-specific
- reusable Factory pattern
- candidate for `agents/`
- candidate for Factory docs/templates
- memory/user preference
- source note or method note
- rejected or parked

### 3. Candidate

Candidate has a clear target artifact and proposed change.

Examples:

- update a role spec
- update a department pack
- update an ops template
- update manual workflow
- update a skill
- create a validation task
- record rejected-change memory

### 4. Validation Ready

Candidate has enough evidence and a proposed validation path.

Requirements:

- validation task or rubric
- baseline/current behavior
- success criteria
- risk level
- required reviewers

### 5. Validating

Skill / Agent Evaluator tests the candidate.

Possible validation:

- representative past tickets
- controlled examples
- review rubric
- regression check
- security/privacy/authority review
- comparison against current canonical behavior

### 6. Promoted

Promotion Gatekeeper approves writeback.

Promotion destinations:

- project-local docs or templates
- Factory design docs
- Factory ops templates
- `agents/` role specs, department packs, prompts, or skills
- knowledge-base maintenance skills only when it is a knowledge-base workflow and separately validated

Promoted candidates must update:

- learning candidate status
- target artifact
- session note
- progress/workboard/log when current state changes
- rejected-change memory if prior variants were rejected

### 7. Rejected

Candidate is not adopted.

Reject when:

- evidence is weak
- change is too project-specific
- validation regresses
- risk is too high
- it duplicates existing rules
- it would bloat canonical docs

Always preserve rejection reason.

### 8. Parked

Candidate is plausible but not worth acting on yet.

Park when:

- signal is promising but insufficient
- target artifact is not stable
- validation set does not exist yet
- implementation would be premature

### 9. Archived

Candidate is closed and retained for history.

Archive after promotion, rejection, or when stale parked candidates no longer matter.

## Project-Local To Central Promotion

Default path:

```text
project ops/learning -> Factory triage -> validation -> central promotion target
```

Rules:

- project-specific candidates stay in project ops unless repeated or reusable
- reusable Factory candidates can promote to this repository's docs and templates
- reusable agent/skill candidates can promote to `agents/` only after review and validation
- knowledge-base candidates promote to knowledge-base maintenance skills only when they manage the knowledge base itself and pass its validation layer
- Security / Privacy / Authority review is required for candidates that alter tools, permissions, external services, credential handling, or autonomous behavior
- founder approval is required for high-impact behavior changes, project truth changes, or external service usage

## Coordination With Knowledge / Documentation

Optimization depends on Knowledge / Documentation for provenance and continuity, but it owns reusable-system promotion decisions.

- Knowledge / Documentation captures session notes, state updates, decisions, docs changes, and initial learning candidates.
- Learning Candidate Router can send reusable or validation-needed candidates into Optimization.
- Optimization validates candidates, proposes bounded edits, preserves rejected-change rationale, and decides promotion, rejection, parking, or archive.
- Docs Reviewer should review documentation clarity after an optimization change, but docs review alone does not prove that a skill, prompt, agent, or workflow change should be promoted.

If Optimization promotes a change to `agents/`, Factory templates, or the knowledge base's maintenance skills, it should update the relevant docs/state trail through Knowledge / Documentation before release.

## Routing Rules

| Situation | Primary Role | Supporting Role |
|---|---|---|
| Raw lesson from ticket or session | Learning Intake Curator | Session Archivist |
| Candidate affects Factory docs/templates | Optimization Lead | Knowledge / Documentation Lead |
| Candidate affects role or department specs | Skill / Agent Editor | Review / QA, Promotion Gatekeeper |
| Candidate affects runnable prompts/skills/agents | Skill / Agent Evaluator | Security / Privacy / Authority when risk applies |
| Candidate needs validation tasks | Skill / Agent Evaluator | Optimization Lead |
| Candidate is ready for promotion | Promotion Gatekeeper | Knowledge / Documentation Lead, Release Agent |
| Candidate is stale or duplicated | Learning Library Curator | Learning Intake Curator |
| Candidate fails validation | Promotion Gatekeeper | Learning Library Curator |
| Candidate touches permissions, tools, MCPs, external APIs, credentials, or automation | Security / Privacy / Authority Department | Promotion Gatekeeper |

## Required Artifacts

Depending on candidate state, this department should produce or update:

- learning candidate record
- source ticket/run/review/session links
- triage decision
- validation task or rubric
- candidate patch or draft
- evaluation results
- promotion/rejection/parked decision
- rejected-change reason
- target artifact diff
- release checklist when promoted
- session note
- library/queue index when a candidate moves state

## Manual Workflow Participation

### Prepare

- identify whether a ticket may create reusable learning
- confirm learning candidate destination and target artifact if known

### Execute

- create or refine learning candidate records
- draft candidate edits only when assigned

### Self-Review

- check evidence, target, scope, and risk

### Fresh-Context Review

- verify the candidate is not overgeneralized from one example
- check whether current canonical docs already cover it

### Test

- run validation tasks or scoring rubric when needed
- compare baseline and candidate behavior

### Release Readiness

- Promotion Gatekeeper confirms validation, reviews, approvals, and rollback path before central promotion

### Reflect And Learn

- update library state and rejected-change memory

## Stop Conditions

Stop and escalate when:

- candidate lacks evidence
- target artifact is unclear
- proposed change is too broad
- validation set does not exist for a high-impact change
- candidate changes security/privacy/authority behavior without specialist review
- candidate would modify canonical `agents/` assets without review
- candidate would modify knowledge-base maintenance skills without the knowledge base's own validation
- founder approval is needed
- candidate repeats a previously rejected change
- promotion would bloat docs or make local quirks global

## Relationship To Source Patterns

Hermes contributes:

- experiential capture after real work
- separation of memory, session search, and skills
- background reflection concept
- curation/anti-bloat lifecycle
- preference for patching existing umbrella skills before creating new narrow skills

SkillOpt contributes:

- markdown skill/agent as trainable artifact
- bounded edits
- validation sets and scoring rubrics
- promotion gates
- best/current candidate distinction
- rejected-edit memory

The Factory uses both:

```text
Hermes for intake, SkillOpt for promotion, markdown/git for governance
```

## Not In V0

- automatic background learning daemon
- automatic canonical skill edits
- model-driven optimizer runs
- skill usage telemetry automation
- full session-search database
- dashboard learning queue
- cross-project learning sync automation

## First Use

Use this pack when the next Factory tickets reveal improvements to:

- manual workflow
- ops templates
- role registry
- department packs
- prompt wrappers
- custom agent specs
- project workspace template

Do not use it to mutate canonical assets automatically. The first several uses should remain manual and evidence-backed.
