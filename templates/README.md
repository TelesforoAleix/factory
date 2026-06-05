# The Factory Templates

Reusable template examples for installing The Factory into future project workspaces.

These files live inside the Factory project. They are copyable templates, not live operational state.

The Factory's live self-hosting operational state lives in [Factory Ops](../ops/README.md).

## Template Sets

- [Ops Templates](ops/README.md): copyable examples for task, ticket, run, founder inbox item, approval, context pack, review record, release checklist, and learning candidate objects.
- [Project Workspace Template](project-workspace/README.md): copyable folder scaffold for installing The Factory into future project workspaces.

## Boundary

- Templates here define the shape of future project workspaces.
- Real project operational state should later live in the target project's own `ops/` folder.
- Reusable agent and skill definitions still belong in [04-agents](../../../04-agents/README.md), not in this template folder.

## Next Template Work

1. Tighten templates based on the internal Factory dogfood pass.
2. Dogfood the project workspace template on the next real project workspace setup.
3. CLI/context-pack helper after the manual workflow is clear.
4. Dashboard prototype.