# Orchestrator Layer

## Current State

No personal orchestrator agent is active.

The previous personal assistant prompt/spec has been removed. The active operating model is now:

- Brain OS behavior lives in [../../.github](../../.github/README.md).
- Runnable brain-maintenance skills live in [../../.github/skills](../../.github/skills/README.md).
- Development-team skills live in [../skills](../skills/README.md).
- Future project or development agents should be added only when a repeated workflow needs persistent role scope, separate context, or tool boundaries.

## Functional Skills

| Skill | Purpose | Output |
|-------|---------|--------|
| Idea Logger | Captures ideas into structured backlog notes | `ideas/` entries |
| Knowledge Builder | Routes and processes source material through the brain OS | `inbox/`, `knowledge-base/`, indexes, sessions |
| Task Tracker | Logs tasks and activities | `session-logs/` entries |
| Session Archiver | Records conversation threads and session logs | `session-logs/` |

See [../skills](../skills/README.md) for development-team specs and [../../.github/skills](../../.github/skills/README.md) for brain OS skills.

## Always-On Instructions

Workspace-level Copilot behavior lives in `.github/copilot-instructions.md`. This is the default layer that should make every chat understand:

- raw source batches go to `inbox/`
- processed knowledge goes to `knowledge-base/`
- project ideas go to `ideas/`
- activated work goes to `03-projects/`
- every meaningful conversation gets a session note in `session-logs/`

The Copilot instructions are the baseline. Focused prompts or agents should be added only after a reusable workflow has been validated as a skill or method.

## Knowledge Processing Flow

1. Capture raw inputs in the inbox.
2. Process one source or theme when the owner asks for a deep dive.
3. Research the source and ask why it matters if that is unclear.
4. Save a source note under `knowledge-base/sources/`.
5. Distill reusable knowledge into `personal/`, `tools-and-tech/`, `markets/`, `domains/`, or `methods/`.
6. Link the result to ideas, project specs, and session logs.

## Agent Boundary Decision

No extra custom agent is needed yet for source processing. The current Brain OS `Knowledge Builder` skill should own capture and deep-dive workflows.

Add a dedicated source researcher or project lead agent only when the work needs a separate context window, a repeated multi-step workflow, or different tool permissions.

## Input Methods (Current → Future)
1. **VS Code / GitHub Copilot Chat** (current primary)
2. **Phone notes** — raw input shared manually for now
3. **Voice via Whisper** — phase 2
4. **Raw drops** — PDFs, YouTube links, articles, URLs
