# Factory Prompts

Thin prompt wrappers for the first runnable Factory role set.

These prompts are workspace-level entry points. Canonical role truth remains in [Factory Role Registry](../../agents/role-registry.md), [Factory Roles](../../agents/roles/README.md), and [Factory Department Packs](../../agents/departments/README.md).

## Current Prompt Wrappers

- [Factory Executive Orchestrator](factory-executive-orchestrator.prompt.md)
- [Factory Product / Feature Owner](factory-product-feature-owner.prompt.md)
- [Factory Execution Agent](factory-execution-agent.prompt.md)
- [Factory Review / QA Agent](factory-review-qa-agent.prompt.md)
- [Factory Release Agent](factory-release-agent.prompt.md)
- [Factory Advisory Architect](factory-advisory-architect.prompt.md)
- [Factory Founder Interface / Personal Assistant](factory-founder-interface-personal-assistant.prompt.md)

## Boundary

- These are prompt wrappers, not full custom agents.
- They should route work through the manual Factory workflow and preserve the authority boundaries in the registry.
- They should not duplicate whole role specs or department packs.
- Promote a wrapper to a custom agent only after repeated use proves context isolation, tool restrictions, or autonomous subagent execution is needed.
