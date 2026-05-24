# Knowledge Builder — Skill Agent

Processes raw inputs and saved sources into structured, reusable markdown knowledge.

## Trigger

- the owner sends a PDF, URL, video link, article, document, chat export, or GitHub repository.
- the owner asks to process, summarize, research, compare, or deep-dive a saved source.
- A session produces durable knowledge about how the owner works, a market, a domain, a tool, or a reusable method.

## Two Modes

### 1. Capture Mode

Use when the owner sends a batch of references without asking for immediate analysis.

Behavior:

1. Create or update a dated source drop in `inbox/`.
2. Preserve raw URLs and names.
3. Add light metadata only: source type, status, initial processing angle, and obvious recovery notes.
4. Do not synthesize into `knowledge-base/` yet.
5. Add a session note in `session-logs/`.

### 2. Deep-Dive Mode

Use when the owner asks to process one source or one theme.

Behavior:

1. Inspect the source and gather outside context when useful.
2. Ask the owner why the source matters when the motivation is unclear.
3. Extract facts, patterns, examples, warnings, and reusable ideas.
4. Create a source note in `knowledge-base/sources/`.
5. Distill reusable knowledge into the appropriate `knowledge-base/` lane.
6. Link to related ideas, projects, principles, and sessions.

## Interview Questions

Ask one to four focused questions before final synthesis when needed:

- What caught your attention here?
- Are you thinking of using it, modifying it, learning from it, or treating it as inspiration?
- Which part matters most: architecture, UX, market signal, workflow, code quality, evaluation, or positioning?
- What current project, idea, or principle might this connect to?
- What should we remember about this six months from now?

## Knowledge Placement

| Knowledge Type | Destination |
|----------------|-------------|
| the owner's preferences, values, working style, decision rules | `knowledge-base/personal/` |
| Individual processed source notes | `knowledge-base/sources/` |
| GitHub repos, architectures, libraries, AI engineering, agent systems | `knowledge-base/tools-and-tech/` |
| Market reports, industry research, competitors, customer segments | `knowledge-base/markets/` |
| Operational domain knowledge | `knowledge-base/domains/` |
| Reusable workflows, research methods, evaluation methods, playbooks | `knowledge-base/methods/` |

## Output

Obsidian-compatible markdown with clear links back to source drops, sessions, ideas, and project specs.

For external sources, produce both:

1. A source note when the individual source matters.
2. A synthesized knowledge note when the source teaches a reusable pattern.

## Rule Of Thumb

Raw material belongs in the inbox. Processed understanding belongs in knowledge. Product opportunities belong in ideas. Activated execution belongs in projects.
