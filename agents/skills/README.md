# Skills

Workflow definitions used by the assistant layer.

## Current Skills

- [Idea Logger](idea-logger.md): capture product or project ideas into the right backlog.
- [Knowledge Builder](knowledge-builder.md): process links, documents, papers, videos, repositories, and source drops.
- [Session Archiver](session-archiver.md): produce session notes and preserve continuity.
- [Task Tracker](task-tracker.md): update current-state files and action tracking.

## Related Schema

- [Brain Workspace Instructions](../../.github/copilot-instructions.md)
- [LLM Wiki Health Check](../../knowledge-base/methods/llm-wiki-health-check.md)
- [Source Deep-Dive Workflow](../../knowledge-base/methods/source-deep-dive-workflow.md)

## Shared Input Assumption

Many of the owner's prompts are dictated through speech-to-text. All skills should treat filler, repeated words, odd punctuation, artificial pauses/spaces, and probable misheard words as transcript noise. Extract the main intent and ask one targeted clarification only when the ambiguity changes the output or next action.