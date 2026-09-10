# The Factory

Reusable AI development company operating system for the owner's projects.

The Factory is the design home for the agentic development team: product, architecture, engineering, review, release, documentation, security, context, and optimization roles working through a visible operating system.

It is not built for any single project. The Factory should be reusable for tools, products, demos, and client or project work.

## Entry Points

- [Spec](spec.md)
- [Progress](progress.md)
- [Roadmap](roadmap.md)
- [Management Dashboard](dashboard/index.html)
- [Design Docs](design/README.md)
- [Templates](templates/README.md)

## Layer Boundary

- This folder holds the product/architecture/spec work for The Factory.
- This repository is also the live build home for The Factory itself while the operating system is being designed.
- The Factory's own operational state lives in the workspace of the project it is operating on, never in this repository.
- Reusable agent and skill definitions belong in [`agents/`](agents/README.md).
- Project-specific operational state should live inside each project workspace, not here by default.

## Current Status

Active self-hosting/spec phase. The first `ops/` templates exist, and a browser-side [management dashboard](dashboard/index.html) now loads local ops records for mission control, stage board, role roster, run ledger, release lane, context panel, decisions, approvals, and learning before CLI or writable dashboard automation.

## Licence

CC BY-SA 4.0 — see [LICENSE](LICENSE).
