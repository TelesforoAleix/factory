# Orchestrator Layer

## Agents

### [removed: personal assistant]
Sparring partner, thinking mentor, brain organizer. The main interface between the owner and the brain.
- **Spec:** [removed.md](removed.md)
- **System prompt:** [removed.prompt.md](removed.prompt.md)

### Skill Agents (Functional)
| Agent | Purpose | Output |
|-------|---------|--------|
| Idea Logger | Captures ideas → structured backlog | `ideas/` entries |
| Knowledge Builder | Captures raw sources, then processes PDFs, videos, repos, articles, reports, and chats into durable knowledge | `inbox/` and `knowledge-base/` markdown files |
| Task Tracker | Logs tasks and activities | `session-logs/` entries |
| Session Archiver | Records conversation threads and session logs | `session-logs/` |

See `skills/` directory for individual specs.

### Future Agents
- Project Lead agents (per project)
- Dev agents (software development)
- These will be separate from [removed] — he provides context, they execute

## Architecture
```
                    ┌─────────────┐
                    │    the owner     │
                    └──────┬──────┘
                           │
                    ┌──────▼──────┐
                    │   [removed]     │  ← sparring, thinking, organizing
                    │  (personal) │
                    └──────┬──────┘
                           │ provides context to
              ┌────────────┼────────────┐
              ▼            ▼            ▼
        ┌──────────┐ ┌──────────┐ ┌──────────┐
        │ Project  │ │ Project  │ │   Dev    │
        │ Lead A   │ │ Lead B   │ │  Agents  │
        └──────────┘ └──────────┘ └──────────┘
```

## Always-On Instructions

Workspace-level Copilot behavior lives in `.github/copilot-instructions.md`. This is the default layer that should make every chat understand:

- raw source batches go to `inbox/`
- processed knowledge goes to `knowledge-base/`
- project ideas go to `ideas/`
- activated work goes to `03-projects/`
- every meaningful conversation gets a session note in `session-logs/`

[removed]'s prompt is still useful for explicit reflection, brainstorming, decision-making, and personal operating-system conversations. The Copilot instructions are the baseline; the prompt is the focused mode.

## Knowledge Processing Flow

1. Capture raw inputs in the inbox.
2. Process one source or theme when the owner asks for a deep dive.
3. Research the source and ask why it matters if that is unclear.
4. Save a source note under `knowledge-base/sources/`.
5. Distill reusable knowledge into `personal/`, `tools-and-tech/`, `markets/`, `domains/`, or `methods/`.
6. Link the result to ideas, project specs, and session logs.

## Agent Boundary Decision

No extra custom agent is needed yet for source processing. The current `Knowledge Builder` skill should own capture and deep-dive workflows.

Add a dedicated source researcher or project lead agent only when the work needs a separate context window, a repeated multi-step workflow, or different tool permissions.

## Input Methods (Current → Future)
1. **VS Code / GitHub Copilot Chat** (current primary)
2. **Phone notes** — raw input shared manually for now
3. **Voice via Whisper** — phase 2
4. **Raw drops** — PDFs, YouTube links, articles, URLs
