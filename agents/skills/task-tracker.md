---
type: skill
created: 2026-05-24
updated: 2026-06-02
---
# Task Tracker — Skill Agent

Maintains current work state across the brain. Session logs are historical; Task Tracker keeps the live dashboard and project progress files useful.

## Trigger

When a task, next action, open thread, active focus, project status change, or commitment is identified, assigned, started, completed, parked, or reprioritized.

This trigger is default-on. Keep current-state tracking updated in the background.

## Input Assumption

When extracting tasks from voice-dictated text, ignore filler, repetitions, unreliable punctuation, artificial pauses/spaces, and likely transcription artifacts. Ask only if the action, project, owner, priority, or timing is genuinely unclear.

## Current-State Files

- Global workboard: the workboard
- Project progress files: `03-projects/[project]/progress.md`
- Session history: session logs

## Behavior

1. Identify whether the item is global, project-specific, or both.
2. Update the workboard when current focus, active projects, next actions, open threads, or parked items change.
3. Update the relevant `03-projects/[project]/progress.md` when project phase, completed work, pending deep dives, next moves, or locked decisions change.
4. Link to the relevant session note instead of duplicating full history.
5. Keep current-state files short and scannable; detailed reasoning belongs in project docs or session logs.

## Output

- Updated global workboard in the workboard
- Updated project progress files in `03-projects/[project]/progress.md`
- Task/action references in session notes when relevant

## Rule of Thumb

Session logs answer: "What happened?"

The workboard and progress files answer: "Where are we now, and what should we pick up next?"

## In-Chat Receipt Style

When updates are made, keep the receipt minimal:

- Workboard updated.
- Progress updated.

Avoid operational explanations unless the owner asks.
