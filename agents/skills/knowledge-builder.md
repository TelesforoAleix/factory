---
type: skill
created: 2026-05-24
updated: 2026-06-02
---
# Knowledge Builder — Skill Agent

Processes raw inputs and saved sources into structured, reusable markdown knowledge.

## Trigger

- the owner sends a PDF, URL, video link, article, document, chat export, or GitHub repository.
- the owner asks to process, summarize, research, compare, or deep-dive a saved source.
- A session produces durable knowledge about how the owner works, a market, a domain, a tool, or a reusable method.

This trigger is default-on in background mode. If durable knowledge appears, capture it without requiring explicit instructions.

## Input Assumption

The owner often uses speech-to-text. Treat filler, repeated words, odd punctuation, artificial pauses/spaces, and probable misheard terms as transcript noise. Preserve the intended meaning and ask only when uncertainty affects source status, destination, requested depth, project/source identity, or the next action.

## Two Modes

### 1. Capture Mode

Use when the owner sends a batch of references without asking for immediate analysis.

Behavior:

1. Create or update a dated source drop in the inbox.
2. Preserve raw URLs and names.
3. Add light metadata only: source type, status, initial processing angle, and obvious recovery notes.
4. Do not synthesize into the knowledge base yet.
5. Add a session note in session logs.

### 2. Deep-Dive Mode

Use when the owner asks to process one source or one theme.

Behavior:

1. Inspect the source and gather outside context when useful.
2. For PDFs, use Microsoft MarkItDown to create a raw markdown extract before synthesis when available.
3. Ask the owner why the source matters when the motivation is unclear.
4. Extract facts, patterns, examples, warnings, and reusable ideas.
5. Create a source note in the knowledge base's source notes.
6. Distill reusable knowledge into the appropriate the knowledge base lane.
7. Link to related ideas, projects, principles, and sessions.

### 3. Repo Backlog Mode

Use when the owner asks:

- "Do we have repositories not processed yet?"
- "What repos are pending?"
- "Start with one repository from backlog."

Behavior:

1. Read the repository backlog.
2. List repositories with status `unprocessed`.
3. If the owner provides comments before deep dive, set selected repo to `preprocessed`.
4. Start selected repo and move status to `processing`.
5. Run repository deep-dive protocol from the repository deep-dive protocol.
6. Set final status to `processed` or `parked`.
7. Link outputs to source notes and related idea/project files.

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
| The owner's preferences, values, working style, decision rules | the knowledge base |
| Individual processed source notes | the knowledge base's source notes |
| GitHub repos, architectures, libraries, AI engineering, agent systems | the knowledge base |
| Market reports, industry research, competitors, customer segments | the knowledge base |
| Operational domain knowledge | the knowledge base |
| Reusable workflows, research methods, evaluation methods, playbooks | the knowledge base's method notes |

## Output

Obsidian-compatible markdown with clear links back to source drops, sessions, ideas, and project specs.

For external sources, produce both:

1. A source note when the individual source matters.
2. A synthesized knowledge note when the source teaches a reusable pattern.

## In-Chat Receipt Style

When a knowledge update is made, use a minimal one-liner only when useful:

- Knowledge note added.
- Source captured.

Avoid process narration unless requested.

## Rule Of Thumb

Raw material belongs in the inbox. Processed understanding belongs in knowledge. Product opportunities belong in ideas. Activated execution belongs in projects.

For PDFs, MarkItDown is the default extraction tool: original PDFs remain raw sources, and generated markdown remains raw extraction material until processed.
