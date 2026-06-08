# Factory Dashboard

Read-only local HTML dashboard for The Factory's own operating state.

Open [index.html](index.html) in a browser to see the latest generated snapshot.

## Refresh

From the repository root:

```bash
python3 03-projects/ai-development-team/dashboard/generate_factory_dashboard.py
```

The dashboard is generated from the files under `03-projects/ai-development-team/ops/`. It does not write tickets, runs, approvals, or other operational state.

## Scope

- Shows current Factory tickets, runs, reviews, release readiness, inbox, approvals, and learning records.
- Links back to the source Markdown, YAML, and JSON records.
- Avoids server, database, CLI bridge, and write actions in this first slice.
