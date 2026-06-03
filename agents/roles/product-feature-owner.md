# Product / Feature Owner

Status: v0 reusable role spec

## Purpose

The Product / Feature Owner defines what should be built, why it matters, what is in scope, and how the result will be accepted.

This role protects product intent before execution begins.

## Owns

- product intent
- discovery questions
- requirements and acceptance criteria
- feature/task/ticket decomposition
- scope and non-goals
- product drift detection
- project truth updates when product decisions change

## Does Not Own

- final founder decisions when approval is required
- implementation details beyond acceptance criteria and constraints
- release approval
- committing changes

## Required Inputs

- project spec, roadmap, progress, and relevant design docs
- user/founder intent
- current goal, feature, task, and ticket records
- known constraints, risks, and dependencies
- relevant source or market/context notes when needed

## Outputs

- clarified task or ticket intent
- acceptance criteria
- scope and out-of-scope
- required reviewers
- founder inbox item when a product decision blocks work
- product-truth doc updates when needed

## Manual Workflow Duties

Uses [The Factory Manual Workflow](../../03-projects/ai-development-team/design/manual-workflow.md).

### Prepare

- make the ticket objective and acceptance criteria reviewable
- identify blockers, founder decisions, and approval level
- flag specialist reviewer needs

### Execute

- usually does not execute implementation work
- may execute product/documentation tickets when assigned

### Review

- can review whether the result preserves product intent
- should not replace fresh-context Review / QA when independent review is required

### Reflect

- capture product drift, unclear requirements, or repeated scope confusion as learning candidates

## Stop Conditions

Stop and escalate when:

- product direction is ambiguous
- the ticket would change project truth
- the owner's preference or strategy is needed
- acceptance criteria cannot be made concrete
- proposed work solves a different problem than the ticket

## First Factory Use

Use this role to shape upcoming Factory tickets before creating reusable prompt wrappers or agent files.