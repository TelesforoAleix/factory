# The Factory

Reusable AI development company operating system for the owner's projects.

The Factory is the design home for the agentic development team: product, architecture, engineering, review, release, documentation, security, context, and optimization roles working through a visible operating system.

It is not built for any single project. The Factory should be reusable for tools, products, demos, and client or project work.

## Quickstart

Factory Workbench runs a project end to end with **nothing else installed** — no
backend, no API key, no account. Python 3.11+ and `git` are all it needs.

```bash
pip install pyyaml

# See the whole loop run: 14 steps, 7 planted refusals, a deterministic fake adapter.
python3 acceptance/synthetic_project.py

# Then drive your own project.
python3 -m workbench.cli init ~/projects/my-project --project-id MYPROJ --title "My project"
python3 -m workbench.cli --project ~/projects/my-project \
    create task --title "First task" \
    --fields '{"intent":"why this exists","acceptance_criteria":["what done means"]}'

# Open the control plane.
python3 -m workbench.cli --project ~/projects/my-project serve
# -> http://127.0.0.1:8765/
```

`serve` binds loopback only and has no login: the OS user boundary is the
boundary. It is not built for public exposure.

Workbench holds **no** backend credential, no model registry and no tool
implementation. AI work goes through a configured execution adapter, and the one
that ships is a deterministic fake — so the quickstart above is repeatable, costs
nothing, and calls nothing.

## Entry Points

- [Workbench](workbench/README.md)
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

**Factory Workbench is executable.** The dashboard is no longer read-only: served
by `workbench serve`, it loads records as JSON from the local server and can
approve, advance and assign — every action going through one validated write
engine that the CLI shares.

What that replaces: the dashboard used to parse records in the browser with a
hand-rolled YAML subset parser that silently dropped nested structure. The server
parses now, so there is one parser and one validator in the system.

Still ahead: the full catalogue migration, and any real execution adapter — only
the deterministic fake exists, which is deliberate.

## Licence

CC BY-SA 4.0 — see [LICENSE](LICENSE).
