# Session Archiver — Skill Agent

Records conversation insights and session summaries after every interaction.

## Trigger

End of every conversation / coding session, or whenever a substantial topic has been completed and should be preserved.

## Behavior

1. Extract key decisions, insights, challenges, open threads, and action items from the session.
2. Create a dated session note in `session-logs/`.
3. If any new ideas emerged, flag for Idea Logger.
4. If any knowledge was generated, flag for Knowledge Builder.
5. If decisions changed a project, update the relevant project docs.
6. If the session changed current focus, next actions, open threads, or project status, update Task Tracker outputs:
   - `session-logs/workboard.md`
   - relevant `03-projects/[project]/progress.md`

## Output Format

```markdown
# Session — YYYY-MM-DD — [Topic]

## Key Decisions
- ...

## Insights
- ...

## Challenges Raised
- ...

## Open Threads
- ...

## Action Items
- [ ] ...

## Files Changed
- ...
```

## Current-State Rule

The session note is the historical record. Do not rely on it alone for continuity.

After archiving, make sure the live current-state files still answer:

- What is the owner working on now?
- What changed in this project?
- What is pending next?
- What is parked or intentionally unresolved?
