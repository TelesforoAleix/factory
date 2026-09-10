# Skills

Development-team workflow definitions used by the assistant layer.

Use this folder for skills that help build, review, plan, test, or ship the owner's ideas and projects.


## Current Skills

- [Idea Logger](idea-logger.md): capture product or project ideas into the right backlog.
- [Factory Project Discovery](factory-project-discovery.md): run project kickoff discovery, version planning, postponed decisions, and first work hierarchy before Factory execution.
- [Knowledge Builder](knowledge-builder.md): process links, documents, papers, videos, repositories, and source drops.
- [Session Archiver](session-archiver.md): produce session notes and preserve continuity.
- [Task Tracker](task-tracker.md): update current-state files and action tracking.

## Shared Input Assumption

Many of the owner's prompts are dictated through speech-to-text. All skills should treat filler, repeated words, odd punctuation, artificial pauses/spaces, and probable misheard words as transcript noise. Extract the main intent and ask one targeted clarification only when the ambiguity changes the output or next action.
