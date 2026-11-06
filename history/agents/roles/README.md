# Roles

Reusable Factory role specs.

Role specs define responsibilities, boundaries, inputs, outputs, and workflow duties. They are not active custom agents yet.

## Current Role Specs

- [Executive Orchestrator](executive-orchestrator.md)
- [Product / Feature Owner](product-feature-owner.md)
- [Execution Agent](execution-agent.md)
- [Review / QA Agent](review-qa-agent.md)
- [Release Agent](release-agent.md)
- [Advisory Architect](advisory-architect.md)
- [Founder Interface / Personal Assistant](founder-interface-personal-assistant.md)

## Shared Operating Contract

All roles use [The Factory Manual Workflow](../../design/manual-workflow.md) until specific skills, prompts, CLI helpers, or dashboard flows exist.

Role authority, ticket powers, permissions, and boundaries are summarized in the [Factory Role Registry](../role-registry.md).

## Role Spec Rule

A role spec should answer:

- what the role owns
- what the role does not own
- what inputs it requires
- what artifacts it must produce
- how it participates in the manual workflow
- when it must stop or escalate
- what learning it should capture

Thin prompt wrappers now exist for the first Factory wrapper set under [Factory Prompts](../../prompts/factory/README.md). Do not create a full runnable custom agent until the role has been used manually and the needed prompt/context shape, isolation, and tool boundaries are clear.
