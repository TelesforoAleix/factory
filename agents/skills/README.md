# Skills

Development-team workflow definitions used by the assistant layer.

Use this folder for skills that help build, review, plan, test, or ship the owner's ideas and projects.


## Current Skills

- [Factory Project Discovery](factory-project-discovery.md): run project kickoff discovery, version planning, postponed decisions, and first work hierarchy before Factory execution.

Idea Logger, Knowledge Builder, Session Archiver and Task Tracker used to be listed here. They are
knowledge-base skills, not method: they read and write one person's private notes, backlog and logs.
They live in that knowledge base's own repository and were removed from this one.

## Shared Input Assumption

Many of the owner's prompts are dictated through speech-to-text. All skills should treat filler, repeated words, odd punctuation, artificial pauses/spaces, and probable misheard words as transcript noise. Extract the main intent and ask one targeted clarification only when the ambiguity changes the output or next action.
